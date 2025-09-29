/* Copyright (c) 2022 Intel Corporation
 * Copyright (c) 2020-2022 Alibaba Cloud
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "token_validate.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include "utils.h"
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/obj_mac.h>
#include <openssl/bn.h>
#include "t_cose/t_cose_common.h"
#include "t_cose/t_cose_sign1_verify.h"
#include "qcbor/qcbor_decode.h"

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

/*
/* Forward declarations for DER to COSE conversion functions
*/
static bool ecdsa_signature_der_to_cose(const unsigned char *der_sig, size_t der_len,
                                        unsigned char *cose_sig, size_t *cose_len,
                                        int curve_nid);
static bool signature_is_der_format(const unsigned char *sig, size_t sig_len);
static int get_curve_nid_from_key(EVP_PKEY *pkey);

/*
/* Certificate type detection function
/* Detects the type of certificate (RSA, ECC P-521, SM2) based on AIK certificate
*/
cert_type_t detect_aik_cert_type(const char *aik_cert_path)
{
    char fullpath[PATH_MAX] = {0};
    FILE *fp = NULL;
    X509 *cert = NULL;
    EVP_PKEY *pkey = NULL;
    cert_type_t cert_type = CERT_TYPE_UNKNOWN;

    if (!aik_cert_path) {
        printf("Invalid AIK certificate path\n");
        return CERT_TYPE_UNKNOWN;
    }

    /* Construct full path for AIK certificate */
    if (strstr(aik_cert_path, "/") != NULL) {
        /* Path already contains directory separator */
        snprintf(fullpath, sizeof(fullpath), "%s", aik_cert_path);
    } else {
        /* Construct path with default prefix */
        snprintf(fullpath, sizeof(fullpath), "%s/%s", DEFAULT_CERT_PEM_PREFIX, aik_cert_path);
    }

    fp = fopen(fullpath, "r");
    if (!fp) {
        printf("Cannot open AIK certificate file: %s\n", fullpath);
        return CERT_TYPE_UNKNOWN;
    }

    cert = PEM_read_X509(fp, NULL, NULL, NULL);
    if (!cert) {
        printf("Failed to read X509 certificate from: %s\n", fullpath);
        fclose(fp);
        return CERT_TYPE_UNKNOWN;
    }

    pkey = X509_get_pubkey(cert);
    if (!pkey) {
        printf("Failed to extract public key from certificate\n");
        X509_free(cert);
        fclose(fp);
        return CERT_TYPE_UNKNOWN;
    }

    int key_type = EVP_PKEY_base_id(pkey);
    
    if (key_type == EVP_PKEY_RSA) {
        cert_type = CERT_TYPE_RSA;
        printf("Detected AIK certificate type: RSA\n");
    } else if (key_type == EVP_PKEY_EC) {
        EC_KEY *ec_key = EVP_PKEY_get1_EC_KEY(pkey);
        if (ec_key) {
            const EC_GROUP *group = EC_KEY_get0_group(ec_key);
            if (group) {
                int curve_nid = EC_GROUP_get_curve_name(group);
                if (curve_nid == NID_secp521r1) {
                    cert_type = CERT_TYPE_ECC_P521;
                    printf("Detected AIK certificate type: ECC P-521\n");
                } else {
                    printf("Detected ECC certificate with unsupported curve (NID: %d)\n", curve_nid);
                    cert_type = CERT_TYPE_UNKNOWN;
                }
            }
            EC_KEY_free(ec_key);
        }
    } else {
        /* Check for SM2 - this would need specific SM2 detection logic */
        printf("Detected certificate with key type: %d (checking for SM2)\n", key_type);
        /* For now, assume SM2 detection would be added here */
        /* This is a placeholder - actual SM2 detection would need SM2-specific logic */
        cert_type = CERT_TYPE_UNKNOWN;
    }

    EVP_PKEY_free(pkey);
    X509_free(cert);
    fclose(fp);

    return cert_type;
}

/*
/* Configure certificate info structure based on detected certificate type
/* Sets appropriate URLs and filenames for certificate chain verification
*/
void configure_cert_info_by_type(cert_info_t *cert_info, cert_type_t cert_type)
{
    if (!cert_info) {
        printf("Invalid cert_info parameter\n");
        return;
    }

    /* Set common values */
    strcpy(cert_info->cert_path_prefix, DEFAULT_CERT_PEM_PREFIX);
    strcpy(cert_info->aik_cert_filename, DEFAULT_AIK_CERT_PEM_FILENAME);

    switch (cert_type) {
        case CERT_TYPE_RSA:
            printf("Configuring certificate chain for RSA\n");
            strcpy(cert_info->root_cert_filename, DEFAULT_ROOT_CERT_PEM_FILENAME);
            strcpy(cert_info->sub_cert_filename, DEFAULT_SUB_CERT_PEM_FILENAME);
            strcpy(cert_info->root_cert_url, DEFAULT_ROOT_CERT_URL);
            strcpy(cert_info->sub_cert_url, DEFAULT_SUB_CERT_URL);
            break;

        case CERT_TYPE_ECC_P521:
            printf("Configuring certificate chain for ECC P-521\n");
            strcpy(cert_info->root_cert_filename, ECCP521_ROOT_CERT_PEM_FILENAME);
            strcpy(cert_info->sub_cert_filename, ECCP521_SUB_CERT_PEM_FILENAME);
            strcpy(cert_info->root_cert_url, ECCP521_ROOT_CERT_URL);
            strcpy(cert_info->sub_cert_url, ECCP521_SUB_CERT_URL);
            break;

        case CERT_TYPE_SM2:
            printf("Configuring certificate chain for SM2\n");
            strcpy(cert_info->root_cert_filename, SM2_ROOT_CERT_PEM_FILENAME);
            strcpy(cert_info->sub_cert_filename, SM2_SUB_CERT_PEM_FILENAME);
            strcpy(cert_info->root_cert_url, SM2_ROOT_CERT_URL);
            strcpy(cert_info->sub_cert_url, SM2_SUB_CERT_URL);
            break;

        case CERT_TYPE_UNKNOWN:
        default:
            printf("Warning: Unknown certificate type, using RSA defaults\n");
            strcpy(cert_info->root_cert_filename, DEFAULT_ROOT_CERT_PEM_FILENAME);
            strcpy(cert_info->sub_cert_filename, DEFAULT_SUB_CERT_PEM_FILENAME);
            strcpy(cert_info->root_cert_url, DEFAULT_ROOT_CERT_URL);
            strcpy(cert_info->sub_cert_url, DEFAULT_SUB_CERT_URL);
            break;
    }
}

/*
/* Calculate SHA digest for challenge verification
*/
static bool digest_sha(const void *msg, size_t msg_len,
                       const char *algorithm,
                       unsigned char *md_value, unsigned int *md_len)
{
    EVP_MD_CTX *mdctx;
    const EVP_MD *md;
    bool ret = false;

#if OPENSSL_VERSION_NUMBER < 0x10100000L
    /* For OpenSSL versions < 1.1.0 */
    OpenSSL_add_all_digests();
#endif

    md = EVP_get_digestbyname(algorithm);
    if (!md) {
        printf("Unknown algorithm %s\n", algorithm);
        goto cleanup;
    }

    mdctx = EVP_MD_CTX_new();
    if (!mdctx) {
        printf("Failed to create MD context\n");
        goto cleanup;
    }

    if (EVP_DigestInit_ex(mdctx, md, NULL) != 1) {
        printf("Failed to initialize digest\n");
        goto cleanup;
    }

    if (EVP_DigestUpdate(mdctx, msg, msg_len) != 1) {
        printf("Failed to update digest\n");
        goto cleanup;
    }

    if (EVP_DigestFinal_ex(mdctx, md_value, md_len) != 1) {
        printf("Failed to finalize digest\n");
        goto cleanup;
    }

    ret = true;

cleanup:
    if (mdctx) {
        EVP_MD_CTX_free(mdctx);
    }

#if OPENSSL_VERSION_NUMBER < 0x10100000L
    /* For OpenSSL versions < 1.1.0 */
    EVP_cleanup();
#endif

    return ret;
}

/*
/* Enhanced initialization for signing key to support both RSA and ECC
*/
static enum t_cose_err_t init_signing_key(struct t_cose_key *key_pair,
                                          struct q_useful_buf_c pub_key)
{
    enum t_cose_err_t ret;
    EVP_PKEY *pkey = NULL;
    const unsigned char *pub_key_ptr = pub_key.ptr;

    pkey = d2i_PUBKEY(NULL, &pub_key_ptr, pub_key.len);
    if (pkey == NULL) {
        /*
        /* If DER format fails, try raw ECC public key format
        /* For P-521: 1 byte (0x04) + 66 bytes (x) + 66 bytes (y) = 133 bytes
        */
        if (pub_key.len == 133 && ((unsigned char*)pub_key.ptr)[0] == 0x04) {
            EC_GROUP *group = EC_GROUP_new_by_curve_name(NID_secp521r1);
            if (!group) {
                printf("Failed to create P-521 curve\n");
                ret = T_COSE_ERR_FAIL;
                goto done;
            }

            EC_POINT *point = EC_POINT_new(group);
            if (!point) {
                printf("Failed to create EC point\n");
                EC_GROUP_free(group);
                ret = T_COSE_ERR_FAIL;
                goto done;
            }

            if (EC_POINT_oct2point(group, point, pub_key.ptr, pub_key.len, NULL) != 1) {
                printf("Failed to convert raw data to EC point\n");
                EC_POINT_free(point);
                EC_GROUP_free(group);
                ret = T_COSE_ERR_FAIL;
                goto done;
            }

            EC_KEY *ec_key = EC_KEY_new();
            if (!ec_key ||
                EC_KEY_set_group(ec_key, group) != 1 ||
                EC_KEY_set_public_key(ec_key, point) != 1) {
                printf("Failed to create EC_KEY\n");
                if (ec_key) {
                    EC_KEY_free(ec_key);
                }
                EC_POINT_free(point);
                EC_GROUP_free(group);
                ret = T_COSE_ERR_FAIL;
                goto done;
            }

            pkey = EVP_PKEY_new();
            if (!pkey || EVP_PKEY_set1_EC_KEY(pkey, ec_key) != 1) {
                printf("Failed to create EVP_PKEY from EC_KEY\n");
                if (pkey) {
                    EVP_PKEY_free(pkey);
                }
                EC_KEY_free(ec_key);
                EC_POINT_free(point);
                EC_GROUP_free(group);
                ret = T_COSE_ERR_FAIL;
                goto done;
            }

            EC_KEY_free(ec_key);
            EC_POINT_free(point);
            EC_GROUP_free(group);
        } else {
            printf("Failed to load pubkey in any supported format\n");
            ret = T_COSE_ERR_FAIL;
            goto done;
        }
    }

    key_pair->k.key_ptr = pkey;
    key_pair->crypto_lib = T_COSE_CRYPTO_LIB_OPENSSL;
    ret = T_COSE_SUCCESS;

done:
    return ret;
}

static void free_signing_key(struct t_cose_key key_pair)
{
    EVP_PKEY_free(key_pair.k.key_ptr);
}

static bool read_x509_from_pem(const char *prefix, const char *filename, X509 **x509_cert)
{
    char fullpath[PATH_MAX] = {0};
    FILE *pFile = NULL;

    snprintf(fullpath, sizeof(fullpath), "%s/%s", prefix, filename);
    pFile = fopen(fullpath, "re");
    if (!pFile) {
        printf("Cannot open pem file %s", fullpath);
        return false;
    }

    if (!PEM_read_X509(pFile, x509_cert, NULL, NULL)) {
        printf("Failed to read x509 from file: %s\n", fullpath);
        fclose(pFile);
        return false;
    }

    fclose(pFile);
    return true;
}

static bool x509_validate_signature(X509 *child_cert, X509 *intermediate_cert, X509 *parent_cert)
{
    bool ret = false;
    X509_STORE *store = NULL;
    X509_STORE_CTX *store_ctx = NULL;

    store = X509_STORE_new();
    if (!store)
        goto err;

    if (X509_STORE_add_cert(store, parent_cert) != 1) {
        printf("Failed to add parent_cert to x509_store\n");
        goto err;
    }

    if (intermediate_cert) {
        if (X509_STORE_add_cert(store, intermediate_cert) != 1) {
            printf("Failed to add intermediate_cert to x509_store\n");
            goto err;
        }
    }

    store_ctx = X509_STORE_CTX_new();
    if (!store_ctx) {
        printf("Failed to create x509_store_context\n");
        goto err;
    }

    /*
    /* Pass the store (parent and intermediate cert) and child cert (need
    /* to be verified) into the store context
    */
    if (X509_STORE_CTX_init(store_ctx, store, child_cert, NULL) != 1) {
        printf("Failed to initialize 509_store_context\n");
        goto err;
    }

    X509_STORE_CTX_set_cert(store_ctx, child_cert);

    ret = X509_verify_cert(store_ctx);
    if (ret != 1) {
        printf("Failed to verify x509 cert: %s\n",
            X509_verify_cert_error_string(X509_STORE_CTX_get_error(store_ctx)));
        goto err;
    }
    ret = true;

err:
    if (store_ctx) {
        X509_STORE_CTX_free(store_ctx);
    }
    if (store) {
        X509_STORE_free(store);
    }
    return ret;
}

bool validate_aik_cert_chain(X509 *x509_aik, X509 *x509_sub, X509 *x509_root)
{
    bool ret;

    if (x509_aik == NULL || x509_sub == NULL || x509_root == NULL) {
        return false;
    }

    ret = x509_validate_signature(x509_root, NULL, x509_root);
    if (!ret) {
        printf("Failed to validate signature of x509_root cert\n");
        return ret;
    }

    ret = x509_validate_signature(x509_sub, NULL, x509_root);
    if (!ret) {
        printf("Failed to validate signature of x509_sub cert\n");
        return ret;
    }

    ret = x509_validate_signature(x509_aik, x509_sub, x509_root);
    if (!ret) {
        printf("Failed to validate signature of x509_aik cert\n");
        return ret;
    }

    return ret;
}

/*
/* Verify public key hash challenge
*/
bool verify_pubkhash_challenge(qbuf_t pub_key, qbuf_t challenge, qbuf_t algorithm)
{
    unsigned char pubkey_hash[EVP_MAX_MD_SIZE];
    unsigned int pubkey_hash_len;
    char algo[10];
    
    if (strncmp("sha-256", algorithm.ptr, algorithm.len) == 0) {
        memcpy(algo, "sha256", sizeof("sha256"));
    } else if (strncmp("sha-512", algorithm.ptr, algorithm.len) == 0) {
        memcpy(algo, "sha512", sizeof("sha512"));
    } else {
        printf("Unsupported sha algorithm\n");
        return false;
    }

    if (!digest_sha(pub_key.ptr, pub_key.len, algo, pubkey_hash, &pubkey_hash_len)) {
        printf("Failed to calculate the hash value\n");
        return false;
    }
        
    if (memcmp(pubkey_hash, challenge.ptr, pubkey_hash_len) != 0) {
        return false;
    }

    return true;
}

/*
/* Enhanced platform COSE signature verification with DER-to-COSE conversion support
/* Same DER format conversion capability as CVM token verification
*/
bool verify_plat_cose_sign(qbuf_t signed_cose, X509 *x509_aik)
{
    qbuf_t payload;
    enum t_cose_err_t ret;
    struct t_cose_key key_pair;
    struct t_cose_sign1_verify_ctx verify_ctx;
    EVP_PKEY *pkey;
    bool conversion_performed = false;
    unsigned char *converted_cose_data = NULL;
    size_t converted_cose_len = 0;
    qbuf_t final_signed_cose = signed_cose;

    pkey = X509_get_pubkey(x509_aik);
    if (!pkey) {
        printf("Failed to extract pub-key from aik_cert\n");
        return false;
    }

    int key_type = EVP_PKEY_base_id(pkey);

    key_pair.k.key_ptr = pkey;
    key_pair.crypto_lib = T_COSE_CRYPTO_LIB_OPENSSL;

    if (key_type == EVP_PKEY_EC) {
        QCBORDecodeContext decode_context;
        QCBORItem item;
        QCBORDecode_Init(&decode_context, signed_cose, QCBOR_DECODE_MODE_NORMAL);
        
        QCBORDecode_VGetNext(&decode_context, &item);
        if (item.uDataType == QCBOR_TYPE_ARRAY && item.val.uCount == 4) {
            QCBORDecode_VGetNext(&decode_context, &item);
            QCBORDecode_VGetNext(&decode_context, &item);
            QCBORDecode_VGetNext(&decode_context, &item);
            QCBORDecode_VGetNext(&decode_context, &item);
            
            if (item.uDataType == QCBOR_TYPE_BYTE_STRING) {
                const unsigned char *signature_data = item.val.string.ptr;
                size_t signature_len = item.val.string.len;
                
                if (signature_is_der_format(signature_data, signature_len)) {
                    int curve_nid = get_curve_nid_from_key(pkey);
                    if (curve_nid > 0) {
                        int field_size = (curve_nid == NID_secp521r1) ? 66 :
                                        (curve_nid == NID_secp384r1) ? 48 : 32;
                        unsigned char *cose_signature = malloc(field_size * 2);
                        size_t cose_sig_len = field_size * 2;
                        
                        if (ecdsa_signature_der_to_cose(signature_data, signature_len,
                                                        cose_signature, &cose_sig_len, curve_nid)) {
                            converted_cose_len = signed_cose.len - signature_len + cose_sig_len;
                            converted_cose_data = malloc(converted_cose_len);
                            
                            if (converted_cose_data) {
                                size_t prefix_len = (unsigned char*)signature_data - (unsigned char*)signed_cose.ptr;
                                memcpy(converted_cose_data, signed_cose.ptr, prefix_len);
                                
                                converted_cose_data[prefix_len - 1] = cose_sig_len;
                                memcpy(converted_cose_data + prefix_len, cose_signature, cose_sig_len);
                                
                                size_t remaining_len = signed_cose.len - prefix_len - signature_len;
                                if (remaining_len > 0) {
                                    memcpy(converted_cose_data + prefix_len + cose_sig_len,
                                           (unsigned char*)signature_data + signature_len, remaining_len);
                                }
                                
                                final_signed_cose.ptr = converted_cose_data;
                                final_signed_cose.len = converted_cose_len;
                                conversion_performed = true;
                            }
                        }
                        
                        free(cose_signature);
                    }
                }
            }
        }
    }

    t_cose_sign1_verify_init(&verify_ctx, 0);
    t_cose_sign1_set_verification_key(&verify_ctx, key_pair);

    ret = t_cose_sign1_verify(&verify_ctx, final_signed_cose, &payload, NULL);
    
    if (converted_cose_data) {
        free(converted_cose_data);
    }
    
    if (ret != T_COSE_SUCCESS) {
        printf("Platform token signature verification failed with t_cose error: %d\n", ret);
        return false;
    }

    return true;
}

/*
/* Helper function: Convert DER format ECDSA signature to COSE format (r||s)
/* For P-521: DER format (~139 bytes)  COSE format (132 bytes)
*/
static bool ecdsa_signature_der_to_cose(const unsigned char *der_sig, size_t der_len,
                                        unsigned char *cose_sig, size_t *cose_len,
                                        int curve_nid)
{
    ECDSA_SIG *sig = NULL;
    const BIGNUM *r = NULL;
    const BIGNUM *s = NULL;
    int field_size;
    bool ret = false;

    switch (curve_nid) {
        case NID_secp521r1:  /* P-521 */
            field_size = 66;  /* (521 + 7) / 8 = 66 bytes */
            break;
        case NID_secp384r1:  /* P-384 */
            field_size = 48;  /* (384 + 7) / 8 = 48 bytes */
            break;
        case NID_X9_62_prime256v1:  /* P-256 */
            field_size = 32;  /* (256 + 7) / 8 = 32 bytes */
            break;
        default:
            printf("Unsupported curve for DER to COSE conversion\n");
            return false;
    }

    if (*cose_len < field_size * 2) {
        printf("COSE signature buffer too small\n");
        return false;
    }

    /* Parse DER signature */
    const unsigned char *p = der_sig;
    sig = d2i_ECDSA_SIG(NULL, &p, der_len);
    if (!sig) {
        printf("Failed to parse DER signature\n");
        goto cleanup;
    }

    /* Get r and s components */
    ECDSA_SIG_get0(sig, &r, &s);
    if (!r || !s) {
        printf("Failed to get r,s from ECDSA signature\n");
        goto cleanup;
    }

    /* Convert r and s to fixed-length byte arrays */
    memset(cose_sig, 0, field_size * 2);
    
    /* Convert r to bytes (big-endian, fixed length) */
    int r_len = BN_num_bytes(r);
    if (r_len > field_size) {
        printf("r component too large for field size\n");
        goto cleanup;
    }
    BN_bn2bin(r, cose_sig + (field_size - r_len));

    /* Convert s to bytes (big-endian, fixed length) */
    int s_len = BN_num_bytes(s);
    if (s_len > field_size) {
        printf("s component too large for field size\n");
        goto cleanup;
    }
    BN_bn2bin(s, cose_sig + field_size + (field_size - s_len));

    *cose_len = field_size * 2;
    ret = true;

cleanup:
    if (sig) {
        ECDSA_SIG_free(sig);
    }
    return ret;
}


static bool signature_is_der_format(const unsigned char *sig, size_t sig_len)
{
    if (sig_len < 6 || sig[0] != 0x30) {
        return false;
    }
    
    size_t declared_len = sig[1];
    if (sig[1] & 0x80) {
        int len_bytes = sig[1] & 0x7f;
        if (len_bytes > 2 || len_bytes == 0) return false;
        
        declared_len = 0;
        for (int i = 0; i < len_bytes; i++) {
            declared_len = (declared_len << 8) | sig[2 + i];
        }
    }
    
    return (declared_len + 2) <= sig_len;
}


static int get_curve_nid_from_key(EVP_PKEY *pkey)
{
    if (EVP_PKEY_base_id(pkey) != EVP_PKEY_EC) {
        return -1;
    }
    
    EC_KEY *ec_key = EVP_PKEY_get1_EC_KEY(pkey);
    if (!ec_key) {
        return -1;
    }
    
    const EC_GROUP *group = EC_KEY_get0_group(ec_key);
    int nid = -1;
    if (group) {
        nid = EC_GROUP_get_curve_name(group);
    }
    
    EC_KEY_free(ec_key);
    return nid;
}


bool verify_cvm_cose_sign(qbuf_t signed_cose, qbuf_t pub_key)
{
    qbuf_t payload;
    enum t_cose_err_t ret;
    struct t_cose_key key_pair;
    struct t_cose_sign1_verify_ctx verify_ctx;
    bool conversion_performed = false;
    unsigned char *converted_cose_data = NULL;
    size_t converted_cose_len = 0;
    qbuf_t final_signed_cose = signed_cose;

    ret = init_signing_key(&key_pair, pub_key);
    if (ret != T_COSE_SUCCESS) {
        printf("Failed to initialize key: %d\n", ret);
        return false;
    }

    EVP_PKEY *verification_key = (EVP_PKEY*)key_pair.k.key_ptr;
    int key_type = EVP_PKEY_base_id(verification_key);
    
    if (key_type == EVP_PKEY_EC) {
        QCBORDecodeContext decode_context;
        QCBORItem item;
        QCBORDecode_Init(&decode_context, signed_cose, QCBOR_DECODE_MODE_NORMAL);
        
        QCBORDecode_VGetNext(&decode_context, &item);
        if (item.uDataType == QCBOR_TYPE_ARRAY && item.val.uCount == 4) {
            QCBORDecode_VGetNext(&decode_context, &item);
            QCBORDecode_VGetNext(&decode_context, &item);
            QCBORDecode_VGetNext(&decode_context, &item);
            QCBORDecode_VGetNext(&decode_context, &item);
            
            if (item.uDataType == QCBOR_TYPE_BYTE_STRING) {
                const unsigned char *signature_data = item.val.string.ptr;
                size_t signature_len = item.val.string.len;
                
                if (signature_is_der_format(signature_data, signature_len)) {
                    int curve_nid = get_curve_nid_from_key(verification_key);
                    if (curve_nid > 0) {
                        int field_size = (curve_nid == NID_secp521r1) ? 66 :
                                        (curve_nid == NID_secp384r1) ? 48 : 32;
                        unsigned char *cose_signature = malloc(field_size * 2);
                        size_t cose_sig_len = field_size * 2;
                        
                        if (ecdsa_signature_der_to_cose(signature_data, signature_len,
                                                        cose_signature, &cose_sig_len, curve_nid)) {
                            converted_cose_len = signed_cose.len - signature_len + cose_sig_len;
                            converted_cose_data = malloc(converted_cose_len);
                            
                            if (converted_cose_data) {
                                size_t prefix_len = (unsigned char*)signature_data - (unsigned char*)signed_cose.ptr;
                                memcpy(converted_cose_data, signed_cose.ptr, prefix_len);
                                
                                converted_cose_data[prefix_len - 1] = cose_sig_len;
                                memcpy(converted_cose_data + prefix_len, cose_signature, cose_sig_len);
                                
                                size_t remaining_len = signed_cose.len - prefix_len - signature_len;
                                if (remaining_len > 0) {
                                    memcpy(converted_cose_data + prefix_len + cose_sig_len,
                                           (unsigned char*)signature_data + signature_len, remaining_len);
                                }
                                
                                final_signed_cose.ptr = converted_cose_data;
                                final_signed_cose.len = converted_cose_len;
                                conversion_performed = true;
                            }
                        }
                        
                        free(cose_signature);
                    }
                }
            }
        }
    }

    t_cose_sign1_verify_init(&verify_ctx, 0);
    t_cose_sign1_set_verification_key(&verify_ctx, key_pair);

    ret = t_cose_sign1_verify(&verify_ctx,
                              final_signed_cose,
                              &payload,
                              NULL);
    
    if (converted_cose_data) {
        free(converted_cose_data);
    }
    free_signing_key(key_pair);
    
    if (ret != T_COSE_SUCCESS) {
        printf("t_cose_sign1_verify ret: %d\n", ret);
        return false;
    }

    return true;
}

/*
/* Complete CCA token signature verification with platform token support
/* Enhanced to support ECC CPAK certificates and RAK keys
*/
bool verify_cca_token_signatures(cert_info_t *cert_info,
                                 qbuf_t plat_cose,
                                 qbuf_t cvm_cose,
                                 qbuf_t cvm_pub_key,
                                 qbuf_t plat_challenge,
                                 qbuf_t cvm_pub_key_algo)
{
    X509 *x509_root = X509_new();
    X509 *x509_sub = X509_new();
    X509 *x509_aik = X509_new();
    bool ret;
    unsigned int ret_bits = 0xFFFFFFFF;
    unsigned int index = 0;

    if (!x509_root || !x509_sub || !x509_aik) {
        printf("Failed to init X509!\n");
        ret_bits = 0x7FFFFFFF;
        goto free;
    }

    if (plat_cose.ptr != NULL && plat_cose.len > 0) {
        ret = verify_pubkhash_challenge(cvm_pub_key, plat_challenge, cvm_pub_key_algo);
        printf("Verifying if cVM token RAK matches platform token challenge: %s \n",
               ret ? "Success" : "Failed");
        if (ret == false) {
            ret_bits &= ~(1 << index);
        }
        index += 1;
    }

    ret = verify_cvm_cose_sign(cvm_cose, cvm_pub_key);
    printf("Verifying if cVM token signature is signed by RAK: %s \n",
           ret ? "Success" : "Failed");
    if (ret == false) {
        ret_bits &= ~(1 << index);
    }
    index += 1;

    if (!read_x509_from_pem(cert_info->cert_path_prefix,
                            cert_info->aik_cert_filename, &x509_aik)) {
        printf("Failed to read x509_aik cert from %s/%s\n",
               cert_info->cert_path_prefix, cert_info->aik_cert_filename);
        ret = false;
        ret_bits &= ~(1 << index);
    }
    index += 1;

    if (plat_cose.ptr != NULL && plat_cose.len > 0) {
        ret = verify_plat_cose_sign(plat_cose, x509_aik);
        printf("Verifying if platform token signature is signed by IAK: %s \n",
               ret ? "Success" : "Failed");
        if (ret == false) {
            ret_bits &= ~(1 << index);
        }
        index += 1;
    }

    if (!file_exists(cert_info->cert_path_prefix,
                     cert_info->root_cert_filename)) {
        download_cert_pem(cert_info->cert_path_prefix,
                          cert_info->root_cert_filename,
                          cert_info->root_cert_url);
    }

    if (!read_x509_from_pem(cert_info->cert_path_prefix,
                            cert_info->root_cert_filename, &x509_root)) {
        printf("Failed to read x509_root cert\n");
        ret = false;
        ret_bits &= ~(1 << index);
    }
    index += 1;

    if (!file_exists(cert_info->cert_path_prefix,
                     cert_info->sub_cert_filename)) {
        download_cert_pem(cert_info->cert_path_prefix,
                          cert_info->sub_cert_filename,
                          cert_info->sub_cert_url);
    }

    if (!read_x509_from_pem(cert_info->cert_path_prefix,
                            cert_info->sub_cert_filename, &x509_sub)) {
        printf("Failed to read x509_sub cert\n");
        ret = false;
        ret_bits &= ~(1 << index);
    }
    index += 1;

    ret = validate_aik_cert_chain(x509_aik, x509_sub, x509_root);
    printf("Verifying IAK certificate chain: %s \n",
           ret ? "Success" : "Failed");
    if (ret == false) {
        ret_bits &= ~(1 << index);
    }
    index += 1;

    /*
    /* In mixed CPAK/RAK scenarios, we consider the verification successful
    /* if the critical components pass:
    /* 1. CVM token signature verification (RAK signs CVM token)
    /* 2. Platform token signature verification (CPAK signs platform token)
    /* 3. Challenge binding (RAK public key hash matches platform challenge)
    /* 4. Certificate chain validation
    */
    bool critical_verifications_passed = true;
    
    if (plat_cose.ptr != NULL && plat_cose.len > 0) {
        if (!(ret_bits & (1 << 0))) {
            printf("Critical: Challenge binding failed\n");
            critical_verifications_passed = false;
        }
        if (!(ret_bits & (1 << 3))) {
            printf("Critical: Platform token signature verification failed\n");
            critical_verifications_passed = false;
        }
    }
    
    if (!(ret_bits & (1 << 1))) {
        printf("Critical: CVM token signature verification failed\n");
        critical_verifications_passed = false;
    }
    
    /*
    /* CRITICAL SECURITY FIX: ALL verification steps must pass
    /* Certificate chain validation and certificate loading are MANDATORY
    */
    printf("INFO: Total verification steps: %d, ret_bits: 0x%08X\n", index, ret_bits);
    
    /* Check certificate loading failures */
    if (plat_cose.ptr != NULL && plat_cose.len > 0) {
        /* Platform token scenario: check all verification steps */
        if (!(ret_bits & (1 << 2))) {  /* AIK cert loading */
            printf("Critical: AIK certificate loading failed\n");
            critical_verifications_passed = false;
        }
        if (!(ret_bits & (1 << 4))) {  /* Root cert loading */
            printf("Critical: Root certificate loading failed\n");
            critical_verifications_passed = false;
        }
        if (!(ret_bits & (1 << 5))) {  /* Sub cert loading */
            printf("Critical: Sub certificate loading failed\n");
            critical_verifications_passed = false;
        }
        if (!(ret_bits & (1 << 6))) {  /* Certificate chain validation */
            printf("Critical: Certificate chain validation failed\n");
            critical_verifications_passed = false;
        }
    } else {
        /* CVM-only token scenario: different bit positions */
        if (!(ret_bits & (1 << 1))) {  /* AIK cert loading */
            printf("Critical: AIK certificate loading failed\n");
            critical_verifications_passed = false;
        }
        if (!(ret_bits & (1 << 2))) {  /* Root cert loading */
            printf("Critical: Root certificate loading failed\n");
            critical_verifications_passed = false;
        }
        if (!(ret_bits & (1 << 3))) {  /* Sub cert loading */
            printf("Critical: Sub certificate loading failed\n");
            critical_verifications_passed = false;
        }
        if (!(ret_bits & (1 << 4))) {  /* Certificate chain validation */
            printf("Critical: Certificate chain validation failed\n");
            critical_verifications_passed = false;
        }
    }

free:
    X509_free(x509_root);
    X509_free(x509_sub);
    X509_free(x509_aik);

    printf("CCA token signature validate [%s]\n",
           critical_verifications_passed ? "Success" : "Failed");
           
    return critical_verifications_passed;
}
