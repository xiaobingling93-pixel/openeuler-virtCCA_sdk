/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */

#ifndef TLS_CORE_H
#define TLS_CORE_H

#include <openssl/ssl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "tmi.h"

#define VIRTCCA_TLS_CONF_FLAGS_MUTUAL		 (1UL << 0)
#define VIRTCCA_TLS_CONF_FLAGS_SERVER		 (VIRTCCA_TLS_CONF_FLAGS_MUTUAL << 1)

typedef struct {
    char *cert_file;
    char *key_file;
    int verify_peer;
    unsigned long flags;
} tls_conf_t;

typedef struct tls_core_context_t {
    tls_conf_t config;
    SSL_CTX *ssl_ctx;
    SSL *ssl;
    unsigned long flags;
} tls_core_context_t;

typedef tls_core_context_t* virtcca_tls_handle;

typedef enum {
    TLS_ERR_OK = 0,
    TLS_ERR_INIT_FAILED,
    TLS_ERR_NEGOTIATE_FAILED,
    TLS_ERR_RECEIVE_FAILED,
    TLS_ERR_TRANSMIT_FAILED,
    TLS_ERR_CLEANUP_FAILED
} tls_err_t;

tls_err_t virtcca_tls_init(const tls_conf_t *conf, virtcca_tls_handle *handle);
tls_err_t virtcca_tls_negotiate(virtcca_tls_handle handle, int fd);
tls_err_t virtcca_tls_receive(virtcca_tls_handle handle, void *buf, size_t *buf_size);
tls_err_t virtcca_tls_transmit(virtcca_tls_handle handle, void *buf, size_t *buf_size);
tls_err_t virtcca_tls_cleanup(virtcca_tls_handle handle);
#endif  // TLS_CORE_H
