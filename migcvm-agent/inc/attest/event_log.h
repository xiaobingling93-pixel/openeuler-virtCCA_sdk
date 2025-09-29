/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef EVENT_LOG_H
#define EVENT_LOG_H

#include <stdint.h>
#include "rem.h"
#include "binary_blob.h"
#include "hash_defs.h"
#include "utils.h"

/* SHA256 digest length (32 bytes) */
#define SHA256_DIGEST_LENGTH 32

/* Add hash algorithm definitions */
#define TPM_ALG_ERROR 0x0
#define TPM_ALG_RSA   0x1
#define TPM_ALG_SHA1  0x4
#define TPM_ALG_SHA256 0xB
#define TPM_ALG_SHA384 0xC
#define TPM_ALG_SHA512 0xD
#define TPM_ALG_ECDSA 0x18

/* Algorithm information structure */
typedef struct {
    uint16_t algoid;
    uint16_t digestsize;
} algorithm_info_t;

/* Event type definitions */
typedef enum {
    EV_PREBOOT_CERT = 0x0,
    EV_POST_CODE = 0x1,
    EV_UNUSED = 0x2,
    EV_NO_ACTION = 0x3,
    EV_SEPARATOR = 0x4,
    EV_ACTION = 0x5,
    EV_EVENT_TAG = 0x6,
    EV_S_CRTM_CONTENTS = 0x7,
    EV_S_CRTM_VERSION = 0x8,
    EV_CPU_MICROCODE = 0x9,
    EV_PLATFORM_CONFIG_FLAGS = 0xa,
    EV_TABLE_OF_DEVICES = 0xb,
    EV_COMPACT_HASH = 0xc,
    EV_IPL = 0xd,
    EV_IPL_PARTITION_DATA = 0xe,
    EV_NONHOST_CODE = 0xf,
    EV_NONHOST_CONFIG = 0x10,
    EV_NONHOST_INFO = 0x11,
    EV_OMIT_BOOT_DEVICE_EVENTS = 0x12,

    /* TCG EFI Platform Specification For TPM Family 1.1 or 1.2 */
    EV_EFI_EVENT_BASE = 0x80000000,
    EV_EFI_VARIABLE_DRIVER_CONFIG = EV_EFI_EVENT_BASE + 0x1,
    EV_EFI_VARIABLE_BOOT = EV_EFI_EVENT_BASE + 0x2,
    EV_EFI_BOOT_SERVICES_APPLICATION = EV_EFI_EVENT_BASE + 0x3,
    EV_EFI_BOOT_SERVICES_DRIVER = EV_EFI_EVENT_BASE + 0x4,
    EV_EFI_RUNTIME_SERVICES_DRIVER = EV_EFI_EVENT_BASE + 0x5,
    EV_EFI_GPT_EVENT = EV_EFI_EVENT_BASE + 0x6,
    EV_EFI_ACTION = EV_EFI_EVENT_BASE + 0x7,
    EV_EFI_PLATFORM_FIRMWARE_BLOB = EV_EFI_EVENT_BASE + 0x8,
    EV_EFI_HANDOFF_TABLES = EV_EFI_EVENT_BASE + 0x9,
    EV_EFI_VARIABLE_AUTHORITY = EV_EFI_EVENT_BASE + 0xe0
} event_type_t;

typedef struct {
    uint32_t rem_index;
    uint32_t event_type;
    uint32_t digest_count;
    uint16_t* alg_ids;  /* Algorithm ID for each digest */
    uint8_t* digests;   /* Data for all digests */
    uint32_t event_size;
    uint8_t* event;
    uint32_t algorithms_number;  /* Number of algorithms */
    algorithm_info_t* algorithms;  /* Array of algorithm information */
} event_log_entry_t;

typedef struct {
    binary_blob_t blob;
    size_t log_base;
    size_t log_length;
    rem_t rems[REM_COUNT];
} event_log_t;

/* Event log operation functions */
bool event_log_init(event_log_t* log, size_t base, size_t length);
bool event_log_process(event_log_t* log);
bool event_log_replay(event_log_t* log);
void event_log_dump(event_log_t* log);

/* Internal function declarations */
bool process_event_log_entry(event_log_t* log, size_t* pos, event_log_entry_t* entry);

#endif /* EVENT_LOG_H */