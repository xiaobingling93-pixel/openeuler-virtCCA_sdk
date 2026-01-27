/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */
 
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <openssl/rand.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#include "tls_core.h"
#include "mig_thread.h"

tls_err_t virtcca_tls_init(const tls_conf_t *conf, virtcca_tls_handle *handle)
{
    SSL_CTX *ssl_ctx = NULL;

    if (conf == NULL || handle == NULL) {
        return TLS_ERR_INIT_FAILED;
    }

    SSL_load_error_strings();
    OpenSSL_add_ssl_algorithms();

    if (conf->flags & VIRTCCA_TLS_CONF_FLAGS_SERVER)
        ssl_ctx = SSL_CTX_new(TLS_server_method());
    else
        ssl_ctx = SSL_CTX_new(TLS_client_method());
    if (!ssl_ctx) {
        return TLS_ERR_INIT_FAILED;
    }

    if (SSL_CTX_use_certificate_file(ssl_ctx, conf->cert_file, SSL_FILETYPE_PEM) <= 0) {
        SSL_CTX_free(ssl_ctx);
        return TLS_ERR_INIT_FAILED;
    }

    if (SSL_CTX_use_PrivateKey_file(ssl_ctx, conf->key_file, SSL_FILETYPE_PEM) <= 0) {
        SSL_CTX_free(ssl_ctx);
        return TLS_ERR_INIT_FAILED;
    }

    // Only enable peer verification if requested
    if (conf->verify_peer) {
        SSL_CTX_set_verify(ssl_ctx, SSL_VERIFY_PEER, NULL);
    }

    *handle = (virtcca_tls_handle)malloc(sizeof(tls_core_context_t));
    if (!*handle) {
        SSL_CTX_free(ssl_ctx);
        return TLS_ERR_INIT_FAILED;
    }

    (*handle)->config = *conf;
    (*handle)->ssl_ctx = ssl_ctx;
    printf("virtcca_tls_init success.\n");
    return TLS_ERR_OK;
}

tls_err_t virtcca_tls_negotiate(virtcca_tls_handle handle, int fd)
{
    int err;

    if (!handle || fd < 0) {
        return TLS_ERR_NEGOTIATE_FAILED;
    }

    handle->ssl = SSL_new(handle->ssl_ctx);
    if (!handle->ssl) {
        return TLS_ERR_NEGOTIATE_FAILED;
    }

    SSL_set_fd(handle->ssl, fd);

    if (handle->config.flags & VIRTCCA_TLS_CONF_FLAGS_SERVER) {
        printf("SSL_accept\n");
        err = SSL_accept(handle->ssl);
    } else {
        printf("SSL_connect\n");
        err = SSL_connect(handle->ssl);
    }

    if (err != 1) {
        SSL_free(handle->ssl);
        return TLS_ERR_NEGOTIATE_FAILED;
    }

    return TLS_ERR_OK;
}

tls_err_t virtcca_tls_receive(virtcca_tls_handle handle, void *buf, size_t *buf_size)
{
    if (!handle || !buf || !buf_size) {
        return TLS_ERR_RECEIVE_FAILED;
    }

    int len = SSL_read(handle->ssl, buf, (int)(*buf_size));
    if (len <= 0) {
        return TLS_ERR_RECEIVE_FAILED;
    }

    *buf_size = (size_t)len;
    return TLS_ERR_OK;
}

tls_err_t virtcca_tls_transmit(virtcca_tls_handle handle, void *buf, size_t *buf_size)
{
    if (!handle || !buf || !buf_size) {
        return TLS_ERR_TRANSMIT_FAILED;
    }

    int len = SSL_write(handle->ssl, buf, (int)(*buf_size));
    if (len <= 0) {
        return TLS_ERR_TRANSMIT_FAILED;
    }

    *buf_size = (size_t)len;
    return TLS_ERR_OK;
}

tls_err_t virtcca_tls_cleanup(virtcca_tls_handle handle)
{
    if (!handle) {
        return TLS_ERR_CLEANUP_FAILED;
    }

    SSL_free(handle->ssl);
    SSL_CTX_free(handle->ssl_ctx);
    free(handle);
    return TLS_ERR_OK;
}