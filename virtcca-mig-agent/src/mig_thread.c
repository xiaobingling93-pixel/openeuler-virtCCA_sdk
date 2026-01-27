/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netinet/tcp.h>

#include "tmi.h"
#include "tls_core.h"
#include "mig_thread.h"
#include "integrity_check_handler.h"

int get_virtcca_mig_info(struct virtcca_mig_agent_notify_info *data, uint64_t *mig_count_p)
{
    int ret = 0;

    tmi_ctx *virtcca_client_ctx = tmi_new_ctx();
    if (!virtcca_client_ctx) {
        return -1;
    }

    ret = virtcca_tmi_ioctl(virtcca_client_ctx, VIRTCCA_TMI_GET_NOTIFY, 0, data, mig_count_p);
    if (ret != 0) {
        printf("Failed to call tmi ioctl: %d\n", ret);
        return ret;
    }

    *mig_count_p = *mig_count_p > MAX_MIG_THREADS ? MAX_MIG_THREADS : *mig_count_p;

    tmi_free_ctx(virtcca_client_ctx);
    return ret;
}

void *virtcca_mig_client_thread_func(void *arg)
{
    uint64_t    mig_count = 0;
    struct virtcca_mig_agent_notify_info *data = NULL;
    struct mig_client_thread_args *client_args = (struct mig_client_thread_args *)arg;

    integrity_socket_t *params = NULL;
    tls_conf_t conf = {
        .cert_file = CLIENT_CA,
        .key_file = CLIENT_KEY,
        .verify_peer = 0,
        .flags = 0
    };

    virtcca_tls_handle handle;
    if (virtcca_tls_init(&conf, &handle) != TLS_ERR_OK) {
        fprintf(stderr, "Failed to initialize TLS.\n");
        return NULL;
    }

    memset(g_mig_threads, 0, sizeof(g_mig_threads));
    data = calloc(MAX_MIG_THREADS, sizeof(struct virtcca_mig_agent_notify_info));
    if (!data) {
        printf("Failed to alloc memory\n");
        return NULL;
    }

    for (int i = 0; i < MAX_MIG_THREADS; i++) {
        g_mig_threads[i].status = THREAD_INACTIVE;
    }

    while (1) {
        mig_count = 0;

        if (get_virtcca_mig_info(data, &mig_count) == 0) {
            int i = 0;
            if (mig_count > 0)
                printf("Client: get %lu vm info\n", mig_count);
            while (i < mig_count) {
                printf("name = %s\ndst_ip=%s\nport=%u\nrd=0x%lx\nvmid=%u\n\n",
                    data[i].name, data[i].dst_ip, data[i].dst_port, data[i].rd, data[i].cvm_vmid);
                int sockfd = socket(AF_INET, SOCK_STREAM, 0);
                struct sockaddr_in server_addr = {0};
                server_addr.sin_family = AF_INET;
                server_addr.sin_port = htons(client_args->dst_port);
                server_addr.sin_addr.s_addr = inet_addr(client_args->dst_ip);

                printf("connect to %s\n", client_args->dst_ip);
                if (connect(sockfd, (struct sockaddr*)&server_addr, sizeof(server_addr)) < 0) {
                    perror("client connect failed");
                    return NULL;
                }

                if (virtcca_tls_negotiate(handle, sockfd) != TLS_ERR_OK) {
                    fprintf(stderr, "TLS negotiation failed.\n");
                    return NULL;
                }

                size_t len = strlen(data[i].name);
                tls_err_t ret = virtcca_tls_transmit(handle, (void *)data[i].name, &len);
                if (ret != TLS_ERR_OK || len != strlen(data[i].name)) {
                    printf("Failed to transmit %#x\n", ret);
                    return NULL;
                }
                params = (integrity_socket_t *)calloc(1, sizeof(integrity_socket_t));
                if (!params) {
                    printf("Failed to alloc memory\n");
                    return NULL;
                }

                params->guest_rd = data[i].rd;
                params->socket_fd = sockfd;
                params->handle = &handle;
                params->is_server = false;
                pthread_t tid;
                pthread_create(&tid, NULL, io_thread, params);
                pthread_detach(tid);

                i++;
            }
        }
        sleep(1);
    }

    if (data)
        free(data);

    return 0;
}

void *virtcca_mig_server_thread_func(void *arg)
{
    pthread_t *mig_prover_tid = NULL;
    int sockfd = -1;
    int connd = -1;

    virtcca_tls_handle handle;
    tls_conf_t conf = {
        .cert_file      = SERVER_CA,
        .key_file       = SERVER_KEY,
        .verify_peer    = 0,
        .flags          = VIRTCCA_TLS_CONF_FLAGS_SERVER
    };

    tmi_ctx *c = tmi_new_ctx();
    if (virtcca_tmi_ioctl(c, VIRTCCA_TMI_IOCTL_VERSION, 0, NULL, NULL) != 0) {
        printf("failed to use ioctl");
    }

    if (virtcca_tls_init(&conf, &handle) != TLS_ERR_OK) {
        fprintf(stderr, "Failed to initialize TLS.\n");
        return NULL;
    }

    sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        printf("Failed to call socket()\n");
        goto out;
    }

    int reuse = 1;
    if (setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, (const void *)&reuse, sizeof(int)) < 0) {
        printf("Failed to call setsockopt(SO_REUSEADDR)\n");
        goto out;
    }

    /* Set keepalive options */
    int flag = 1;
    int tcp_keepalive_time = 30;
    int tcp_keepalive_intvl = 10;
    int tcp_keepalive_probes = 5;
    if (setsockopt(sockfd, SOL_SOCKET, SO_KEEPALIVE, &flag, sizeof(flag)) < 0) {
        printf("Failed to call setsockopt(SO_KEEPALIVE)\n");
        goto out;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPIDLE, &tcp_keepalive_time,
                   sizeof(tcp_keepalive_time)) < 0) {
        printf("Failed to call setsockopt(TCP_KEEPIDLE)\n");
        goto out;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPINTVL, &tcp_keepalive_intvl,
                   sizeof(tcp_keepalive_intvl)) < 0) {
        printf("Failed to call setsockopt(TCP_KEEPINTVL)\n");
        goto out;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPCNT, &tcp_keepalive_probes,
                   sizeof(tcp_keepalive_probes)) < 0) {
        printf("Failed to call setsockopt(TCP_KEEPCNT)\n");
        goto out;
    }

    printf("set socket success.\n");
    struct sockaddr_in s_addr = {0};
    s_addr.sin_family = AF_INET;
    s_addr.sin_addr.s_addr = INADDR_ANY;
    s_addr.sin_port = htons(DEFAULT_PORT);

    /* Bind the server socket */
    if (bind(sockfd, (struct sockaddr *)&s_addr, sizeof(s_addr)) == -1) {
        printf("Failed to call bind()\n");
        goto out;
    }
    printf("bind socket success.\n");
    /* Listen for a new connection, allow 5 pending connections */
    if (listen(sockfd, 5) == -1) {
        printf("Failed to call listen()\n");
        goto out;
    }
    printf("TLS Server: Waiting for incoming connections...\n");

    while (1) {
        int client_fd = 0;
        char cvm_name[MAX_NAME_LENGTH];
        size_t len = sizeof(cvm_name);
        uint64_t rd;
        int ret;

        mig_prover_tid = calloc(1, sizeof(pthread_t));
        if (!mig_prover_tid) {
            perror("Malloc failed");
            continue;
        }

        client_fd = accept(sockfd, NULL, NULL);

        printf("TLS Server: connect success...\n");

        if (virtcca_tls_negotiate(handle, client_fd) != TLS_ERR_OK) {
            fprintf(stderr, "TLS negotiation failed.\n");
            return NULL;
        }

        ret = virtcca_tls_receive(handle, cvm_name, &len);
        if (ret != TLS_ERR_OK) {
            printf("Failed to receive %#x\n", ret);
            return NULL;
        }

        tmi_ctx *ctx = tmi_new_ctx();
        ret = virtcca_tmi_ioctl(ctx, VIRTCCA_GET_DSTVM_RD, 0, cvm_name, &rd);
        if (ret != 0) {
            printf("failed to get rd of cvm %s", cvm_name);
        }

        integrity_socket_t *params = (integrity_socket_t *)calloc(1, sizeof(integrity_socket_t));
        if (params) {
            params->guest_rd = rd;
            params->socket_fd = sockfd;
            params->connd_fd = client_fd;
            params->handle = &handle;
            params->is_server = true;
            pthread_t tid;
            pthread_create(&tid, NULL, io_thread, params);
            pthread_detach(tid);
        }
    }

out:
    if (connd >= 0) {
        close(connd);
        connd = -1;
    }
    if (sockfd >= 0) {
        shutdown(sockfd, SHUT_RDWR);
        close(sockfd);
        sockfd = -1;
    }

    if (handle) {
        tls_err_t cleanup_ret = virtcca_tls_cleanup(handle);
        if (cleanup_ret != TLS_ERR_OK)
            printf("Failed to cleanup virtcca-tls %#x\n", cleanup_ret);
    }
    return NULL;
}
