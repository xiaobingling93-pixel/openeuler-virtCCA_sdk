/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef TOKEN_VALIDATE_H
#define TOKEN_VALIDATE_H

#include <openssl/x509.h>
#include "t_cose/q_useful_buf.h"
#include "token_parse.h"

/* Store the virtCCA certs downloaded from HUAWEI PKI */
/* RSA certificate chain URLs (legacy) */
#define DEFAULT_ROOT_CERT_URL "\"https://download.huawei.com/dl/download.do?actionFlag=download&nid=PKI1000000002&partNo=3001&mid=SUP_PKI\""
#define DEFAULT_SUB_CERT_URL "\"https://download.huawei.com/dl/download.do?actionFlag=download&nid=PKI1000000040&partNo=3001&mid=SUP_PKI\""

/* ECC P-521 certificate chain URLs */
#define ECCP521_ROOT_CERT_URL "\"https://download.huawei.com/dl/download.do?actionFlag=download&nid=PKI1100000224&partNo=3001&mid=SUP_PKI\""
#define ECCP521_SUB_CERT_URL "\"https://download.huawei.com/dl/download.do?actionFlag=download&nid=PKI1100000225&partNo=3001&mid=SUP_PKI\""

/* SM2 certificate chain URLs */
#define SM2_ROOT_CERT_URL "\"https://download.huawei.com/dl/download.do?actionFlag=download&nid=PKI1100000204&partNo=3001&mid=SUP_PKI\""
#define SM2_SUB_CERT_URL "\"https://download.huawei.com/dl/download.do?actionFlag=download&nid=PKI1100000226&partNo=3001&mid=SUP_PKI\""

#define DEFAULT_CERT_PEM_PREFIX "."
/* RSA certificate filenames (legacy) */
#define DEFAULT_ROOT_CERT_PEM_FILENAME "root_cert.pem"
#define DEFAULT_SUB_CERT_PEM_FILENAME "sub_cert.pem"

/* ECC P-521 certificate filenames */
#define ECCP521_ROOT_CERT_PEM_FILENAME "eccp521_root_cert.pem"
#define ECCP521_SUB_CERT_PEM_FILENAME "eccp521_sub_cert.pem"

/* SM2 certificate filenames */
#define SM2_ROOT_CERT_PEM_FILENAME "sm2_root_cert.pem"
#define SM2_SUB_CERT_PEM_FILENAME "sm2_sub_cert.pem"

#define DEFAULT_AIK_CERT_PEM_FILENAME "aik_cert.pem"
#define MAX_FILE_NAME_SIZE 100
#define MAX_FILE_PATH_SIZE 1000
#define MAX_URL_SIZE 1000

typedef struct {
    char cert_path_prefix[MAX_FILE_PATH_SIZE];
    char root_cert_filename[MAX_FILE_NAME_SIZE];
    char sub_cert_filename[MAX_FILE_NAME_SIZE];
    char aik_cert_filename[MAX_FILE_NAME_SIZE];
    char root_cert_url[MAX_URL_SIZE];
    char sub_cert_url[MAX_URL_SIZE];
} cert_info_t;

/* Certificate type enumeration */
typedef enum {
    CERT_TYPE_RSA = 0,
    CERT_TYPE_ECC_P521 = 1,
    CERT_TYPE_SM2 = 2,
    CERT_TYPE_UNKNOWN = -1
} cert_type_t;

/*
/* Certificate type detection and configuration functions
*/
cert_type_t detect_aik_cert_type(const char *aik_cert_path);
void configure_cert_info_by_type(cert_info_t *cert_info, cert_type_t cert_type);

bool validate_aik_cert_chain(X509 *x509_aik, X509 *x509_sub, X509 *x509_root);

bool verify_cvm_cose_sign(qbuf_t signed_cose, qbuf_t pub_key);

/*
/* Platform token validation functions
*/
bool verify_pubkhash_challenge(qbuf_t pub_key, qbuf_t challenge, qbuf_t algorithm);

bool verify_plat_cose_sign(qbuf_t signed_cose, X509 *x509_aik);

/*
/* Complete CCA token signature verification
*/
bool verify_cca_token_signatures(cert_info_t *cert_info,
                                 qbuf_t plat_cose,
                                 qbuf_t cvm_cose,
                                 qbuf_t cvm_pub_key,
                                 qbuf_t plat_challenge,
                                 qbuf_t cvm_pub_key_algo);

#endif /* TOKEN_VALIDATE_H */
