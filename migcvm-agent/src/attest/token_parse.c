/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */
#include "token_parse.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool check_item_type_size(const QCBORItem *item, int data_type,
                                 const int *sizes, int num_sizes)
{
    if (item->uDataType != data_type) {
        return false;
    }
    if (sizes != NULL && num_sizes > 0) {
        for (int i = 0; i < num_sizes; ++i) {
            if (item->val.string.len == sizes[i]) {
                return true;
            }
        }
        return false;
    } else {
        return true;
    }
}

static inline bool check_item_array_count(const QCBORItem *item, int count)
{
    if (item->uDataType != QCBOR_TYPE_ARRAY || count != item->val.uCount) {
        return false;
    } else {
        return true;
    }
}

static inline bool check_item_bstring_size(const QCBORItem *item, const int *sizes, int num_sizes)
{
    return check_item_type_size(item, QCBOR_TYPE_BYTE_STRING, sizes, num_sizes);
}

static inline bool check_item_tstring_size(const QCBORItem *item, const int *sizes, int num_sizes)
{
    return check_item_type_size(item, QCBOR_TYPE_TEXT_STRING, sizes, num_sizes);
}

/*
/* Parse software component claims for platform token
*/
static uint16_t parse_claims_sw_comp(sw_comp_claims_t *claim,
                                     QCBORDecodeContext *decode_context,
                                     QCBORItem *item)
{
    uint64_t claim_cnt = 0;
    uint64_t map_item_count;

    QCBORDecode_VGetNext(decode_context, item);
    if (item->uDataType != QCBOR_TYPE_MAP) {
        printf("Attestation token error formatting: Invalid software component claim map format\n");
        return VIRTCCA_ERROR;
    }

    map_item_count = item->val.uCount;

    for (int i = 0; i < map_item_count; i++) {
        QCBORDecode_VGetNext(decode_context, item);
        if (item->uLabelType == QCBOR_TYPE_INT64) {
            claim_cnt = claim_cnt + 1;
            switch (item->label.int64) {
                case CCA_PLATFORM_SW_COMPONENT_MEASUREMENT_VALUE:
                    if (!check_item_bstring_size(item, NULL, 0)) {
                        printf("Software component measurement value is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->measurement = item->val.string;
                    break;
                
                case CCA_PLATFORM_SW_COMPONENT_SIGNER_ID:
                    if (!check_item_bstring_size(item, NULL, 0)) {
                        printf("Software component measurement signer is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->signer_id = item->val.string;
                    break;

                case CCA_PLATFORM_SW_COMPONENT_TYPE:
                    claim_cnt = claim_cnt - 1;
                    if (!check_item_tstring_size(item, NULL, 0)) {
                        printf("Software component type is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->component_type = item->val.string;
                    break;

                case CCA_PLATFORM_SW_COMPONENT_VERSION:
                    claim_cnt = claim_cnt - 1;
                    if (!check_item_tstring_size(item, NULL, 0)) {
                        printf("Software component version is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->version = item->val.string;
                    break;

                case CCA_PLATFORM_SW_COMPONENT_ALGORITHM_ID:
                    claim_cnt = claim_cnt - 1;
                    if (!check_item_tstring_size(item, NULL, 0)) {
                        printf("Software component algorithm is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->hash_algo_id = item->val.string;
                    break;
                
                default:
                    claim_cnt = claim_cnt - 1;
                    break;
            }
        } else {
            printf("Un-supported label type %d\n", item->uLabelType);
            return VIRTCCA_ERROR;
        }
    }

    if (claim_cnt != CCA_PLAT_SW_CLAIM_CNT) {
        printf("Software component number of claims is incorrect\n");
        return VIRTCCA_ERROR;
    }
    return VIRTCCA_SUCCESS;
}


static uint64_t parse_platform_claims(platform_claims_t *claim,
                                      qbuf_t *raw)
{
    QCBORItem item;
    QCBORDecodeContext decode_context;
    QCBORError ret = QCBOR_SUCCESS;
    sw_comp_claims_t *comps;
    int claim_cnt = 0;

    QCBORDecode_Init(&decode_context, *raw, QCBOR_DECODE_MODE_NORMAL);
    QCBORDecode_VGetNext(&decode_context, &item);
    if (item.uDataType != QCBOR_TYPE_MAP) {
        printf("Attestation token error formatting: Invalid platform claim map format\n");
        return VIRTCCA_ERROR;
    }

    while (ret == QCBOR_SUCCESS) {
        QCBORDecode_VGetNext(&decode_context, &item);
        ret = QCBORDecode_GetError(&decode_context);
        if (ret != QCBOR_SUCCESS) {
            break;
        }

        if (item.uLabelType == QCBOR_TYPE_INT64) {
            claim_cnt = claim_cnt + 1;
            switch (item.label.int64) {
                case CCA_PLATFORM_PROFILE:
                    if (!check_item_tstring_size(&item, NULL, 0)) {
                        printf("Platform token profile is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->profile = item.val.string;
                    break;
                    
                case CCA_PLATFORM_CHALLENGE:
                    if (!check_item_bstring_size(&item,
                        (int[]){CCA_BYTE_SIZE_32, CCA_BYTE_SIZE_48, CCA_BYTE_SIZE_64}, 3)) {
                        printf("Platform challenge is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->challenge = item.val.string;
                    break;

                case CCA_PLATFORM_IMPLEMENTATION_ID:
                    if (!check_item_bstring_size(&item, (int[]){CCA_BYTE_SIZE_32}, 1)) {
                        printf("Platform implementation id is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->implementation_id = item.val.string;
                    break;

                case CCA_PLATFORM_INSTANCE_ID:
                    if (!check_item_bstring_size(&item, (int[]){CCA_BYTE_SIZE_33}, 1)) {
                        printf("Platform instance id is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->instance_id = item.val.string;
                    break;

                case CCA_PLATFORM_CONFIG:
                    if (!check_item_bstring_size(&item, NULL, 0)) {
                        printf("Platform config is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->config = item.val.string;
                    break;

                case CCA_PLATFORM_LIFESTYLE:
                    if (item.uDataType != QCBOR_TYPE_INT64) {
                        printf("Platform lifestyle is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->lifecycle = item.val.int64;
                    break;

                case CCA_PLATFORM_SW_COMPONENTS:
                    if (item.uDataType != QCBOR_TYPE_ARRAY) {
                        printf("Software components is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->sw_comp_cnts = item.val.uCount;
                    comps = (sw_comp_claims_t *)malloc(claim->sw_comp_cnts *
                                                       sizeof(sw_comp_claims_t));
                    for (int i = 0; i < claim->sw_comp_cnts; i++) {
                        if (parse_claims_sw_comp(&comps[i], &decode_context, &item)) {
                            printf("Failed parsing software component %d\n", i);
                        }
                    }
                    claim->sw_components = comps;
                    break;

                case CCA_PLATFORM_VERIFICATION_SERVICE:
                    claim_cnt = claim_cnt - 1;
                    if (!check_item_tstring_size(&item, NULL, 0)) {
                        printf("Platform token verification-service is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->verification_service = item.val.string;
                    break;

                case CCA_PLATFORM_HASH_ALGO_ID:
                    if (!check_item_tstring_size(&item, NULL, 0)) {
                        printf("Platform token hash algo is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->hash_algo_id = item.val.string;
                    break;

                default:
                    claim_cnt = claim_cnt - 1;
                    break;
            }
        } else {
            printf("Un-supported label type %d\n", item.uLabelType);
            return VIRTCCA_ERROR;
        }
    }

    if (ret == QCBOR_ERR_NO_MORE_ITEMS) {
        if (claim_cnt != CCA_PLAT_CLAIM_CNT) {
            printf("Number of platform claims %d is incorrect\n", claim_cnt);
            return VIRTCCA_ERROR;
        } else {
            return VIRTCCA_SUCCESS;
        }
    } else {
        return VIRTCCA_ERROR;
    }
}

static uint64_t parse_cvm_claims(cvm_claims_t *claim,
                                 qbuf_t *raw)
{
    QCBORItem item;
    QCBORDecodeContext decode_context;
    QCBORError ret = QCBOR_SUCCESS;
    int claim_cnt = 0;

    QCBORDecode_Init(&decode_context, *raw, QCBOR_DECODE_MODE_NORMAL);
    QCBORDecode_EnterBstrWrapped(&decode_context, QCBOR_TAG_REQUIREMENT_NOT_A_TAG, NULL);
    QCBORDecode_VGetNext(&decode_context, &item);
    if (item.uDataType != QCBOR_TYPE_MAP) {
        printf("Attestation token error formatting: Invalid cvm claim map format\n");
        return VIRTCCA_ERROR;
    }

    while (ret == QCBOR_SUCCESS) {
        QCBORDecode_VGetNext(&decode_context, &item);
        ret = QCBORDecode_GetError(&decode_context);
        if (ret != QCBOR_SUCCESS) {
            break;
        }
    
        if (item.uLabelType == QCBOR_TYPE_INT64) {
            claim_cnt = claim_cnt + 1;
            switch (item.label.int64) {
                case CCA_CVM_CHALLENGE:
                    if (!check_item_bstring_size(&item, (int[]){CCA_BYTE_SIZE_64}, 1)) {
                        printf("cVM challenge is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->challenge = item.val.string;
                    break;

                case CCA_CVM_PERSONALIZATION_VALUE:
                    if (!check_item_bstring_size(&item, (int[]){CCA_BYTE_SIZE_64}, 1)) {
                        printf("cVM personalization value is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->rpv = item.val.string;
                    break;

                case CCA_CVM_INITIAL_MEASUREMENT:
                    if (!check_item_bstring_size(&item,
                        (int[]){CCA_BYTE_SIZE_32, CCA_BYTE_SIZE_48, CCA_BYTE_SIZE_64}, 3)) {
                        printf("cVM initial measurement is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->rim = item.val.string;
                    break;

                case CCA_CVM_EXTENSIBLE_MEASUREMENTS:
                    if (check_item_array_count(&item, CCA_CVM_EXTED_MEAS_SLOTS_NUM)) {
                        for (int i = 0; i < CCA_CVM_EXTED_MEAS_SLOTS_NUM; i++) {
                            QCBORDecode_VGetNext(&decode_context, &item);
                            if (check_item_bstring_size(&item,
                                (int[]){CCA_BYTE_SIZE_32, CCA_BYTE_SIZE_48, CCA_BYTE_SIZE_64}, 3)) {
                                claim->rem[i] = item.val.string;
                            } else {
                                printf("cVM extensible measurement is not in expected format\n");
                                return VIRTCCA_ERROR;
                            }
                        }
                    } else {
                        printf("cVM extensible measurement is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    break;

                case CCA_CVM_PUB_KEY:
                    /*
                    /* Support both RSA (550 bytes) and ECC (133 bytes) public keys for backward compatibility
                    */
                    if (!check_item_bstring_size(&item, (int[]){CCA_BYTE_SIZE_133, CCA_BYTE_SIZE_550}, 2)) {
                        printf("cVM public key is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->pub_key = item.val.string;
                    break;

                case CCA_CVM_HASH_ALGO_ID:
                    if (!check_item_tstring_size(&item, NULL, 0)) {
                        printf("cVM hash algo is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->hash_algo_id = item.val.string;
                    break;

                case CCA_CVM_PUB_KEY_HASH_ALGO_ID:
                    if (!check_item_tstring_size(&item, NULL, 0)) {
                        printf("cVM public key hash algo is not in expected format\n");
                        return VIRTCCA_ERROR;
                    }
                    claim->pub_key_hash_algo_id = item.val.string;
                    break;

                default:
                    claim_cnt = claim_cnt - 1;
                    break;
            }
        } else {
            printf("Un-supported label type %d\n", item.uLabelType);
            return VIRTCCA_ERROR;
        }
    }

    QCBORDecode_ExitBstrWrapped(&decode_context);

    if (ret == QCBOR_ERR_NO_MORE_ITEMS) {
        if (claim_cnt != CCA_CVM_CLAIM_CNT) {
            printf("Number of cVM claims %d is incorrect\n", claim_cnt);
            return VIRTCCA_ERROR;
        } else {
            return VIRTCCA_SUCCESS;
        }
    } else {
        return VIRTCCA_ERROR;
    }
}

static uint64_t parse_cose_sign1(cose_sign1_envelop_t *envelop,
                                 qbuf_t *raw)
{
    QCBORItem item;
    QCBORDecodeContext decode_context;
    QCBORError ret;

    QCBORDecode_Init(&decode_context, *raw, QCBOR_DECODE_MODE_NORMAL);
    QCBORDecode_VGetNext(&decode_context, &item);

    if (item.uDataType != QCBOR_TYPE_ARRAY || item.val.uCount != 4 ||
        QCBORDecode_GetNthTag(&decode_context, &item, 0) != CBOR_TAG_COSE_SIGN1) {
        printf("Attestation token error formatting: Cannot get COSE_SIGN1 envelop\n");
        return VIRTCCA_ERROR;
    }

    QCBORDecode_VGetNext(&decode_context, &item);
    envelop->p_headers = item.val.string;

    QCBORDecode_VGetNext(&decode_context, &item);
    envelop->np_headers = item.val.string;

    QCBORDecode_VGetNext(&decode_context, &item);
    envelop->payload = item.val.string;

    QCBORDecode_VGetNext(&decode_context, &item);
    envelop->signature = item.val.string;

    QCBORDecode_VGetNext(&decode_context, &item);
    ret = QCBORDecode_Finish(&decode_context);
    if (QCBOR_ERR_NO_MORE_ITEMS != ret) {
        printf("Unexpected return code %d\n", ret);
        return VIRTCCA_ERROR;
    }

    return VIRTCCA_SUCCESS;
}

uint64_t parse_cca_attestation_token(cca_token_t *token, uint8_t *raw_token, size_t raw_token_size)
{
    uint64_t status = VIRTCCA_SUCCESS;
    QCBORItem item;
    QCBORDecodeContext decode_context;

    qbuf_t raw_cca_token;
    qbuf_t raw_platform_envelop;
    qbuf_t raw_cvm_envelop;
    errno = EIO;
    QCBORError ret;

    /*
    /* Initialize platform token fields to NULL/0 for backward compatibility
    */
    memset(&token->platform_envelop, 0, sizeof(token->platform_envelop));
    memset(&token->platform_token, 0, sizeof(token->platform_token));
    token->platform_cose.ptr = NULL;
    token->platform_cose.len = 0;

    raw_cca_token.ptr = raw_token;
    raw_cca_token.len = raw_token_size;

    QCBORDecode_Init(&decode_context, raw_cca_token, QCBOR_DECODE_MODE_NORMAL);
    QCBORDecode_VGetNext(&decode_context, &item);
    /*
    /* Updated to support both CVM-only and CVM+Platform token formats
    */
    if (item.uDataType != QCBOR_TYPE_MAP ||
        (item.val.uCount != 1 && item.val.uCount != 2) ||
        QCBORDecode_GetNthTag(&decode_context, &item, 0) != TAG_CCA_TOKEN) {
        printf("Attestation token error formatting: This may not be CCA token\n");
        return VIRTCCA_ERROR;
    }

    /*
    /* First try to parse platform token if present
    */
    QCBORDecode_VGetNext(&decode_context, &item);
    if (item.uDataType == QCBOR_TYPE_BYTE_STRING &&
        item.label.int64 == CCA_PLAT_TOKEN) {
        raw_platform_envelop = item.val.string;
        token->platform_cose = raw_platform_envelop;
        status = parse_cose_sign1(&token->platform_envelop,
                                  &raw_platform_envelop);
        if (status != VIRTCCA_SUCCESS) {
            printf("Failed to decode platform COSE_Sign1 envelop\n");
            return status;
        }

        status = parse_platform_claims(&token->platform_token, &token->platform_envelop.payload);
        if (status != VIRTCCA_SUCCESS) {
            printf("Failed to parse platform claim map\n");
            return status;
        }
        
        QCBORDecode_VGetNext(&decode_context, &item);
    }

    /*
    /* Parse CVM token
    */
    if (item.uDataType != QCBOR_TYPE_BYTE_STRING || 
        item.label.int64 != CCA_CVM_TOKEN) {
        printf("Attestation token error formatting: Cannot get CVM token\n");
        return VIRTCCA_ERROR;
    }

    raw_cvm_envelop = item.val.string;
    token->cvm_cose = raw_cvm_envelop;
    status = parse_cose_sign1(&token->cvm_envelop,
                              &raw_cvm_envelop);
    if (status != VIRTCCA_SUCCESS) {
        printf("Failed to decode cvm COSE_Sign1 envelop\n");
        return status;
    }

    status = parse_cvm_claims(&token->cvm_token, &token->cvm_envelop.payload);
    if (status != VIRTCCA_SUCCESS) {
        printf("Failed to parse cvm claim map\n");
        return status;
    }

    QCBORDecode_VGetNext(&decode_context, &item);
    ret =  QCBORDecode_Finish(&decode_context);
    if (QCBOR_ERR_NO_MORE_ITEMS != ret) {
        printf("Unexpected return code %d\n", ret);
        return ret;
    }

    return VIRTCCA_SUCCESS;
}

void print_cca_attestation_token_raw(const cca_token_t *token)
{
    const uint8_t *_p;
    int _l;
    printf("CCA attestation token\n");
    printf("CVM token\n");

    printf("\tProtected headers: ");
    _p = token->cvm_envelop.p_headers.ptr;
    _l = token->cvm_envelop.p_headers.len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tUn-Protected headers: ");
    _p = token->cvm_envelop.np_headers.ptr;
    _l = token->cvm_envelop.np_headers.len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tPayload: ");
    _p = token->cvm_envelop.payload.ptr;
    _l = token->cvm_envelop.payload.len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tSignature: ");
    _p = token->cvm_envelop.signature.ptr;
    _l = token->cvm_envelop.signature.len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n\n");

    /*
    /* Print platform token if present
    */
    if (token->platform_cose.ptr != NULL && token->platform_cose.len > 0) {
        printf("Platform token\n");

        printf("\tProtected headers: ");
        _p = token->platform_envelop.p_headers.ptr;
        _l = token->platform_envelop.p_headers.len;
        for (unsigned int i = 0U; i < _l; ++i) {
            printf("%02x", _p[i]);
        }
        printf("\n");
        
        printf("\tUn-Protected headers: ");
        _p = token->platform_envelop.np_headers.ptr;
        _l = token->platform_envelop.np_headers.len;
        for (unsigned int i = 0U; i < _l; ++i) {
            printf("%02x", _p[i]);
        }
        printf("\n");

        printf("\tPayload: ");
        _p = token->platform_envelop.payload.ptr;
        _l = token->platform_envelop.payload.len;
        for (unsigned int i = 0U; i < _l; ++i) {
            printf("%02x", _p[i]);
        }
        printf("\n");

        printf("\tSignature: ");
        _p = token->platform_envelop.signature.ptr;
        _l = token->platform_envelop.signature.len;
        for (unsigned int i = 0U; i < _l; ++i) {
            printf("%02x", _p[i]);
        }
        printf("\n\n");
    }
}

void print_cca_attestation_token(const cca_token_t *token)
{
    const uint8_t *_p;
    int _l;

    printf("Parsed CCA attestation token\n");
    printf("CVM token\n");

    printf("\tChallenge: ");
    _p = token->cvm_token.challenge.ptr;
    _l = token->cvm_token.challenge.len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tRPV: ");
    _p = token->cvm_token.rpv.ptr;
    _l = token->cvm_token.rpv.len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tRIM: ");
    _p = token->cvm_token.rim.ptr;
    _l = token->cvm_token.rim.len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tREM[0]: ");
    _p = token->cvm_token.rem[0].ptr;
    _l = token->cvm_token.rem[0].len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tREM[1]: ");
    _p = token->cvm_token.rem[1].ptr;
    _l = token->cvm_token.rem[1].len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tREM[2]: ");
    _p = token->cvm_token.rem[2].ptr;
    _l = token->cvm_token.rem[2].len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tREM[3]: ");
    _p = token->cvm_token.rem[3].ptr;
    _l = token->cvm_token.rem[3].len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tHash Algo ID: ");
    _p = token->cvm_token.hash_algo_id.ptr;
    _l = token->cvm_token.hash_algo_id.len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%c", _p[i]);
    }
    printf("\n");

    printf("\tPublic Key: ");
    _p = token->cvm_token.pub_key.ptr;
    _l = token->cvm_token.pub_key.len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%02x", _p[i]);
    }
    printf("\n");

    printf("\tPublic Key Hash Algo ID: ");
    _p = token->cvm_token.pub_key_hash_algo_id.ptr;
    _l = token->cvm_token.pub_key_hash_algo_id.len;
    for (unsigned int i = 0U; i < _l; ++i) {
        printf("%c", _p[i]);
    }
    printf("\n");

    /*
    /* Print platform token details if present
    */
    if (token->platform_cose.ptr != NULL && token->platform_cose.len > 0) {
        printf("\nPlatform token\n");
        printf("\tProfile: ");
        _p = token->platform_token.profile.ptr;
        _l = token->platform_token.profile.len;
        for (unsigned int i = 0U; i < _l; ++i) {
            printf("%c", _p[i]);
        }
        printf("\n");

        printf("\tChallenge: ");
        _p = token->platform_token.challenge.ptr;
        _l = token->platform_token.challenge.len;
        for (unsigned int i = 0U; i < _l; ++i) {
            printf("%02x", _p[i]);
        }
        printf("\n");

        printf("\tImplementation ID: ");
        _p = token->platform_token.implementation_id.ptr;
        _l = token->platform_token.implementation_id.len;
        for (unsigned int i = 0U; i < _l; ++i) {
            printf("%02x", _p[i]);
        }
        printf("\n");

        printf("\tInstance ID: ");
        _p = token->platform_token.instance_id.ptr;
        _l = token->platform_token.instance_id.len;
        for (unsigned int i = 0U; i < _l; ++i) {
            printf("%02x", _p[i]);
        }
        printf("\n");

        printf("\tConfig: ");
        _p = token->platform_token.config.ptr;
        _l = token->platform_token.config.len;
        for (unsigned int i = 0U; i < _l; ++i) {
            printf("%02x", _p[i]);
        }
        printf("\n");

        printf("\tLifecycle: %ld\n", token->platform_token.lifecycle);

        printf("\tSoftware Components (%ld):\n", token->platform_token.sw_comp_cnts);
        for (int i = 0; i < token->platform_token.sw_comp_cnts; i++) {
            printf("\t\tIndex %d:\n", i);

            printf("\t\tComponent Type: ");
            _p = token->platform_token.sw_components[i].component_type.ptr;
            _l = token->platform_token.sw_components[i].component_type.len;
            if (_p != NULL && _l > 0) {
                for (unsigned int j = 0U; j < _l; ++j) {
                    printf("%c", _p[j]);
                }
            } else {
                printf("(not present)");
            }
            printf("\n");

            printf("\t\tMeasurement: ");
            _p = token->platform_token.sw_components[i].measurement.ptr;
            _l = token->platform_token.sw_components[i].measurement.len;
            for (unsigned int j = 0U; j < _l; ++j) {
                printf("%02x", _p[j]);
            }
            printf("\n");

            printf("\t\tVersion: ");
            _p = token->platform_token.sw_components[i].version.ptr;
            _l = token->platform_token.sw_components[i].version.len;
            if (_p != NULL && _l > 0) {
                for (unsigned int j = 0U; j < _l; ++j) {
                    printf("%c", _p[j]);
                }
            } else {
                printf("(not present)");
            }
            printf("\n");

            printf("\t\tSigner ID: ");
            _p = token->platform_token.sw_components[i].signer_id.ptr;
            _l = token->platform_token.sw_components[i].signer_id.len;
            for (unsigned int j = 0U; j < _l; ++j) {
                printf("%02x", _p[j]);
            }
            printf("\n");

            printf("\t\tHash Algo ID: ");
            _p = token->platform_token.sw_components[i].hash_algo_id.ptr;
            _l = token->platform_token.sw_components[i].hash_algo_id.len;
            if (_p != NULL && _l > 0) {
                for (unsigned int j = 0U; j < _l; ++j) {
                    printf("%c", _p[j]);
                }
            } else {
                printf("(not present)");
            }
            printf("\n");
        }

        printf("\tVerification Service: ");
        _p = token->platform_token.verification_service.ptr;
        _l = token->platform_token.verification_service.len;
        if (_p != NULL && _l > 0) {
            for (unsigned int i = 0U; i < _l; ++i) {
                printf("%c", _p[i]);
            }
        } else {
            printf("(not present)");
        }
        printf("\n");

        printf("\tHash Algo ID: ");
        _p = token->platform_token.hash_algo_id.ptr;
        _l = token->platform_token.hash_algo_id.len;
        for (unsigned int i = 0U; i < _l; ++i) {
            printf("%c", _p[i]);
        }
        printf("\n");
    }
}
