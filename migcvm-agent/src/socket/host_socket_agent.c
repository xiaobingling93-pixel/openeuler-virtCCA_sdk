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

#include "socket_agent.h"

static int start_listening = 1;

static void default_msg_handler(const struct socket_msg *msg, int conn_fd)
{
    RTLS_INFO("Received: cmd='%s', payload_type=%d, payload_len=%u\n",
              msg->cmd, msg->payload_type, msg->payload_len);
    const char *resp = "ACK";
    if (write(conn_fd, resp, strlen(resp) + 1) == -1) {
        perror("Failed to send ACK (ignored)");
    }
}

static void calling_handler(const int listen_fd, socket_msg_handler handler,
                            mig_agent_args *args)
{
    int conn_fd = accept(listen_fd, NULL, NULL);
    if (conn_fd < 0) {
        perror("accept failed");
        return;
    }

    RTLS_INFO("New connection accepted\n");
    struct socket_msg msg;
    ssize_t bytes_read = read(conn_fd, &msg, sizeof(msg));
    if (bytes_read == sizeof(msg)) {
        if (handler) {
            RTLS_INFO("Handling message: cmd=%s, payload_type=%d\n",
                      msg.cmd, msg.payload_type);
            handler(&msg, conn_fd, args);
        }
    } else if (bytes_read < 0) {
        char error_message[256] = {0};
        strerror_r(errno, error_message, sizeof(error_message));
        RTLS_ERR("read failed: %s (errno=%d)\n", error_message, errno);
    } else if (bytes_read == 0) {
        RTLS_INFO("Connection closed by client\n");
    } else {
        RTLS_INFO("Partial message received: %zd/%zu bytes\n", bytes_read, sizeof(msg));
    }
    close(conn_fd);
}

int socket_agent_start_with_handler(const struct socket_agent_cfg *cfg,
                                    socket_msg_handler handler)
{
    int listen_fd;
    char error_message[256] = {0};
    struct sockaddr_vm sa = {
        .svm_family = AF_VSOCK,
        .svm_cid = cfg->cid,
        .svm_port = cfg->port
    };

    /* create socket */
    listen_fd = socket(AF_VSOCK, SOCK_STREAM, 0);
    if (listen_fd < 0) {
        perror("socket creation failed");
        return -1;
    }

    /* allow reuse of local addresses */
    int opt = 1;
    if (setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt))) {
        perror("setsockopt failed");
        close(listen_fd);
        return -1;
    }

    RTLS_INFO("Trying to bind: CID=%u, Port=%d\n", sa.svm_cid, sa.svm_port);
    if (bind(listen_fd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        strerror_r(errno, error_message, sizeof(error_message));
        RTLS_ERR("bind failed: %s (errno=%d)\n", error_message, errno);
        close(listen_fd);
        return -1;
    }

    RTLS_INFO("Successfully bound to port %d\n", sa.svm_port);
    if (listen(listen_fd, cfg->backlog) < 0) {
        strerror_r(errno, error_message, sizeof(error_message));
        RTLS_INFO("listen failed: %s (errno=%d)\n", error_message, errno);
        close(listen_fd);
        return -1;
    }

    RTLS_INFO("Listening for VSOCK connections on port %d...\n", sa.svm_port);
    calling_handler(listen_fd, handler, cfg->args);
    close(listen_fd);
    return 0;
}

static void payload_encode_char(struct socket_msg *msg, const char *in)
{
    msg->payload_type = PAYLOAD_TYPE_CHAR;
    strncpy(msg->payload.char_payload, in, MAX_PAYLOAD_SIZE);
    msg->payload_len = strlen(in) + 1;
}

static void payload_encode_ull(struct socket_msg *msg, unsigned long long in)
{
    msg->payload_type = PAYLOAD_TYPE_ULL;
    msg->payload.ull_payload = in;
    msg->payload_len = sizeof(unsigned long long);
}

void payload_decode(const struct socket_msg *msg, void *out)
{
    if (msg->payload_type == PAYLOAD_TYPE_CHAR) {
        strncpy((char *)out, msg->payload.char_payload, msg->payload_len);
    } else if (msg->payload_type == PAYLOAD_TYPE_ULL) {
        *(unsigned long long *)out = msg->payload.ull_payload;
    }
}