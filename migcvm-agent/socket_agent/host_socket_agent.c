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

#include "socket_agent.h"

static void DefaultMsgHandler(const struct SocketMsg *msg, int connFd)
{
    printf("Received: cmd='%s', payload=%llu\n",
           msg->cmd, (unsigned long long)msg->payload);
    const char *resp = "ACK";
    if (write(connFd, resp, strlen(resp) + 1) == -1) {
        perror("Failed to send ACK (ignored)");
    }
}

int SocketAgentStart(const struct SocketAgentCfg *cfg)
{
    return SocketAgentStartWithHandler(cfg, DefaultMsgHandler);
}

static void CallingHandler(const int listenFd, SocketMsgHandler handler)
{
    while (1) {
        int connFd = accept(listenFd, NULL, NULL);
        if (connFd < 0) {
            perror("accept failed");
            continue;
        }
        printf("New connection accepted\n");

        struct SocketMsg msg;
        ssize_t bytesRead = read(connFd, &msg, sizeof(msg));
        if (bytesRead == sizeof(msg)) {
            if (handler) {
                printf("Handling message: cmd='%s', payload=%llu\n",
                       msg.cmd, (unsigned long long)msg.payload);
                handler(&msg, connFd);
            }
        } else if (bytesRead < 0) {
            char errorMessage[256] = {0};
            strerror_r(errno, errorMessage, sizeof(errorMessage));
            printf("read failed: %s (errno=%d)\n", errorMessage, errno);
        } else if (bytesRead == 0) {
            printf("Connection closed by client\n");
        } else {
            printf("Partial message received: %zd/%zu bytes\n", bytesRead, sizeof(msg));
        }
        close(connFd);
    }
}

int SocketAgentStartWithHandler(const struct SocketAgentCfg *cfg,
                                SocketMsgHandler handler)
{
    int listenFd;
    char errorMessage[256] = {0};
    struct sockaddr_vm sa = {
        .svm_family = AF_VSOCK,
        .svm_cid = cfg->cid,
        .svm_port = cfg->port
    };

    /* create socket */
    listenFd = socket(AF_VSOCK, SOCK_STREAM, 0);
    if (listenFd < 0) {
        perror("socket creation failed");
        return -1;
    }

    /* allow reuse of local addresses */
    int opt = 1;
    if (setsockopt(listenFd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt))) {
        perror("setsockopt failed");
        close(listenFd);
        return -1;
    }

    printf("Trying to bind: CID=%u, Port=%d\n", sa.svm_cid, sa.svm_port);
    if (bind(listenFd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        strerror_r(errno, errorMessage, sizeof(errorMessage));
        printf("bind failed: %s (errno=%d)\n", errorMessage, errno);
        close(listenFd);
        return -1;
    }

    printf("Successfully bound to port %d\n", sa.svm_port);
    if (listen(listenFd, cfg->backlog) < 0) {
        strerror_r(errno, errorMessage, sizeof(errorMessage));
        printf("listen failed: %s (errno=%d)\n", errorMessage, errno);
        close(listenFd);
        return -1;
    }

    printf("Listening for VSOCK connections on port %d...\n", sa.svm_port);
    CallingHandler(listenFd, handler);
    close(listenFd);
    return 0;
}