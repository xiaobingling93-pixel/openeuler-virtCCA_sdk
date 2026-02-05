/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */

#ifndef INTEGRITY_CHECK_H
#define INTEGRITY_CHECK_H

#include <stdbool.h>
#include "tls_core.h"

#define SLAVE_THREAD_NUM    15
#define IO_THREAD_NUM       ((SLAVE_THREAD_NUM) + 1)

typedef struct {
    unsigned long guest_rd;
    int socket_fd;
    int connd_fd;
    uint16_t cpu_start;
    uint16_t cpu_end;
    bool is_server;
    virtcca_tls_handle *handle;
} integrity_socket_t;

int set_affinity(int cpu_start, int cpu_end);
void* io_thread(void* arg);
#endif