/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef INTEGRITY_CHECK_H
#define INTEGRITY_CHECK_H

#include "rats-tls/log.h"

typedef struct {
    unsigned long guest_rd;
    int socket_fd;
    int connd_fd;
    bool is_server;
    rats_tls_handle *handle;
} integrity_socket_t;

void* io_thread(void* arg);
#endif