/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#include "config.h"

#define CCEL_ACPI_TABLE_PATH "./ccel.bin"
#define CCEL_EVENT_LOG_PATH "./event_log.bin"

/* Global configuration variable definition */
config_t g_config = {
    .ccel_file = CCEL_ACPI_TABLE_PATH,
    .event_log_file = CCEL_EVENT_LOG_PATH,
    .json_file = NULL  /* Will be set from command line */
}; 