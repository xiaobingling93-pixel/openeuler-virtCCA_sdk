/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef IMA_MEASURE_H
#define IMA_MEASURE_H

#include <limits.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

#define TCG_EVENT_NAME_LEN_MAX    255
#define IMA_TEMPLATE_FIELD_ID_MAX_LEN    16
#define IMA_TEMPLATE_NUM_FIELDS_MAX    15
#define CRYPTO_MAX_ALG_NAME 64
#define IMA_MAX_HASH_SIZE 64
#define MAX_CMD_LEN 1024
#define IMA_TEMPLATE_DATA_MAX_LEN (IMA_MAX_HASH_SIZE + PATH_MAX)
#define OPENSSL_1_1_0 0x10100000L

#define IMA_TEMPLATE_IMA_NAME "ima"
#define IMA_TEMPLATE_IMA_FMT "d|n"

#define ARRAY_SIZE(arr) (sizeof(arr) / sizeof(arr[0]))

#define ERROR_ENTRY_PARSING 1
#define ERROR_FIELD_NOT_FOUND 2

/* server */
#define MIGCVM_PORT 1234
#define DEFAULT_IP   "0.0.0.0" /* Listern to connections from any ip */
#define TOKEN "ATTESTATION_PASS"
#define REQUEST_IMA_LOG "REQUEST_IMA_LOG"
#define SERVER_IMA_MEASUREMENTS_PATH "/sys/kernel/security/ima/binary_runtime_measurements"
#define CLIENT_IMA_MEASUREMENTS_PATH "binary_runtime_measurements"
#define IMA_READ_BLCOK_SIZE 1024
#define ENABLE_FDE_TOKEN "ENABLE_FDE_TOKEN"
#define MAX_PASSWD_LEN 32
#define MAX 4096
#define SERVER_CCEL_ACPI_TABLE_PATH "/sys/firmware/acpi/tables/CCEL"
#define SERVER_CCEL_EVENT_LOG_PATH "/sys/firmware/acpi/tables/data/CCEL"
#define KEY_FILE_PATH "/root/rootfs_key.bin"

/* client */
#define SHA256_SIZE 32
#define SHA512_SIZE 64
#define MAX_MEASUREMENT_SIZE SHA512_SIZE
#define MAX_IMA_LOG_SIZE (1024 * 1024 * 1024)
#define MAX_LOG 0x200000 /* 2MB */
#define CLIENT_CCEL_ACPI_TABLE_PATH "./ccel.bin"
#define CLIENT_CCEL_EVENT_LOG_PATH "./event_log.bin"
#define HASH_STR_LENGTH 64

int ima_measure(const void *reference_pcr_value, size_t reference_pcr_value_len,
                char *digest_list_file, int validate, int verify, int target_pcr_index);

#endif