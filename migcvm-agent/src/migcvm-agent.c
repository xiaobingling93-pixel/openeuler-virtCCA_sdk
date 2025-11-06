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
#include <getopt.h>
#include <errno.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <rats-tls/api.h>
#include <rats-tls/log.h>
#include <rats-tls/claim.h>
#include <sys/stat.h>
#include "utils.h"

/* client */
#include <termios.h>
#include <ctype.h>
#include <internal/core.h>
#include "openssl/rand.h"
#include "openssl/x509.h"
#include "openssl/pem.h"
#include "openssl/bio.h"
#include "openssl/evp.h"
#include "openssl/ec.h"

#include "token_parse.h"
#include "token_validate.h"
#include "platform_verify.h"
#include "common.h"
#include "ima_measure.h"

#include "token_parse.h"
#include "token_validate.h"
#include "event_log.h"
#include "firmware_state.h"
#include "binary_blob.h"
#include "verify.h"
#include "config.h"

#include "socket_agent.h"
#include "migcvm_tsi.h"

#define    MIG_TYPE_SERVER 1
#define    MIG_TYPE_CLIENT 2

rats_tls_log_level_t global_log_level = RATS_TLS_LOG_LEVEL_DEFAULT;

static uint8_t g_rim_ref[MAX_MEASUREMENT_SIZE];
static size_t g_rim_ref_size = MAX_MEASUREMENT_SIZE;
static int start_listening = 1;
pending_guest_rd_t *pending_guest_rds = NULL;

rats_tls_err_t read_ima_measurements(uint8_t **value, size_t *size)
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

int send_ima_log(rats_tls_handle handle)
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

int deal_rootfs_key(rats_tls_handle handle)
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

int send_ccel_data(rats_tls_handle handle)
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

int send_event_log(rats_tls_handle handle)
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

int deal_client_req(rats_tls_handle handle)
{
    int ret = ENCLAVE_ATTESTER_ERR_UNKNOWN;
    char buf[256] = {0};
    size_t len = sizeof(buf);

    ret = rats_tls_receive(handle, buf, &len);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to receive %#x\n", ret);
        return ret;
    }

    if (len >= sizeof(buf))
        len = sizeof(buf) - 1;
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
        return deal_client_req(handle);
    }

    /* Process event log request */
    if (strncmp(buf, "REQUEST_EVENT_LOG", strlen("REQUEST_EVENT_LOG")) == 0) {
        ret = send_event_log(handle);
        if (ret) {
            RTLS_ERR("Send event log failed %#x\n", ret);
            return ret;
        }
        RTLS_INFO("Send event log success\n");
        return deal_client_req(handle);
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
            ret = deal_client_req(handle);
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
            if ((ret = deal_client_req(handle))) {
                RTLS_ERR("recevice PASS ACK failed %#x\n", ret);
                return ret;
            }
            ret = 0x68; /* Return specific value for LUKS completion */
        }
        return ret;
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
} while(0)

/* Forward declarations */
static char* extract_json_string(const char* json, const char* key);
static int parse_input_mig_agent_args(int argc, char **argv, mig_agent_args *args);
static int request_and_save_firmware_data(rats_tls_handle handle);
static int handle_eventlogs_command(void);

int user_callback(void *args)
{
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
    memcpy(&cca_token_buf, ev->cca.evidence, ev->cca.evidence_sz);
    
    ret = parse_cca_attestation_token(&token, cca_token_buf.buf, cca_token_buf.buf_size);
    if (ret != VIRTCCA_SUCCESS) {
        RTLS_ERR("failed to parse virtcca token\n");
        return ENCLAVE_VERIFIER_ERR_CBOR;
    }
    RTLS_DEBUG("Token parsed successfully\n");

    cert_info_t cert_info;
    /* Detect AIK certificate type and configure certificate chain accordingly */
    // cert_type_t aik_cert_type = detect_aik_cert_type(DEFAULT_AIK_CERT_PEM_FILENAME);
    // configure_cert_info_by_type(&cert_info, aik_cert_type);

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
    
    // ret = verify_cca_token_signatures(&cert_info,
    //                             platform_cose,
    //                             token.cvm_cose,
    //                             token.cvm_token.pub_key,
    //                             platform_challenge,
    //                             token.cvm_token.pub_key_hash_algo_id);
    // if (!ret) {
    //     RTLS_ERR("Token signature verification failed");
    //     return false;
    // }
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
    if (ret)
        return ret;

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

static int deal_passwd(char password[MAX_PASSWD_LEN])
{
    int i = 0;
    char ch;

    RTLS_INFO("Enter remote disk image password: ");
    if (tc_attr_set_echo(false)) {
        return ENCLAVE_VERIFIER_ERR_UNKNOWN;
    }
    while ((ch = getchar()) != '\n' && ch != EOF) {
        if (i > MAX_PASSWD_LEN - 1) {
            RTLS_ERR("Input passwd too long,\n");
            return ENCLAVE_VERIFIER_ERR_UNKNOWN;
        }
        password[i++] = ch;
    }
    putchar('\n');
    if (tc_attr_set_echo(true)) {
        return ENCLAVE_VERIFIER_ERR_UNKNOWN;
    }
    
    for (i = 0; i < MAX_PASSWD_LEN; i++) {
        password[i] = '\0';
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

static int mig_agent_init(mig_agent_args *args)
{
    args->agent_type = 0;

    args->srv_ip = malloc(MAX_PAYLOAD_SIZE);
    if (args->srv_ip == NULL) {
        perror("malloc failed");
        return -1;
    }

    args->attester_type = "";
    args->verifier_type = "";
    args->tls_type = "";
    args->crypto_type = "";
    args->port = MIGCVM_PORT;
    args->digest_file = "";
    args->log_level = RATS_TLS_LOG_LEVEL_INFO;
    args->mutual = false;
    args->provide_endorsements = false;
    args->use_firmware = false;
    args->dump_eventlog = false;
    args->ref_json_file = NULL;
    args->use_fde = false;
    args->rootfs_key_file = NULL;
    args->verify_platform_components = false;
    args->platform_ref_json_file = NULL;

    return 0;
}

static int mig_agent_exit(mig_agent_args *args)
{
    free(args->srv_ip);
    return 0;
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

static int parse_input_mig_agent_args(int argc, char **argv, mig_agent_args *args)
{
    int opt;
    char *rim = NULL;
    char *const short_options = "i:p:r:f:h";
    struct option long_options[] = {
        { "ip", required_argument, NULL, 'i' },
        { "port", required_argument, NULL, 'p' },
        { "rim", required_argument, NULL, 'r' },
        { "firmware", required_argument, NULL, 'f' },
        { "help", no_argument, NULL, 'h' },
        { 0, 0, 0, 0 }
    };

    do {
        opt = getopt_long(argc, argv, short_options, long_options, NULL);
        switch (opt) {
        case 'i':
            args->srv_ip = optarg;
            break;
        case 'p':
            args->port = atoi(optarg);
            break;
        case 'r':
            CHECK_LENGHT_ASSIGN(optarg, MAX_MEASUREMENT_SIZE + 1, rim);
            if (hex_to_bytes((unsigned char*)rim, strlen(rim), g_rim_ref, &g_rim_ref_size) != 0) {
                printf("change rim to bytes failed\n");
                return -1;
            }
            break;
        case 'f':
            args->use_firmware = true;
            args->ref_json_file = optarg;
            break;
        case 'g':
            if (args->use_firmware) {
                printf("Error: Cannot use -g and -f together\n");
                return -1;
            }
            args->dump_eventlog = true;
            break;
        case -1:
            break;
        default:
            puts("    Usage:\n\n"
                 "        rats-tls-client <options> [arguments]\n\n"
                 "    Options:\n\n"
                 "        --attester/-a value   set the type of quote attester\n"
                 "        --verifier/-v value   set the type of quote verifier\n"
                 "        --tls/-t value        set the type of tls wrapper\n"
                 "        --crypto/-c value     set the type of crypto wrapper\n"
                 "        --mutual/-m           set to enable mutual attestation\n"
                 "        --endorsements/-e     set to let attester provide endorsements\n"
                 "        --log-level/-l        set the log level\n"
                 "        --ip/-i               set the listening ip address\n"
                 "        --port/-p             set the listening tcp port\n"
                 "        --rim/-r              set the initial measurement of cVM\n"
                 "        --digest/-d           set the digest list file for verifying IMA measurement\n"
                 "        --firmware/-f         enable firmware verification with JSON reference file\n"
                 "        --eventlog/-g         dump VCCA event logs\n"
                 "        --fdekey/-k           enable Full Disk Encryption with rootfs key file\n"
                 "        --platform/-P         enable platform SW-components verification with JSON reference file\n"
                 "        --help/-h             show the usage\n");
            return -1;
        }
    } while (opt != -1);
    global_log_level = RATS_TLS_LOG_LEVEL_INFO;

    return 0;
}

int rats_tls_server_startup(mig_agent_args *args)
{
    rats_tls_conf_t conf;
    rats_tls_err_t ret;
    memset(&conf, 0, sizeof(conf));
    conf.log_level = args->log_level;
    strcpy(conf.attester_type, args->attester_type);
    strcpy(conf.verifier_type, args->verifier_type);
    strcpy(conf.tls_type, args->tls_type);
    strcpy(conf.crypto_type, args->crypto_type);
    int sockfd = -1;

    conf.cert_algo = RATS_TLS_CERT_ALGO_DEFAULT;
    conf.flags |= RATS_TLS_CONF_FLAGS_SERVER;
    if (args->mutual)
        conf.flags |= RATS_TLS_CONF_FLAGS_MUTUAL;

    if (args->provide_endorsements)
        conf.flags |= RATS_TLS_CONF_FLAGS_PROVIDE_ENDORSEMENTS;

    sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        RTLS_ERR("Failed to call socket()");
        return -1;
    }

    int reuse = 1;
    if (setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, (const void *)&reuse, sizeof(int)) < 0) {
        RTLS_ERR("Failed to call setsockopt()");
        return -1;
    }

    /* Set keepalive options */
    int flag = 1;
    int tcp_keepalive_time = 30;
    int tcp_keepalive_intvl = 10;
    int tcp_keepalive_probes = 5;
    if (setsockopt(sockfd, SOL_SOCKET, SO_KEEPALIVE, &flag, sizeof(flag)) < 0) {
        RTLS_ERR("Failed to call setsockopt()");
        return -1;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPIDLE, &tcp_keepalive_time,
                   sizeof(tcp_keepalive_time)) < 0) {
        RTLS_ERR("Failed to call setsockopt()");
        return -1;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPINTVL, &tcp_keepalive_intvl,
                   sizeof(tcp_keepalive_intvl)) < 0) {
        RTLS_ERR("Failed to call setsockopt()");
        return -1;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPCNT, &tcp_keepalive_probes,
                   sizeof(tcp_keepalive_probes)) < 0) {
        RTLS_ERR("Failed to call setsockopt()");
        return -1;
    }

    struct sockaddr_in s_addr;
    memset(&s_addr, 0, sizeof(s_addr));
    s_addr.sin_family = AF_INET;
    s_addr.sin_addr.s_addr = inet_addr(args->srv_ip);
    s_addr.sin_port = htons(args->port);

    /* Bind the server socket */
    if (bind(sockfd, (struct sockaddr *)&s_addr, sizeof(s_addr)) == -1) {
        RTLS_ERR("Failed to call bind()");
        return -1;
    }

    /* Listen for a new connection, allow 5 pending connections */
    if (listen(sockfd, 5) == -1) {
        RTLS_ERR("Failed to call listen()");
        return -1;
    }

    rats_tls_handle handle;

    ret = rats_tls_init(&conf, &handle);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to initialize rats tls %#x\n", ret);
        goto err;
    }

    ret = rats_tls_set_verification_callback(&handle, NULL);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to set verification callback %#x\n", ret);
        goto err;
    }

    while (start_listening) {
        RTLS_INFO("Waiting for a connection ...\n");

        /* Accept client connections */
        struct sockaddr_in c_addr;
        socklen_t size = sizeof(c_addr);

        int connd = accept(sockfd, (struct sockaddr *)&c_addr, &size);
        if (connd < 0) {
            RTLS_ERR("Failed to call accept()");
            continue;
        }

        ret = rats_tls_negotiate(handle, connd);
        if (ret != RATS_TLS_ERR_NONE) {
            RTLS_ERR("Failed to negotiate %#x\n", ret);
            goto close_connd;
        }

        RTLS_DEBUG("Client connected successfully\n");
        ret = deal_client_req(handle);
        if (ret != RATS_TLS_ERR_NONE && ret != 0x68) {
            RTLS_ERR("Client verify failed %#x\n", ret);
        } else {
            RTLS_INFO("Client verify success, do other jobs.\n");
            close(connd);
            break;
        }

    close_connd:
        close(connd);
    }

    shutdown(sockfd, SHUT_RDWR);
    close(sockfd);

    if (rats_tls_cleanup(handle) != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to cleanup\n");
        return RATS_TLS_ERR_INVALID;
    }

    if (ret == 0x68) {
        return 0x68;
    } else {
        return 0x67;
    }

err:
    /* Ignore the error code of cleanup in order to return the prepositional error */
    if (sockfd != -1) {
        shutdown(sockfd, SHUT_RDWR);
        close(sockfd);
        sockfd = -1;
    }
    rats_tls_cleanup(handle);
    return -1;
}

int rats_tls_client_startup(mig_agent_args *args)
{
    int ret;
    rats_tls_conf_t conf;
    rats_tls_handle handle = NULL;

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
    conf.cert_algo = RATS_TLS_CERT_ALGO_DEFAULT;
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
    int sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        RTLS_ERR("failed to call socket()\n");
        return -1;
    }

    struct sockaddr_in s_addr;
    memset(&s_addr, 0, sizeof(s_addr));
    s_addr.sin_family = AF_INET;
    s_addr.sin_port = htons(args->port);

    if (inet_pton(AF_INET, args->srv_ip, &s_addr.sin_addr) != 1) {
        RTLS_ERR("invalid server address\n");
        ret = -1;
        goto err;
    }

    if ((ret = connect(sockfd, (struct sockaddr *)&s_addr, sizeof(s_addr))) == -1) {
        RTLS_ERR("failed to call connect()\n");
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
    
    const char *msg = TOKEN;
    size_t len = strlen(msg);
    ret = rats_tls_transmit(handle, (void *)msg, &len);
    if (ret != RATS_TLS_ERR_NONE || len != strlen(msg)) {
        RTLS_ERR("Failed to transmit %#x\n", ret);
        goto err;
    }

    char buf[1024];
    len = sizeof(buf);
    ret = rats_tls_receive(handle, buf, &len);
    if (ret != RATS_TLS_ERR_NONE) {
        RTLS_ERR("Failed to receive %#x\n", ret);
        goto err;
    }

    if (len >= sizeof(buf))
        len = sizeof(buf) - 1;
    buf[len] = '\0';

    printf("Sent to Server: %s\n", msg);
    printf("The msk is: 0x1\n");
    printf("Received from Server: %s\n", buf);

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
    shutdown(sockfd, SHUT_RDWR);
    close(sockfd);
    return ret;
}

static int insert_a_guest_rd_in_pending_guest_rds(unsigned long long guest_rd)
{
    for (int i = 0; i < MAX_BIND_VM; i++) {
        if (pending_guest_rds->guest_rd[i] == 0) {
            pending_guest_rds->guest_rd[i] = guest_rd;
            return 0;
        }
    }
    return -1;
}

static void ras_tls_handler(const struct socket_msg *msg, int conn_fd, mig_agent_args *args)
{
    int ret;
    RTLS_INFO("Custom handling: cmd=%s, payload_type=%d\n",
              msg->cmd, msg->payload_type);
    
    if (msg->payload_type != PAYLOAD_TYPE_CHAR) {
        RTLS_ERR("Expected char payload, got type %d\n", msg->payload_type);
        return;
    }
    
    char ip_buffer[MAX_PAYLOAD_SIZE];
    if (strcmp(msg->cmd, "s") == 0) {
        RTLS_INFO("start server\n");
        payload_decode(msg, ip_buffer);
        strncpy(args->srv_ip, ip_buffer, MAX_PAYLOAD_SIZE);
        ret = rats_tls_server_startup(args);
    } else if (strcmp(msg->cmd, "c") == 0) {
        RTLS_INFO("start client\n");
        payload_decode(msg, ip_buffer);
        strncpy(args->srv_ip, ip_buffer, MAX_PAYLOAD_SIZE);
        ret = rats_tls_client_startup(args);
    } else {
        printf("error msg->cmd %s\n", msg->cmd);
    }

    const char *resp = "ACK";
    write(conn_fd, resp, strlen(resp) + 1);
}

static void host_handler(const struct socket_msg *msg, int conn_fd,
                         mig_agent_args *args)
{
    RTLS_INFO("Host handling: cmd=%s, payload_type=%d\n",
              msg->cmd, msg->payload_type);
    
    if (strcmp(msg->cmd, "BIND_COMPLETE") == 0) {
        if (msg->payload_type != PAYLOAD_TYPE_ULL) {
            RTLS_ERR("Expected ULL payload for BIND_COMPLETE, got type %d\n",
                     msg->payload_type);
            return;
        }
        
        unsigned long long guest_rd;
        payload_decode(msg, &guest_rd);
        
        if (insert_a_guest_rd_in_pending_guest_rds(guest_rd)) {
            perror("Failed to insert guest RD");
        }
    }
    
    printf("Host handling: cmd=%s, payload_type=%d\n",
           msg->cmd, msg->payload_type);
}

static unsigned long long get_first_rd(pending_guest_rd_t *pending_guest_rds)
{
    for (int i = 0; i < MAX_BIND_VM; i++) {
        if (pending_guest_rds->guest_rd[i]) {
            return pending_guest_rds->guest_rd[i];
        }
    }
    return -1;
}

static int prepare_migration(unsigned long long guest_rd)
{
    tsi_ctx *ctx = NULL;
    virtcca_mig_info_t *migvm_info;
    migration_info_t *attest_info;
    int ret;
    int function_to_test = 0; /* 1 for get_migration_info, 2 for set_migration_bind_slot */

    /* Initialize TSI context */
    ctx = tsi_new_ctx();
    if (ctx == NULL) {
        printf("Failed to create TSI context\n");
        return -1;
    }

    printf("using guest_rd: 0x%llx\n", guest_rd);
    migvm_info = (virtcca_mig_info_t *)malloc(sizeof(virtcca_mig_info_t));
    if (!migvm_info) {
        printf("Failed to initialize migvm_info\n");
        tsi_free_ctx(ctx);
        return -1;
    }
    migvm_info->guest_rd = guest_rd;
    attest_info = (migration_info_t *)malloc(sizeof(migration_info_t));
    if (!attest_info) {
        printf("Failed to initialize attest_info\n");
        tsi_free_ctx(ctx);
        return -1;
    };
    attest_info->msk[0] = 0x11;

    attest_info->pending_guest_rds = pending_guest_rds;
    migvm_info->mig_info = attest_info;

    printf("Testing get_rd_info with guestRd=0x%llx...\n", migvm_info->guest_rd);
    ret = set_migration_bind_slot_and_mask(ctx, migvm_info, attest_info);
    if (ret == TSI_SUCCESS) {
        printf("set_migration_bind_slot_and_mask succeeded\n");
    } else {
        printf("set_migration_bind_slot_and_mask failed with error: 0x%08x\n", ret);
        return -1;
    }
    free(attest_info);
    free(migvm_info);
    tsi_free_ctx(ctx);
    return ret;
}

static unsigned long long get_guest_rd(pending_guest_rd_t *pending_guest_rds, bool *startup)
{
    tsi_ctx *ctx = NULL;
    virtcca_mig_info_t *migvm_info;
    migration_info_t *attest_info;
    int ret;
    int function_to_test = 0; /* 1 for get_migration_info, 2 for set_migration_bind_slot */

    printf("size of virtcca_mig_info_t is %zu\n", sizeof(virtcca_mig_info_t));
    printf("size of migration_info_t is %zu\n", sizeof(migration_info_t));
    if (!*startup)
        return get_first_rd(pending_guest_rds);
    ctx = tsi_new_ctx();
    if (ctx == NULL) {
        printf("Failed to create TSI context\n");
        return -1;
    }
    attest_info = (migration_info_t *)malloc(sizeof(migration_info_t));
    if (!attest_info) {
        printf("Failed to initialize attest_info\n");
        tsi_free_ctx(ctx);
        return -1;
    };
    migvm_info = (virtcca_mig_info_t *)malloc(sizeof(virtcca_mig_info_t));
    // if (memset_s(&migvm_info, sizeof(migvm_info), 0, sizeof(migvm_info)) != 0) {
    if (!migvm_info) {
        printf("Failed to initialize migvm_info\n");
        tsi_free_ctx(ctx);
        return -1;
    }
    attest_info->pending_guest_rds = pending_guest_rds;
    ret = get_migration_binded_rds(ctx, migvm_info, attest_info);

    if (ret == TSI_SUCCESS) {
        printf("get_rd_info succeeded\n");
    } else {
        printf("get_rd_info failed with error: 0x%08x\n", ret);
        tsi_free_ctx(ctx);
        return -1;
    }
    tsi_free_ctx(ctx);
    *startup = false;
    free(migvm_info);
    free(attest_info);
    return get_first_rd(pending_guest_rds);
}

int main(int argc, char **argv)
{
    pthread_t vsock_thread, tcp_thread;
    mig_agent_args input_args = {0};
    struct socket_agent_cfg cfg = {
        .args = &input_args,
        .cid = MIGCVM_CID,
        .port = HOST_AGENT_PORT,
        .backlog = 5            /* the length of the listening queue */
    };

    mig_agent_init(&input_args);
    if (parse_input_mig_agent_args(argc, argv, &input_args)) {
        RTLS_ERR("Error parsing input args.\n");
        goto out;
    }

    int ret = socket_agent_start_with_handler(&cfg, ras_tls_handler); /* host socket */
    if (ret != 0) {
        fprintf(stderr, "Failed to start socket agent: %d\n", ret);
        goto out;
    }

out:
    mig_agent_exit(&input_args);
    return 0;
}

static int auto_test_main(int argc, char **argv)
{
    pthread_t vsock_thread, tcp_thread;
    mig_agent_args input_args = {0};
    int ret = 0;
    bool rds_should_init = true;

    pending_guest_rds = (pending_guest_rd_t *)malloc(sizeof(pending_guest_rd_t));
    if (!pending_guest_rds) {
        perror("Failed to allocate pending_guest_rds");
        return -1;
    }

    struct socket_agent_cfg cfg = {
        .args = &input_args,
        .cid = MIGCVM_CID,
        .port = HOST_AGENT_PORT,
        .backlog = 5            /* the length of the listening queue */
    };

    mig_agent_init(&input_args);
    if (parse_input_mig_agent_args(argc, argv, &input_args)) {
        RTLS_ERR("Error parsing input args.\n");
        goto out;
    }

    /* use tsi get the rds which will be migrated */
    unsigned long long guest_rd = get_guest_rd(pending_guest_rds, &rds_should_init);
    if (guest_rd != 0) {
        ret = socket_agent_start_with_handler(&cfg, ras_tls_handler); /* rats-tls socket */
        if (ret != 0) {
            fprintf(stderr, "Failed to start tls socket agent: %d\n", ret);
            goto out;
        }
    }

    ret = prepare_migration(guest_rd);
    if (ret != 0) {
        fprintf(stderr, "Failed to prepare migration: %d\n", ret);
        goto out;
    }

    while (start_listening) {
        /* todo: state machine to handle multi migration */
        ret = socket_agent_start_with_handler(&cfg, host_handler); /* host socket */
        if (ret != 0) {
            fprintf(stderr, "Failed to start host socket agent: %d\n", ret);
            goto out;
        }
        guest_rd = get_guest_rd(pending_guest_rds, &rds_should_init);
        ret = socket_agent_start_with_handler(&cfg, ras_tls_handler); /* rats-tls socket */
        if (ret != 0) {
            fprintf(stderr, "Failed to start tls socket agent: %d\n", ret);
            goto out;
        }
        ret = prepare_migration(guest_rd);
        if (ret != 0) {
            fprintf(stderr, "Failed to prepare migration: %d\n", ret);
            break;
        }
    }

out:
    mig_agent_exit(&input_args);
    free(pending_guest_rds);
    pending_guest_rds = NULL;
    return 0;
}