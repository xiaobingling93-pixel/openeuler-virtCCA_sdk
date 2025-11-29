/* Copyright (c) 2021 Intel Corporation
 * Copyright (c) 2020-2021 Alibaba Cloud
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/* server */
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <errno.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <sys/stat.h>
#include "utils.h"

/* client */
#include <termios.h>
#include <ctype.h>
#include <internal/core.h>

#include "token_parse.h"
#include "token_validate.h"
#include "platform_verify.h"
#include "ima_measure.h"

#include "token_parse.h"
#include "token_validate.h"
#include "event_log.h"
#include "firmware_state.h"
#include "binary_blob.h"
#include "verify.h"
#include "config.h"
#include "rats-tls/log.h"

#include "socket_agent.h"
#include "migcvm_tsi.h"
#include "rats_tls_handler.h"

#define    MIG_TYPE_SERVER 1
#define    MIG_TYPE_CLIENT 2
#define    MIG_MSK_ACK "MSK_ACK"
#define    MIG_MSK_SEND "MSK_SEND"

static int start_listening = 1;

static rats_tls_err_t read_ima_measurements(uint8_t **value, size_t *size)
{
    FILE *file;
    uint8_t buffer[IMA_READ_BLCOK_SIZE];
    size_t byte_read;
    rats_tls_err_t ret = RATS_TLS_ERR_NO_MEM;

    file = fopen(SERVER_IMA_MEASUREMENTS_PATH, "rb");
    if (file == NULL) {
        RTLS_ERR("Error opening file: %s\n", strerror(errno));
        return RATS_TLS_ERR_INVALID;
    }
    RTLS_INFO("file opened: %s\n", SERVER_IMA_MEASUREMENTS_PATH);

    while ((byte_read = fread(buffer, 1, IMA_READ_BLCOK_SIZE, file)) > 0) {
        uint8_t *content = realloc(*value, *size + byte_read);
        if (content == NULL) {
            free(*value);
            RTLS_ERR("memory reallocation failed");
            goto close;
        }

        *value = content;
        memcpy(*value + *size, buffer, byte_read);
        *size += byte_read;
    }
    ret = RATS_TLS_ERR_NONE;

close:
    fclose(file);
    return ret;
}

static int send_ima_log(rats_tls_handle handle)
{
    uint8_t *ima_meas_buf = NULL;
    size_t ima_size = 0;
    size_t send_size = 0;
    size_t len = sizeof(size_t);
    int ret = ENCLAVE_ATTESTER_ERR_UNKNOWN;

    ret = read_ima_measurements(&ima_meas_buf, &ima_size);
    if (ret == 0 && ima_size != 0) {
        RTLS_INFO("Read %zu bytes from binary_runtime_measurements\n", ima_size);
    } else {
        RTLS_ERR("Failed to read binary_runtime_measurements\n");
        return ret;
    }

    ret = rats_tls_transmit(handle, &ima_size, &len);
    if (ret != RATS_TLS_ERR_NONE || len != sizeof(size_t)) {
        RTLS_ERR("Failed to send IMA log size %#x\n", ret);
        ret = RATS_TLS_ERR_LOAD_TLS_WRAPPERS;
        goto free;
    }

    while (send_size < ima_size) {
        len = ima_size - send_size;
        ret = rats_tls_transmit(handle, ima_meas_buf + send_size, &len);
        if (ret != RATS_TLS_ERR_NONE) {
            RTLS_ERR("Failed to send IMA log data %#x\n", ret);
            goto free;
        }
        send_size += len;
    }

free:
    free(ima_meas_buf);
    return ret;
}

static int deal_rootfs_key(rats_tls_handle handle)
{
    uint8_t key_file[MAX] = {};
    size_t len = sizeof(key_file);
    int ret = ENCLAVE_ATTESTER_ERR_UNKNOWN;

    ret = rats_tls_receive(handle, key_file, &len);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to receive %#x\n", ret);
        return ret;
    }

    ret = save_file_data(KEY_FILE_PATH, key_file, len) ? 0 : 1;
    if (ret != 0) {
        RTLS_ERR("Failed to save key file data.\n");
        return ret;
    }

    return RATS_TLS_ERR_NONE;
}

static int send_ccel_data(rats_tls_handle handle)
{
    size_t ccel_size = 0;
    uint8_t *ccel_data = NULL;
    int ret = ENCLAVE_ATTESTER_ERR_UNKNOWN;

    ccel_data = read_file_data(SERVER_CCEL_ACPI_TABLE_PATH, &ccel_size);
    if (!ccel_data) {
        RTLS_ERR("Failed to read CCEL ACPI table data\n");
        return ret;
    }

    size_t len = ccel_size;
    ret = rats_tls_transmit(handle, ccel_data, &len);
    if (ret != RATS_TLS_ERR_NONE || len != ccel_size) {
        RTLS_ERR("Failed to send CCEL ACPI table data %#x\n", ret);
        ret = RATS_TLS_ERR_LOAD_TLS_WRAPPERS;
        goto free;
    }

    RTLS_INFO("Successfully sent CCEL ACPI table (%zu bytes)\n", ccel_size);

free:
    free(ccel_data);
    return ret;
}

static int send_event_log(rats_tls_handle handle)
{
    size_t event_log_size = 0;
    uint8_t *event_log = NULL;
    int ret = ENCLAVE_ATTESTER_ERR_UNKNOWN;

    event_log = read_file_data(SERVER_CCEL_EVENT_LOG_PATH, &event_log_size);
    if (!event_log) {
        RTLS_ERR("Failed to read event log data\n");
        return ret;
    }

    /* First send the event log size */
    size_t len = sizeof(size_t);
    ret = rats_tls_transmit(handle, &event_log_size, &len);
    if (ret != RATS_TLS_ERR_NONE || len != sizeof(size_t)) {
        RTLS_ERR("Failed to send event log size %#x\n", ret);
        ret = RATS_TLS_ERR_LOAD_TLS_WRAPPERS;
        goto free;
    }

    /* Then send the event log data */
    size_t send_size = 0;
    while (send_size < event_log_size) {
        len = event_log_size - send_size;
        ret = rats_tls_transmit(handle, event_log + send_size, &len);
        if (ret != RATS_TLS_ERR_NONE) {
            RTLS_ERR("Failed to send event log data at offset %zu %#x\n", send_size, ret);
            goto free;
        }
        send_size += len;
        RTLS_INFO("Sent %zu of %zu bytes\n", send_size, event_log_size);
    }

    RTLS_INFO("Successfully sent complete event log (%zu bytes)\n", event_log_size);

free:
    free(event_log);
    return ret;
}

static int recieve_and_save_msk(rats_tls_handle handle, mig_agent_args *args)
{
    int ret = ENCLAVE_ATTESTER_ERR_UNKNOWN;
    unsigned long long migrate_key_package[10];
    size_t len = sizeof(migrate_key_package);

    /* tsi context */
    virtcca_mig_info_t *migvm_info = NULL;
    migration_info_t *attest_info = NULL;

    tsi_ctx *virtcca_server_ctx = tsi_new_ctx();
    if (!virtcca_server_ctx) {
        goto out;
    }

    RTLS_INFO("[SERVER] calling recieve_and_save_msk\n");
    ret = rats_tls_receive(handle, migrate_key_package, &len);
    if (ret != RATS_TLS_ERR_NONE || len != sizeof(migrate_key_package)) {
        RTLS_ERR("[SERVER] Failed to receive valid MSK and RAND iv\n");
        ret = RATS_TLS_ERR_UNKNOWN;
        goto out;
    }

    migvm_info = (virtcca_mig_info_t *)malloc(sizeof(virtcca_mig_info_t));
    if (!migvm_info) {
        printf("[SERVER] Failed to initialize migvm_info\n");
        ret = RATS_TLS_ERR_UNKNOWN;
        goto out;
    }
    migvm_info->guest_rd = args->guest_rd;
    attest_info = (migration_info_t *)malloc(sizeof(migration_info_t));
    if (!attest_info) {
        printf("[SERVER] Failed to initialize attest_info\n");
        ret = RATS_TLS_ERR_UNKNOWN;
        goto out;
    };
    attest_info->pending_guest_rds = NULL;
    memcpy(attest_info->msk, migrate_key_package, sizeof(attest_info->msk));
    memcpy(attest_info->rand_iv, migrate_key_package + 4, sizeof(attest_info->rand_iv));
    memcpy(attest_info->tag, migrate_key_package + 8, sizeof(attest_info->tag));
    attest_info->slot_status = SLOT_IS_READY;

    /* Set migration bind slot and mask : SLOT_IS_READY*/
    ret = set_migration_bind_slot_and_mask(virtcca_server_ctx, migvm_info, attest_info);
    if (ret == 0) {
        printf("[SERVER] set_migration_bind_slot_and_mask succeeded\n");
    } else {
        printf("[SERVER] set_migration_bind_slot_and_mask failed with error: 0x%08x\n", ret);
        goto out;
    }

    ret = RATS_TLS_ERR_NONE;
out:
    args->guest_rd = 0;
    memset(args->msk, 0, sizeof(args->msk));
    memset(args->tag, 0, sizeof(args->tag));
    memset(args->rand_iv, 0, sizeof(args->rand_iv));
    if (virtcca_server_ctx) {
        tsi_free_ctx(virtcca_server_ctx);
    }
    if (attest_info) {
        free(attest_info);
    }
    if (migvm_info) {
        free(migvm_info);
    }
    return ret;
}

static int deal_client_req(rats_tls_handle handle, mig_agent_args *args)
{
    int ret = ENCLAVE_ATTESTER_ERR_UNKNOWN;
    char buf[256] = {0};
    size_t len = sizeof(buf);
    if (args == NULL) {
        RTLS_ERR("Invalid arguments\n");
        return RATS_TLS_ERR_INVALID;
    }
    ret = rats_tls_receive(handle, buf, &len);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to receive %#x\n", ret);
        return ret;
    }

    if (len >= sizeof(buf)) {
        len = sizeof(buf) - 1;
    }
    buf[len] = '\0';

    RTLS_INFO("Received from Client: %s\n", buf);

    /* Process CCEL table request */
    if (strncmp(buf, "REQUEST_CCEL_TABLE", strlen("REQUEST_CCEL_TABLE")) == 0) {
        ret = send_ccel_data(handle);
        if (ret) {
            RTLS_ERR("Send CCEL ACPI table failed %#x\n", ret);
            return ret;
        }
        RTLS_INFO("Send CCEL ACPI table success\n");
        return deal_client_req(handle, args);
    }

    /* Process event log request */
    if (strncmp(buf, "REQUEST_EVENT_LOG", strlen("REQUEST_EVENT_LOG")) == 0) {
        ret = send_event_log(handle);
        if (ret) {
            RTLS_ERR("Send event log failed %#x\n", ret);
            return ret;
        }
        RTLS_INFO("Send event log success\n");
        return deal_client_req(handle, args);
    }

    /* Process TOKEN */
    if (strncmp(buf, TOKEN, strlen(TOKEN)) == 0) {
        strcpy(buf, "Attestation Passed, Swtiching Root.....");
        len = sizeof(buf);
        ret = rats_tls_transmit(handle, buf, &len);
        if (ret != RATS_TLS_ERR_NONE) {
            RTLS_ERR("Failed to transmit %#x\n", ret);
            return ret;
        }
        return RATS_TLS_ERR_NONE;  /* Return success directly */
    }

    if (strncmp(buf, REQUEST_IMA_LOG, strlen(REQUEST_IMA_LOG)) == 0) {
        ret = send_ima_log(handle);
        if (ret) {
            RTLS_ERR("Send IMA log failed %#x\n", ret);
        } else {
            RTLS_INFO("Send IMA log success\n");
            /* expect receive the PASS TOKEN */
            ret = deal_client_req(handle, args);
        }
        return ret;
    }

    if (strncmp(buf, ENABLE_FDE_TOKEN, strlen(ENABLE_FDE_TOKEN)) == 0) {
        ret = deal_rootfs_key(handle);
        if (ret) {
            RTLS_ERR("Save rootfs key failed %#x\n", ret);
        } else {
            RTLS_INFO("Save rootfs key success\n");
            /* expect receive the PASS TOKEN */
            if ((ret = deal_client_req(handle, args))) {
                RTLS_ERR("recevice PASS ACK failed %#x\n", ret);
                return ret;
            }
            ret = 0x68; /* Return specific value for LUKS completion */
        }
        return ret;
    }

    /* Process MIG_MSK_SEND */
    if (strncmp(buf, MIG_MSK_SEND, strlen(MIG_MSK_SEND)) == 0) {
        strcpy(buf, MIG_MSK_ACK);
        len = sizeof(buf);
        ret = rats_tls_transmit(handle, buf, &len);
        if (ret != RATS_TLS_ERR_NONE) {
            RTLS_ERR("Failed to transmit %#x\n", ret);
            return ret;
        }
        return recieve_and_save_msk(handle, args);  /* Return success directly */
    }

    strcpy(buf, "Attestation Failed, Continue.....");
    /* Reply back to the client */
    len = sizeof(buf);
    ret = rats_tls_transmit(handle, buf, &len);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to transmit %#x\n", ret);
    }
    ret = ENCLAVE_ATTESTER_ERR_UNKNOWN;

    return ret;
}

/* client */
static void display_hash_as_hex_string(const uint8_t *hash, size_t hash_len, const char *label)
{
    if (label) {
        RTLS_INFO("%s: ", label);
    }
    for (size_t i = 0; i < hash_len; ++i) {
        printf("%02x", hash[i]);
    }
    printf("\n");
}

static bool is_rem_entry_zero(const qbuf_t *rem_entry)
{
    if (!rem_entry || rem_entry->ptr == NULL || rem_entry->len == 0) {
        return true;
    }
    for (size_t i = 0; i < rem_entry->len; ++i) {
        if (((const uint8_t *)rem_entry->ptr)[i] != 0) {
            return false;
        }
    }
    return true;
}

#define CHECK_LENGHT_ASSIGN(src, max_len, dst) \
do { \
    if (strnlen(src, max_len) == max_len) { \
        printf("input param len too long.\n"); \
        return -1; \
    } \
    dst = src; \
} while (0)

/* Forward declarations */
static char* extract_json_string(const char* json, const char* key);
static int request_and_save_firmware_data(rats_tls_handle handle);
static int handle_eventlogs_command(void);

static int user_callback(void *args)
{
    if (!args) {
        RTLS_ERR("the agent arg is NULL\n");
        return ENCLAVE_VERIFIER_ERR_INVALID;
    }
    rtls_evidence_t *ev = (rtls_evidence_t *)args;
    bool ret = true;
    FILE *fp;
    size_t byte_write;
    int validate = 1;
    int verify = 1;
    rtls_core_context_t *ctx = (rtls_core_context_t *)ev;
    mig_agent_args *client_config = NULL;
    rats_tls_handle handle = ctx;

    RTLS_INFO("Entering user_callback function\n");
    
    /* Try to get client_config from core context */
    if (ctx && ctx->config.custom_claims && ctx->config.custom_claims->value) {
        client_config = (mig_agent_args *)ctx->config.custom_claims->value;
        RTLS_DEBUG("Got client_config from ctx->config\n");
    }

    RTLS_INFO("Context check: ctx=%p, client_config=%p\n", ctx, client_config);
    
    /* Step 1: Parse and verify token regardless of client_config */
    RTLS_DEBUG("Starting token verification\n");
    cca_token_t token = {0};
    cca_token_buf_t cca_token_buf = {0};

    if (ev->cca.evidence_sz > MAX_TOKEN_SIZE) {
        RTLS_ERR("token length is invalid\n");
        return ENCLAVE_VERIFIER_ERR_CBOR;
    }
    memcpy(&cca_token_buf, ev->cca.evidence, ev->cca.evidence_sz);
    
    ret = parse_cca_attestation_token(&token, cca_token_buf.buf, cca_token_buf.buf_size);
    if (ret != VIRTCCA_SUCCESS) {
        RTLS_ERR("failed to parse virtcca token\n");
        return ENCLAVE_VERIFIER_ERR_CBOR;
    }
    RTLS_DEBUG("Token parsed successfully\n");

    cert_info_t cert_info;
    /* Detect AIK certificate type and configure certificate chain accordingly */
    cert_type_t aik_cert_type = detect_aik_cert_type(DEFAULT_AIK_CERT_PEM_FILENAME);
    configure_cert_info_by_type(&cert_info, aik_cert_type);

    /*
     * Determine if we have platform token or CVM-only token
     * If we have platform token, use proper platform verification
     * Otherwise, use empty placeholders for backward compatibility
     */
    qbuf_t platform_cose = {.ptr = NULL, .len = 0};
    qbuf_t platform_challenge = {.ptr = NULL, .len = 0};
    
    /* Check if platform token exists */
    bool has_platform = (token.platform_cose.len > 0);
    if (has_platform) {
        platform_cose = token.platform_cose;
        platform_challenge = token.platform_token.challenge;
        RTLS_INFO("Platform token detected, enabling full platform verification\n");
    } else {
        RTLS_INFO("CVM-only token detected, using backward compatibility mode\n");
    }
    
    ret = verify_cca_token_signatures(&cert_info,
                                      platform_cose,
                                      token.cvm_cose,
                                      token.cvm_token.pub_key,
                                      platform_challenge,
                                      token.cvm_token.pub_key_hash_algo_id);
    if (!ret) {
        RTLS_ERR("Token signature verification failed");
        return false;
    }
    RTLS_DEBUG("Token signatures verified successfully");

    /* Step 2: Verify RIM */
    if (token.cvm_token.rim.len != g_rim_ref_size ||
        memcmp(g_rim_ref, token.cvm_token.rim.ptr, token.cvm_token.rim.len)) {
        RTLS_ERR("RIM verification failed\n");
        printf("Verifying if RIM of cVM token matches reference value: Failed\n");
        return false;
    }
    RTLS_INFO("RIM verification passed\n");

    /* Step 3: Platform SW Components Verification */
    /* Note: Platform verification is now handled in verify_evidence.c */
    if (has_platform && client_config && client_config->verify_platform_components) {
        RTLS_INFO("Platform SW components verification will be handled by verifier");
    } else if (client_config && client_config->verify_platform_components) {
        RTLS_WARN("Platform verification requested but no platform token present in attestation");
    }

    RTLS_DEBUG("All verifications completed successfully\n");
    return true;
}

/*
 * Parse IMA measurement file to determine the actual PCR index being used
 * Returns the PCR index found in the file, or -1 on error
 */
static int parse_ima_pcr_index(void)
{
    FILE *fp;
    int pcr_index = -1;
    
    /*
    * IMA measurements file is in binary format, not text format
    * Each entry has a header structure containing PCR index
    */
    struct {
        u_int32_t pcr;
        u_int8_t digest[20];  /* SHA1_DIGEST_LENGTH */
        u_int32_t name_len;
    } header;

    fp = fopen(CLIENT_IMA_MEASUREMENTS_PATH, "rb");  /* Open in binary mode */
    if (!fp) {
        RTLS_ERR("Unable to open IMA measurements file: %s\n", CLIENT_IMA_MEASUREMENTS_PATH);
        return -1;
    }
    
    /* Skip the first entry (boot_aggregate) and read the second entry */
    /* which contains the actual PCR index used for file measurements */
    for (int entry_count = 0; entry_count < 2; entry_count++) {
        if (fread(&header, sizeof(header), 1, fp) != 1) {
            RTLS_ERR("Failed to read IMA measurement header for entry %d\n", entry_count);
            fclose(fp);
            return -1;
        }
        
        if (entry_count == 0) {
            /* This is boot_aggregate entry, skip it */
            RTLS_DEBUG("Skipping boot_aggregate entry with PCR %d\n", header.pcr);
            
            /* Skip template name */
            if (header.name_len > 0 && header.name_len < 1024) {
                fseek(fp, header.name_len, SEEK_CUR);
            }
            
            /* Skip template data for boot_aggregate */
            /* For ima-ng template: skip template_data_len + template_data */
            u_int32_t template_data_len;
            if (fread(&template_data_len, sizeof(u_int32_t), 1, fp) == 1 && template_data_len < 10240) {
                fseek(fp, template_data_len, SEEK_CUR);
            }
        } else {
            /* This is the actual file measurement entry */
            pcr_index = header.pcr;
            RTLS_INFO("Found actual measurement PCR index %d from IMA measurements file (skipped boot_aggregate)\n", pcr_index);
            break;
        }
    }
    
    fclose(fp);
    
    if (pcr_index == -1) {
        RTLS_ERR("Could not determine PCR index from IMA measurements\n");
        return -1;
    }
    
    return pcr_index;
}

static int verify_ima_log(rats_tls_handle handle, mig_agent_args *args)
{
    size_t len = sizeof(size_t);
    size_t ima_log_size = 0;
    uint8_t *ima_log_buf = NULL;
    size_t recv_size = 0;
    FILE *fp = NULL;
    int ret = ENCLAVE_VERIFIER_ERR_UNKNOWN;
    cca_token_t token = {0};
    cca_token_buf_t *cca_token_buf_ptr = NULL;
    int target_pcr_for_ima = -1;  /* Will be set to 1 or 4 */
    int rem_index_for_ima = -1; /* Will be set to 0 or 3 */
    const uint8_t *reference_rem_ptr = NULL;
    size_t reference_rem_len = 0;

    RTLS_INFO("Starting automatic IMA measurement verification...");

    ret = rats_tls_receive(handle, &ima_log_size, &len);
    if (ret != RATS_TLS_ERR_NONE || len != sizeof(size_t)) {
        RTLS_INFO("Failed to receive IMA log size %#x\n", ret);
        return RATS_TLS_ERR_LOAD_TLS_WRAPPERS;
    }
    if (ima_log_size == 0 || ima_log_size > MAX_IMA_LOG_SIZE) {
        RTLS_INFO("IMA log size is invalid, %u\n", ima_log_size);
        return RATS_TLS_ERR_LOAD_ENCLAVE_ATTESTERS;
    }

    ima_log_buf = malloc(ima_log_size);
    if (ima_log_buf == NULL) {
        RTLS_INFO("Malloc IMA log buffer failed.\n");
        return ENCLAVE_VERIFIER_ERR_NO_MEM;
    }

    while (recv_size < ima_log_size) {
        len = ima_log_size - recv_size;
        ret = rats_tls_receive(handle, ima_log_buf + recv_size, &len);
        if (ret != RATS_TLS_ERR_NONE) {
            RTLS_INFO("Filed to receive IMA log data.\n");
            goto free;
        }
        recv_size += len;
    }

    /* write IMA log to file for next verify */
    if ((fp = fopen(CLIENT_IMA_MEASUREMENTS_PATH, "w")) == NULL) {
        RTLS_INFO("Filed to open file %s.\n", CLIENT_IMA_MEASUREMENTS_PATH);
        ret = ENCLAVE_VERIFIER_ERR_UNKNOWN;
        goto free;
    }
    if ((len = fwrite(ima_log_buf, ima_log_size, 1, fp)) != 1) {
        RTLS_INFO("Filed to write IMA log to file.\n");
        ret = ENCLAVE_VERIFIER_ERR_UNKNOWN;
    }

close:
    fclose(fp);
free:
    free(ima_log_buf);
    if (ret) {
        return ret;
    }

    rtls_core_context_t *ctx = (rtls_core_context_t *)handle;

    if (!ctx || !ctx->verifier || !ctx->verifier->verifier_private) {
        RTLS_ERR("Verifier context or private data not found, cannot get CVM token for IMA validation.\n");
        return RATS_TLS_ERR_INVALID;
    }
    cca_token_buf_ptr = (cca_token_buf_t *)ctx->verifier->verifier_private;

    if (parse_cca_attestation_token(&token, cca_token_buf_ptr->buf, cca_token_buf_ptr->buf_size) != VIRTCCA_SUCCESS) {
        RTLS_ERR("Failed to parse virtcca token from verifier context for IMA validation.\n");
        return ENCLAVE_VERIFIER_ERR_CBOR;
    }

    /*
     * Parse IMA measurement file to determine the actual PCR index being used
     * Based on the PCR index, determine which REM to use:
     * - PCR 4: use REM[3] (UEFI boot mode)
     * - PCR 1 or 10: use REM[0] (Direct boot mode)
     */
    RTLS_INFO("Attempting to parse PCR index from IMA measurements file...\n");
    int actual_pcr_index = parse_ima_pcr_index();
    if (actual_pcr_index == -1) {
        RTLS_ERR("Failed to parse PCR index from IMA measurements\n");
        return RATS_TLS_ERR_INVALID;
    }
    RTLS_INFO("Successfully parsed PCR index: %d\n", actual_pcr_index);

    if (actual_pcr_index == 4) {
        /* UEFI boot mode: PCR 4 -> REM[3] */
        if (REM_COUNT <= 3 || token.cvm_token.rem[3].len != SHA256_SIZE || is_rem_entry_zero(&token.cvm_token.rem[3])) {
            RTLS_ERR("REM[3] is invalid or zero for PCR 4 verification\n");
            return RATS_TLS_ERR_INVALID;
        }
        target_pcr_for_ima = 4;
        rem_index_for_ima = 3;
        reference_rem_ptr = (const uint8_t *)token.cvm_token.rem[3].ptr;
        reference_rem_len = token.cvm_token.rem[3].len;
        RTLS_INFO("UEFI boot mode detected: using REM[3] for PCR 4 verification\n");
    } else if (actual_pcr_index == 1 || actual_pcr_index == 10) {
        /* Direct boot mode: PCR 1 or 10 -> REM[0] */
        if (REM_COUNT <= 0 || token.cvm_token.rem[0].len != SHA256_SIZE || is_rem_entry_zero(&token.cvm_token.rem[0])) {
            RTLS_ERR("REM[0] is invalid or zero for PCR %d verification\n", actual_pcr_index);
            return RATS_TLS_ERR_INVALID;
        }
        target_pcr_for_ima = actual_pcr_index;  /* Use the actual PCR index detected */
        rem_index_for_ima = 0;
        reference_rem_ptr = (const uint8_t *)token.cvm_token.rem[0].ptr;
        reference_rem_len = token.cvm_token.rem[0].len;
        RTLS_INFO("Direct boot mode detected: using REM[0] for PCR %d verification\n", actual_pcr_index);
    } else {
        RTLS_ERR("Unsupported PCR index %d found in IMA measurements\n", actual_pcr_index);
        return RATS_TLS_ERR_INVALID;
    }

    RTLS_INFO("Using REM[%d] (PCR%d) from CVM token for IMA validation.\n", rem_index_for_ima, target_pcr_for_ima);
    display_hash_as_hex_string(reference_rem_ptr, reference_rem_len, "REM_FOR_IMA");

    ret = ima_measure(reference_rem_ptr,
                      reference_rem_len,
                      args->digest_file, 1, 1, target_pcr_for_ima);
    if (ret != 0) {
        RTLS_ERR("IMA measurement verification failed for PCR%d. ima_measure returned: %d\n", target_pcr_for_ima, ret);
        return ENCLAVE_VERIFIER_ERR_UNKNOWN;
    }

    RTLS_INFO("IMA measurement verification successful for PCR%d.\n", target_pcr_for_ima);
    return RATS_TLS_ERR_NONE;
}

static int deal_ima(rats_tls_handle handle, mig_agent_args *args)
{
    int ret = ENCLAVE_VERIFIER_ERR_UNKNOWN;

    RTLS_DEBUG("IMA file hash path %s\n", args->digest_file);
    if (args->digest_file == NULL || strlen(args->digest_file) == 0) {
        RTLS_INFO("No need to request and verify IMA log.\n");
        return RATS_TLS_ERR_BASE;
    }
    const char *msg = REQUEST_IMA_LOG;
    size_t len = strlen(msg);
    ret = rats_tls_transmit(handle, (void *)msg, &len);
    if (ret != RATS_TLS_ERR_NONE || len != strlen(msg)) {
        RTLS_ERR("Failed to request IMA log %#x\n", ret);
        return RATS_TLS_ERR_LOAD_TLS_WRAPPERS;
    }

    ret = verify_ima_log(handle, args);
    return ret;
}

static int tc_attr_set_echo(bool enbale)
{
    struct termios tty;
    if (tcgetattr(STDIN_FILENO, &tty) < 0) {
        RTLS_ERR("tcgetattr failed, err: %s\n", strerror(errno));
        return ENCLAVE_VERIFIER_ERR_UNKNOWN;
    }

    if (enbale) {
        tty.c_lflag |= ECHO;
    } else {
        tty.c_lflag &= ~ECHO;
    }

    if (tcsetattr(STDIN_FILENO, TCSANOW, &tty) < 0) {
        RTLS_ERR("tcsetattr failed, err: %s\n", strerror(errno));
        return ENCLAVE_VERIFIER_ERR_UNKNOWN;
    }

    return RATS_TLS_ERR_BASE;
}

static int deal_fde_key(rats_tls_handle handle, bool use_fde, const char* rootfs_key_file)
{
    int ret = ENCLAVE_VERIFIER_ERR_UNKNOWN;

    RTLS_DEBUG("deal FDE key %d\n", use_fde);
    if (use_fde == false) {
        RTLS_INFO("FDE is not enabled\n");
        return RATS_TLS_ERR_BASE;
    }

    char *msg = ENABLE_FDE_TOKEN;
    size_t len = strlen(msg);
    ret = rats_tls_transmit(handle, (void *)msg, &len);
    if (ret != RATS_TLS_ERR_NONE || len != strlen(msg)) {
        RTLS_ERR("Failed to send fde token %#x\n", ret);
        return RATS_TLS_ERR_LOAD_TLS_WRAPPERS;
    }

    size_t key_file_len;
    uint8_t* key_file = read_file_data(rootfs_key_file, &key_file_len);
    if (!key_file) {
        RTLS_ERR("Failed to read rootfs key file\n");
        return ret;
    }
    ret = rats_tls_transmit(handle, key_file, &key_file_len);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to send rootfs key file %#x\n", ret);
        ret = RATS_TLS_ERR_LOAD_TLS_WRAPPERS;
        goto free;
    }

    RTLS_INFO("Successfully sent rootfs key file (%zu bytes)\n", key_file_len);

free:
    free(key_file);
    return ret;
}

/* New function: Request and save firmware data */
static int request_and_save_firmware_data(rats_tls_handle handle)
{
    int ret;
    
    /* Request CCEL table */
    const char *ccel_req = "REQUEST_CCEL_TABLE";
    size_t len = strlen(ccel_req);
    ret = rats_tls_transmit(handle, (void *)ccel_req, &len);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to request CCEL table %#x\n", ret);
        return ret;
    }

    /* Receive CCEL data */
    unsigned char ccel_table[MAX] = {0};
    size_t ccel_table_len = MAX;
    ret = rats_tls_receive(handle, ccel_table, &ccel_table_len);
    if (ret != RATS_TLS_ERR_NONE || ccel_table_len == 0) {
        RTLS_ERR("Failed to receive CCEL table %#x\n", ret);
        return ret;
    }
    RTLS_INFO("Received CCEL table data, size: %zu bytes\n", ccel_table_len);

    /* Save CCEL table */
    FILE *fp = fopen(CLIENT_CCEL_ACPI_TABLE_PATH, "wb");
    if (!fp) {
        RTLS_ERR("Failed to open file %s for writing\n", CLIENT_CCEL_ACPI_TABLE_PATH);
        return RATS_TLS_ERR_INVALID;
    }
    if (fwrite(ccel_table, 1, ccel_table_len, fp) != ccel_table_len) {
        RTLS_ERR("Failed to write CCEL table to file\n");
        fclose(fp);
        return RATS_TLS_ERR_INVALID;
    }
    fclose(fp);
    RTLS_INFO("CCEL table saved to %s\n", CLIENT_CCEL_ACPI_TABLE_PATH);

    /* Request event log */
    RTLS_INFO("Requesting event log...\n");
    const char *log_req = "REQUEST_EVENT_LOG";
    len = strlen(log_req);
    ret = rats_tls_transmit(handle, (void *)log_req, &len);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to request event log %#x\n", ret);
        return ret;
    }

    /* Receive event log size */
    size_t expected_size = 0;
    len = sizeof(size_t);
    ret = rats_tls_receive(handle, &expected_size, &len);
    if (ret != RATS_TLS_ERR_NONE || expected_size == 0 || expected_size > MAX_LOG) {
        RTLS_ERR("Failed to receive event log size or invalid size %#x\n", ret);
        return ret;
    }
    RTLS_INFO("Expecting event log size: %zu bytes\n", expected_size);

    /* Allocate receive buffer */
    unsigned char *event_log = (unsigned char *)malloc(expected_size);
    if (!event_log) {
        RTLS_ERR("Failed to allocate memory for event log\n");
        return RATS_TLS_ERR_NO_MEM;
    }

    /* Receive event log data */
    size_t total_received = 0;
    while (total_received < expected_size) {
        len = expected_size - total_received;
        ret = rats_tls_receive(handle, event_log + total_received, &len);
        if (ret != RATS_TLS_ERR_NONE) {
            RTLS_ERR("Failed to receive event log data %#x\n", ret);
            free(event_log);
            return ret;
        }
        total_received += len;
    }
    RTLS_INFO("Received complete event log (%zu bytes)\n", expected_size);

    /* Save event log */
    fp = fopen(CLIENT_CCEL_EVENT_LOG_PATH, "wb");
    if (!fp) {
        RTLS_ERR("Failed to open file %s for writing\n", CLIENT_CCEL_EVENT_LOG_PATH);
        free(event_log);
        return RATS_TLS_ERR_INVALID;
    }
    if (fwrite(event_log, 1, expected_size, fp) != expected_size) {
        RTLS_ERR("Failed to write event log to file\n");
        fclose(fp);
        free(event_log);
        return RATS_TLS_ERR_INVALID;
    }
    fclose(fp);
    free(event_log);
    RTLS_INFO("Event log saved to %s\n\n", CLIENT_CCEL_EVENT_LOG_PATH);

    return RATS_TLS_ERR_NONE;
}

static void print_hex_dump_with_ascii(const uint8_t* data, size_t length)
{
    char ascii_buf[17] = {0};

    printf("=> Read CCEL ACPI Table\n");
    for (size_t i = 0; i < length; i++) {
        if (i % 16 == 0) {
            if (i > 0) {
                printf("  %s\n", ascii_buf);
            }
            printf("%08zX  ", i);
            memset(ascii_buf, 0, sizeof(ascii_buf));
        }
        printf("%02X ", data[i]);
        ascii_buf[i % 16] = isprint(data[i]) ? data[i] : '.';
    }

    /* Process the last line */
    if (length % 16 != 0) {
        for (size_t i = length % 16; i < 16; i++) {
            printf("   ");
        }
    }
    printf("  %s\n", ascii_buf);
}

static void print_acpi_table(const uint8_t* ccel_data, size_t file_size, const acpi_table_info_t* info)
{
    print_hex_dump_with_ascii(ccel_data, file_size);

    printf("Revision:     %d\n", info->revision);
    printf("Length:       %zu\n", file_size);
    printf("Checksum:     %02X\n", info->checksum);
    
    printf("OEM ID:       b'");
    for (int i = 0; i < 6; i++) {
        printf("%c", info->oem_id[i]);
    }
    printf("'\n");

    printf("CC Type:      %d\n", info->cc_type);
    printf("CC Sub-type:  %d\n", info->cc_subtype);
    
    printf("Log Lenght:   0x%08lX\n", (unsigned long)info->log_length);
    printf("Log Address:  0x%08lX\n", (unsigned long)info->log_address);
    printf("\n");
}

static bool parse_acpi_table(const uint8_t* ccel_data, size_t file_size, acpi_table_info_t* info)
{
    if (!ccel_data || !info || file_size < 56) {
        return false;
    }

    if (memcmp(ccel_data, "CCEL", 4) != 0) {
        printf("Error: Invalid CCEL signature\n");
        return false;
    }

    info->revision = ccel_data[8];
    info->checksum = ccel_data[9];
    memcpy(info->oem_id, ccel_data + 10, 6);
    info->cc_type = ccel_data[36];
    info->cc_subtype = ccel_data[37];
    info->log_length = *(uint64_t*)(ccel_data + 40);
    info->log_address = *(uint64_t*)(ccel_data + 48);

    print_acpi_table(ccel_data, file_size, info);

    return true;
}

static int handle_eventlogs_command(void)
{
    size_t file_size;
    uint8_t* ccel_data = read_file_data(CLIENT_CCEL_ACPI_TABLE_PATH, &file_size);
    if (!ccel_data) {
        return 1;
    }

    acpi_table_info_t table_info;
    if (!parse_acpi_table(ccel_data, file_size, &table_info)) {
        free(ccel_data);
        return 1;
    }

    event_log_t event_log;
    if (!event_log_init(&event_log, (size_t)table_info.log_address, (size_t)table_info.log_length)) {
        printf("Error: Failed to initialize event log\n");
        free(ccel_data);
        return 1;
    }

    event_log_dump(&event_log);

    free(ccel_data);
    return 0;
}

static char* extract_json_string(const char* json, const char* key)
{
    char* value = NULL;
    char search_key[64];
    snprintf(search_key, sizeof(search_key), "\"%s\":", key);
    
    char* pos = strstr(json, search_key);
    if (pos) {
        pos = strchr(pos + strlen(search_key), '"');
        if (pos) {
            pos++; /* Skip quote */
            char* end = strchr(pos, '"');
            if (end) {
                size_t len = end - pos;
                value = (char*)malloc(len + 1);
                if (value) {
                    strncpy(value, pos, len);
                    value[len] = '\0';
                }
            }
        }
    }
    return value;
}

int rats_tls_server_startup(mig_agent_args *args)
{
    rats_tls_conf_t conf;
    rats_tls_err_t ret = RATS_TLS_ERR_NONE;
    int sockfd = -1;
    int connd = -1;
    rats_tls_handle handle = NULL;

    memset(&conf, 0, sizeof(conf));
    conf.log_level = args->log_level;
    strcpy(conf.attester_type, args->attester_type);
    strcpy(conf.verifier_type, args->verifier_type);
    strcpy(conf.tls_type, args->tls_type);
    strcpy(conf.crypto_type, args->crypto_type);

    conf.cert_algo = RATS_TLS_CERT_ALGO_RSA_3072_SHA256;
    conf.flags |= RATS_TLS_CONF_FLAGS_SERVER;
    if (args->mutual)
        conf.flags |= RATS_TLS_CONF_FLAGS_MUTUAL;

    if (args->provide_endorsements)
        conf.flags |= RATS_TLS_CONF_FLAGS_PROVIDE_ENDORSEMENTS;

    sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        RTLS_ERR("Failed to call socket()");
        ret = RATS_TLS_ERR_INVALID;
        goto out;
    }

    int reuse = 1;
    if (setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, (const void *)&reuse, sizeof(int)) < 0) {
        RTLS_ERR("Failed to call setsockopt(SO_REUSEADDR)");
        ret = RATS_TLS_ERR_INVALID;
        goto out;
    }

    /* Set keepalive options */
    int flag = 1;
    int tcp_keepalive_time = 30;
    int tcp_keepalive_intvl = 10;
    int tcp_keepalive_probes = 5;
    if (setsockopt(sockfd, SOL_SOCKET, SO_KEEPALIVE, &flag, sizeof(flag)) < 0) {
        RTLS_ERR("Failed to call setsockopt(SO_KEEPALIVE)");
        ret = RATS_TLS_ERR_INVALID;
        goto out;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPIDLE, &tcp_keepalive_time,
                   sizeof(tcp_keepalive_time)) < 0) {
        RTLS_ERR("Failed to call setsockopt(TCP_KEEPIDLE)");
        ret = RATS_TLS_ERR_INVALID;
        goto out;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPINTVL, &tcp_keepalive_intvl,
                   sizeof(tcp_keepalive_intvl)) < 0) {
        RTLS_ERR("Failed to call setsockopt(TCP_KEEPINTVL)");
        ret = RATS_TLS_ERR_INVALID;
        goto out;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPCNT, &tcp_keepalive_probes,
                   sizeof(tcp_keepalive_probes)) < 0) {
        RTLS_ERR("Failed to call setsockopt(TCP_KEEPCNT)");
        ret = RATS_TLS_ERR_INVALID;
        goto out;
    }

    struct sockaddr_in s_addr;
    memset(&s_addr, 0, sizeof(s_addr));
    s_addr.sin_family = AF_INET;
    s_addr.sin_addr.s_addr = inet_addr(args->srv_ip);
    s_addr.sin_port = htons(args->port);

    /* Bind the server socket */
    if (bind(sockfd, (struct sockaddr *)&s_addr, sizeof(s_addr)) == -1) {
        RTLS_ERR("Failed to call bind()");
        ret = RATS_TLS_ERR_INVALID;
        goto out;
    }

    /* Listen for a new connection, allow 5 pending connections */
    if (listen(sockfd, 5) == -1) {
        RTLS_ERR("Failed to call listen()");
        ret = RATS_TLS_ERR_INVALID;
        goto out;
    }

    ret = rats_tls_init(&conf, &handle);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to initialize rats tls %#x\n", ret);
        goto out;
    }

    ret = rats_tls_set_verification_callback(&handle, NULL);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to set verification callback %#x\n", ret);
        goto out;
    }

    RTLS_INFO("Waiting for a connection ...\n");
    /* Accept client connections */
    struct sockaddr_in c_addr;
    socklen_t size = sizeof(c_addr);

    connd = accept(sockfd, (struct sockaddr *)&c_addr, &size);
    if (connd < 0) {
        RTLS_ERR("Failed to call accept()");
        ret = RATS_TLS_ERR_INVALID;
        goto out;
    }

    ret = rats_tls_negotiate(handle, connd);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to negotiate %#x\n", ret);
        goto out;
    }

    RTLS_DEBUG("Client connected successfully\n");
    ret = deal_client_req(handle, args);
    if (ret != RATS_TLS_ERR_NONE && ret != 0x68) {
        RTLS_ERR("Client verify failed %#x\n", ret);
        goto out;
    } else {
        RTLS_INFO("Client verify success, do other jobs.\n");
        goto out;
    }

out:
    if (connd >= 0) {
        close(connd);
        connd = -1;
    }
    if (sockfd >= 0) {
        shutdown(sockfd, SHUT_RDWR);
        close(sockfd);
        sockfd = -1;
    }
    if (handle) {
        rats_tls_err_t cleanup_ret = rats_tls_cleanup(handle);
        if (cleanup_ret != RATS_TLS_ERR_NONE)
            RTLS_ERR("Failed to cleanup rats-tls %#x\n", cleanup_ret);
    }

    RTLS_INFO("server cleanup!\n");
    if (ret == 0x68) {
        return 0x68;
    } else if (ret == RATS_TLS_ERR_NONE) {
        return 0x67;
    } else {
        return -1;
    }
}

int rats_tls_client_startup(mig_agent_args *args)
{
    int ret;
    rats_tls_conf_t conf;
    rats_tls_handle handle = NULL;
    int sockfd = -1;
    /* Create static configuration storage */
    static mig_agent_args static_args;
    static claim_t static_claim;

    /* Copy parameters to static storage */
    memcpy(&static_args, args, sizeof(mig_agent_args));

    memset(&conf, 0, sizeof(conf));
    conf.log_level = args->log_level;
    strcpy(conf.attester_type, args->attester_type);
    strcpy(conf.verifier_type, args->verifier_type);
    strcpy(conf.tls_type, args->tls_type);
    strcpy(conf.crypto_type, args->crypto_type);
    conf.cert_algo = RATS_TLS_CERT_ALGO_RSA_3072_SHA256;
    if (args->mutual)
        conf.flags |= RATS_TLS_CONF_FLAGS_MUTUAL;
    if (args->provide_endorsements)
        conf.flags |= RATS_TLS_CONF_FLAGS_PROVIDE_ENDORSEMENTS;

    /* Set static claim, using type casting to avoid warnings */
    static_claim.name = "mig_agent_args";
    static_claim.value = (uint8_t *)&static_args;
    static_claim.value_size = sizeof(mig_agent_args);
    conf.custom_claims = &static_claim;
    conf.custom_claims_length = 1; /* Set length to 1, indicating only one claim */

    RTLS_INFO("Setting up custom claims with args=%p", &static_args);

    /* Create socket and connect */
    sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        RTLS_ERR("failed to call socket()\n");
        ret = RATS_TLS_ERR_INVALID;
        goto err;
    }

    struct sockaddr_in s_addr;
    memset(&s_addr, 0, sizeof(s_addr));
    s_addr.sin_family = AF_INET;
    s_addr.sin_port = htons(args->port);

    if (inet_pton(AF_INET, args->srv_ip, &s_addr.sin_addr) != 1) {
        RTLS_ERR("invalid server address\n");
        ret = RATS_TLS_ERR_INVALID;
        goto err;
    }

    if ((ret = connect(sockfd, (struct sockaddr *)&s_addr, sizeof(s_addr))) == -1) {
        RTLS_ERR("failed to call connect()\n");
        ret = RATS_TLS_ERR_INVALID;
        goto err;
    }

    ret = rats_tls_init(&conf, &handle);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to initialize rats tls %#x\n", ret);
        goto err;
    }

    /* Ensure configuration is correctly copied to handle */
    rtls_core_context_t *ctx = (rtls_core_context_t *)handle;
    if (!ctx->config.custom_claims) {
        RTLS_ERR("Failed to set custom claims in handle\n");
        ret = RATS_TLS_ERR_INVALID;
        goto err;
    }
    RTLS_DEBUG("Custom claims set in handle: %p", ctx->config.custom_claims->value);

    ret = rats_tls_set_verification_callback(&handle, user_callback);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to set verification callback %#x\n", ret);
        goto err;
    }

    ret = rats_tls_negotiate(handle, sockfd);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to negotiate %#x\n", ret);
        goto err;
    }

    /* Platform SW Components Verification */
    if (static_args.verify_platform_components) {
        RTLS_INFO("Starting Platform SW Components verification...");
        
        /* Get token from verifier context */
        rtls_core_context_t *ctx = (rtls_core_context_t *)handle;
        if (!ctx || !ctx->verifier || !ctx->verifier->verifier_private) {
            RTLS_ERR("Failed to get verifier context for platform verification\n");
            ret = RATS_TLS_ERR_INVALID;
            goto err;
        }

        /* Parse token from verifier_private */
        cca_token_t token = {0};
        cca_token_buf_t *cca_token_buf = (cca_token_buf_t *)ctx->verifier->verifier_private;
        
        if (parse_cca_attestation_token(&token, cca_token_buf->buf, cca_token_buf->buf_size) != VIRTCCA_SUCCESS) {
            RTLS_ERR("Failed to parse virtcca token for platform verification\n");
            ret = RATS_TLS_ERR_INVALID;
            goto err;
        }

        /* Check if platform token exists */
        if (token.platform_cose.ptr != NULL && token.platform_cose.len > 0) {
            if (!static_args.platform_ref_json_file) {
                RTLS_ERR("Platform verification enabled but no reference JSON file provided\n");
                ret = RATS_TLS_ERR_INVALID;
                goto err;
            }

            /* Load platform reference values */
            platform_ref_values_t ref_values = {0};
            if (!load_platform_ref_values(static_args.platform_ref_json_file, &ref_values)) {
                RTLS_ERR("Failed to load platform reference values from: %s\n", static_args.platform_ref_json_file);
                ret = RATS_TLS_ERR_INVALID;
                goto err;
            }

            /* Perform platform SW components verification */
            if (!verify_platform_sw_components(&token.platform_token, &ref_values)) {
                RTLS_ERR("Platform SW components verification failed\n");
                ret = RATS_TLS_ERR_INVALID;
                goto err;
            }

            RTLS_INFO("Platform SW components verification PASSED!\n");
        } else {
            RTLS_WARN("Platform verification requested but no platform token present in attestation\n");
        }
    }

    /* Handle IMA verification */
    if ((ret = deal_ima(handle, &static_args)) != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Verify IMA measurement failed %#x\n", ret);
        goto err;
    }

    /* If firmware verification is enabled, first get and verify firmware state */
    if (static_args.use_firmware || static_args.dump_eventlog) {
        RTLS_INFO("Starting firmware verification process\n");
        
        /* Request and receive CCEL table and event log */
        ret = request_and_save_firmware_data(handle);
        if (ret != RATS_TLS_ERR_NONE) {
            RTLS_ERR("Failed to get firmware data %#x\n", ret);
            goto err;
        }

        /* If in dump_eventlog mode, directly execute handle_eventlogs_command and return */
        if (static_args.dump_eventlog) {
            ret = handle_eventlogs_command();
            goto err;
        }

        /* Below is the firmware verification logic */
        /* Initialize event log processor */
        event_log_t event_log;
        if (!event_log_init(&event_log, 0, 0)) {
            RTLS_ERR("Failed to initialize event log\n");
            ret = RATS_TLS_ERR_INVALID;
            goto err;
        }

        /* Replay event log to calculate REM values */
        if (!event_log_replay(&event_log)) {
            RTLS_ERR("Failed to replay event log\n");
            ret = RATS_TLS_ERR_INVALID;
            goto err;
        }

        /* Verify REM values from token */
        RTLS_INFO("Verifying REM values from token...\n");

        /* Get token from verifier context */
        rtls_core_context_t *ctx = (rtls_core_context_t *)handle;
        if (!ctx || !ctx->verifier || !ctx->verifier->verifier_private) {
            RTLS_ERR("Failed to get verifier context\n");
            ret = RATS_TLS_ERR_INVALID;
            goto err;
        }

        /* Parse token from verifier_private */
        cca_token_t token = {0};
        cca_token_buf_t *cca_token_buf = (cca_token_buf_t *)ctx->verifier->verifier_private;

        if (parse_cca_attestation_token(&token, cca_token_buf->buf, cca_token_buf->buf_size) != VIRTCCA_SUCCESS) {
            RTLS_ERR("Failed to parse virtcca token\n");
            ret = RATS_TLS_ERR_INVALID;
            goto err;
        }

        bool all_rems_passed = true;
        for (int i = 0; i < REM_COUNT; i++) {
            if (token.cvm_token.rem[i].len != sizeof(rem_t)) {
                RTLS_ERR("Invalid REM[%d] size in token\n", i);
                ret = RATS_TLS_ERR_INVALID;
                goto err;
            }
            
            verify_single_rem(i, (rem_t*)token.cvm_token.rem[i].ptr, &event_log.rems[i]);
            if (!rem_compare((rem_t*)token.cvm_token.rem[i].ptr, &event_log.rems[i])) {
                all_rems_passed = false;
            }
        }
        
        if (!all_rems_passed) {
            RTLS_ERR("REM verification failed\n");
            ret = RATS_TLS_ERR_INVALID;
            goto err;
        }
        
        RTLS_INFO("All REM values verified successfully\n");
        printf("\n=====================================\n");

        /* Create firmware state */
        firmware_log_state_t* state = firmware_log_state_create(&event_log);
        if (!state) {
            RTLS_ERR("Failed to create firmware state\n");
            ret = RATS_TLS_ERR_INVALID;
            goto err;
        }

        /* Extract firmware state */
        if (!firmware_log_state_extract(&event_log, state)) {
            RTLS_ERR("Failed to extract firmware state\n");
            firmware_log_state_free(state);
            ret = RATS_TLS_ERR_INVALID;
            goto err;
        }

        /* Verify firmware state */
        if (!verify_firmware_state(static_args.ref_json_file, state)) {
            RTLS_ERR("Firmware state verification failed\n");
            firmware_log_state_free(state);
            ret = RATS_TLS_ERR_INVALID;
            goto err;
        }

        firmware_log_state_free(state);
        RTLS_INFO("Firmware verification completed successfully\n\n");
    }

    if ((ret = deal_fde_key(handle, args->use_fde, args->rootfs_key_file)) != RATS_TLS_ERR_NONE) {
        RTLS_ERR("deal fde key failed %#x\n", ret);
        goto err;
    }
    
    const char *msg = MIG_MSK_SEND;
    size_t len = strlen(msg);
    ret = rats_tls_transmit(handle, (void *)msg, &len);
    if (ret != RATS_TLS_ERR_NONE || len != strlen(msg)) {
        RTLS_ERR("Failed to transmit %#x\n", ret);
        goto err;
    }

    char buf[256] = {0};
    len = sizeof(buf);
    ret = rats_tls_receive(handle, buf, &len);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to receive %#x\n", ret);
        goto err;
    }

    if (len >= sizeof(buf)) {
        len = sizeof(buf) - 1;
    }
    buf[len] = '\0';

    /* virtCCA insert: Migration session key exchange */
    RTLS_INFO("Sent to Server MSK\n");

    unsigned long long migrate_key_package[10];
    /* Process MIG_MSK_SEND */
    if (strncmp(buf, MIG_MSK_ACK, strlen(MIG_MSK_ACK)) == 0) {
        RTLS_INFO("Received MIG_MSK_ACK, transmit msk\n");
        memcpy(migrate_key_package, args->msk, sizeof(args->msk));
        memcpy(migrate_key_package + 4, args->rand_iv, sizeof(args->rand_iv));
        memcpy(migrate_key_package + 8, args->tag, sizeof(args->tag));
        len = sizeof(migrate_key_package);
        ret = rats_tls_transmit(handle, migrate_key_package, &len);
        if (ret != RATS_TLS_ERR_NONE) {
            RTLS_ERR("Failed to transmit %#x\n", ret);
            goto err;
        }
    }

err:
    if (handle) {
        /* Clear custom_claims before cleanup to prevent freeing static memory */
        rtls_core_context_t *ctx = (rtls_core_context_t *)handle;
        if (ctx) {
            ctx->config.custom_claims = NULL;
            ctx->config.custom_claims_length = 0;
        }
        rats_tls_cleanup(handle);
    }
    if (sockfd >= 0) {
        shutdown(sockfd, SHUT_RDWR);
        close(sockfd);
        sockfd = -1;
    }
    return ret;
}
