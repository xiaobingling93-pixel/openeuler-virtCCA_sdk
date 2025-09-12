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

#define TARGET_PORT 9000
#define TARGET_CID 3
int main()
{
    int sockfd;
    struct sockaddr_vm sa = {
        .svm_family = AF_VSOCK,
        .svm_cid = TARGET_CID,
        .svm_port = TARGET_PORT
    };

    /* setup socket */
    sockfd = socket(AF_VSOCK, SOCK_STREAM, 0);
    if (sockfd < 0) {
        perror("socket creation failed");
        exit(EXIT_FAILURE);
    }

    /* connect server */
    if (connect(sockfd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        perror("connect failed");
        char errorMessage[256] = {0};
        strerror_r(errno, errorMessage, sizeof(errorMessage));
        printf("failed: %s (errno=%d)\n", errorMessage, errno);
        close(sockfd);
        exit(EXIT_FAILURE);
    }
    printf("Connected to VSOCK service at CID=%d, Port=%d\n", sa.svm_cid, sa.svm_port);

    /* send msg */
    const char *msg = "Hello from VSOCK client!";
    if (send(sockfd, msg, strlen(msg), 0) < 0) {
        perror("send failed");
        close(sockfd);
        exit(EXIT_FAILURE);
    }

    printf("Message sent: %s\n", msg);
    close(sockfd);
    return 0;
}

