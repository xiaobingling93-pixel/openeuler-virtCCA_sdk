/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <errno.h>
#include <linux/vm_sockets.h>
#include <rats-tls/log.h>
#include <pthread.h>

#include "socket_agent.h"
#include "migcvm_tsi.h"

static int start_listening = 1;

ssize_t readn(int fd, void *buf, size_t n)
{
    if (!buf || n == 0) {
        return 0;
    }
    size_t left = n;
    char *p = buf;
    while (left > 0) {
        ssize_t r = read(fd, p, left);
        if (r < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("read");
            return -1;
        } else if (r == 0) {
            break;
        }
        left -= r;
        p += r;
    }
    return n - left;
}

ssize_t writen(int fd, const void *buf, size_t n)
{
    if (!buf || n == 0) {
        return 0;
    }
    size_t left = n;
    const char *p = buf;
    while (left > 0) {
        ssize_t r = write(fd, p, left);
        if (r < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("write");
            return -1;
        }
        left -= r;
        p += r;
    }
    return n;
}

static void default_msg_handler(const struct socket_msg *msg, int conn_fd)
{
    if (!msg) {
        fprintf(stderr, "default_msg_handler: msg is NULL\n");
        return;
    }
    printf("Received: cmd='%s', payload_type=%d, payload_char_len=%u\n",
           msg->cmd, msg->payload_type, msg->payload_char_len);
    const char *resp = "ACK";
    ssize_t written = writen(conn_fd, resp, strlen(resp) + 1);
    if (written < 0) {
        perror("Failed to send ACK (ignored)");
    }
}

static void calling_handler(const int listen_fd, socket_msg_handler handler,
                            mig_agent_args *args, const struct socket_agent_cfg *cfg)
{
    struct sockaddr_vm peer_sa = {0};
    socklen_t peer_len = sizeof(peer_sa);
    struct sockaddr_vm local_sa = {0};
    socklen_t local_len = sizeof(local_sa);
    struct socket_msg msg;
    memset(&msg, 0, sizeof(msg));

    if (!cfg) {
        fprintf(stderr, "calling_handler: cfg is NULL\n");
        return;
    }
    if (!args) {
        fprintf(stderr, "calling_handler: args is NULL\n");
        return;
    }

    int conn_fd = accept(listen_fd, (struct sockaddr *)&peer_sa, &peer_len);
    if (conn_fd < 0) {
        perror("accept failed");
        return;
    }
    if (getsockname(conn_fd, (struct sockaddr *)&local_sa, &local_len) == 0) {
        printf("Accepted: listener port=%u, local port=%u, "
               "peer cid=%u, peer port=%u\n",
               cfg->port, local_sa.svm_port,
               peer_sa.svm_cid, peer_sa.svm_port);
    } else {
        perror("getsockname failed");
        close(conn_fd);
        return;
    }

    ssize_t bytes_read = readn(conn_fd, &msg, sizeof(msg));
    if (bytes_read == sizeof(msg)) {
        if (handler) {
            printf("Handling message: cmd=%s, payload_type=%d\n",
                   msg.cmd, msg.payload_type);
            handler(&msg, conn_fd, args);
        } else {
            default_msg_handler(&msg, conn_fd);
        }
    } else if (bytes_read < 0) {
        printf("read failed: %s (errno=%d)\n", strerror(errno), errno);
    } else if (bytes_read == 0) {
        printf("Connection closed by client before sending data\n");
    } else {
        printf("Partial message received: %zd/%zu bytes\n", bytes_read, sizeof(msg));
    }
    printf("Closing connection (client cid=%u, port=%u)\n", peer_sa.svm_cid, peer_sa.svm_port);
    close(conn_fd);
}

int socket_agent_start_with_handler(const struct socket_agent_cfg *cfg,
                                    socket_msg_handler handler)
{
    int listen_fd;
    char error_message[256] = {0};

    if (!cfg) {
        fprintf(stderr, "socket_agent_start_with_handler: cfg is NULL\n");
        return TSI_ERROR_INPUT;
    }

    struct sockaddr_vm sa = {
        .svm_family = AF_VSOCK,
        .svm_cid = cfg->cid,
        .svm_port = cfg->port
    };

    /* create socket */
    listen_fd = socket(AF_VSOCK, SOCK_STREAM, 0);
    if (listen_fd < 0) {
        perror("socket creation failed");
        return TSI_ERROR_STATE;
    }

    /* allow reuse of local addresses */
    int opt = 1;
    if (setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) != 0) {
        perror("setsockopt failed");
        close(listen_fd);
        return TSI_ERROR_STATE;
    }

    printf("Trying to bind: CID=%u, Port=%d\n", sa.svm_cid, sa.svm_port);
    if (bind(listen_fd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        fprintf(stderr, "bind failed: %s (errno=%d)\n", strerror(errno), errno);
        close(listen_fd);
        return TSI_ERROR_INPUT;
    }

    printf("Successfully bound to port %d\n", sa.svm_port);
    if (listen(listen_fd, cfg->backlog) < 0) {
        strerror_r(errno, error_message, sizeof(error_message));
        fprintf(stderr, "listen failed: %s (errno=%d)\n", error_message, errno);
        close(listen_fd);
        return TSI_ERROR_STATE;
    }

    while (start_listening) {
        printf("Listening for VSOCK connections on port %d...\n", sa.svm_port);
        calling_handler(listen_fd, handler, cfg->args, cfg);
    }
    close(listen_fd);
    return TSI_SUCCESS;
}

void payload_encode_all(struct socket_msg *msg, socket_payload_t *in)
{
    if (!msg || !in) {
        return;
    }
    msg->payload_type = PAYLOAD_TYPE_NONE;
    strncpy(msg->payload.char_payload, in->char_payload, MAX_PAYLOAD_SIZE - 1);
    msg->payload.char_payload[MAX_PAYLOAD_SIZE - 1] = '\0';

    msg->payload.ull_payload = in->ull_payload;
    msg->payload_char_len = strnlen(in->char_payload, MAX_PAYLOAD_SIZE - 1) + 1;
}

void payload_encode_char(struct socket_msg *msg, const char *in)
{
    if (!msg || !in) {
        return;
    }
    msg->payload_type = PAYLOAD_TYPE_CHAR;
    strncpy(msg->payload.char_payload, in, MAX_PAYLOAD_SIZE - 1);
    msg->payload.char_payload[MAX_PAYLOAD_SIZE - 1] = '\0';
    msg->payload_char_len = strnlen(in, MAX_PAYLOAD_SIZE - 1) + 1;
}

void payload_encode_ull(struct socket_msg *msg, unsigned long long in)
{
    if (!msg) {
        return;
    }
    msg->payload_type = PAYLOAD_TYPE_ULL;
    msg->payload.ull_payload = in;
}

void payload_decode_one_type(const struct socket_msg *msg, socket_payload_t *out)
{
    if (!msg || !out) {
        return;
    }

    if (msg->payload_type == PAYLOAD_TYPE_NONE) {
        return;
    }
    size_t copy_len = msg->payload_char_len;
    if (copy_len >= MAX_PAYLOAD_SIZE) {
        copy_len = MAX_PAYLOAD_SIZE - 1;
    }
    if (msg->payload_type == PAYLOAD_TYPE_CHAR) {
        strncpy(out->char_payload, msg->payload.char_payload, copy_len);
        out->char_payload[copy_len] = '\0';
    } else if (msg->payload_type == PAYLOAD_TYPE_ULL) {
        out->ull_payload = msg->payload.ull_payload;
    }
}

void payload_decode_all(const struct socket_msg *msg, socket_payload_t *out)
{
    if (!msg || !out) {
        return;
    }

    if (msg->payload_type != PAYLOAD_TYPE_NONE) {
        memset(out, 0, sizeof(*out));
    }
    size_t copy_len = msg->payload_char_len;
    if (copy_len >= MAX_PAYLOAD_SIZE) {
        copy_len = MAX_PAYLOAD_SIZE - 1;
    }
    strncpy(out->char_payload, msg->payload.char_payload, copy_len);
    out->char_payload[copy_len] = '\0';
    out->ull_payload = msg->payload.ull_payload;
}