/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netinet/tcp.h>

#include "tmi.h"
#include "tls_core.h"
#include "integrity_check_handler.h"
#include "mig_thread.h"

int get_virtcca_mig_info(struct virtcca_mig_agent_notify_info *data, int *mig_count_p)
{
    int ret = 0;

    tmi_ctx *virtcca_client_ctx = tmi_new_ctx();
    if (!virtcca_client_ctx) {
        return -1;
    }

    ret = virtcca_tmi_ioctl(virtcca_client_ctx, VIRTCCA_TMI_GET_NOTIFY, 0, data, (uint64_t *)mig_count_p);
    if (ret != 0) {
        printf("Failed get virtcca mig info, tmi ioctl error: %d\n", ret);
        return ret;
    }

    *mig_count_p = *mig_count_p > MAX_MIG_THREADS ? MAX_MIG_THREADS : *mig_count_p;

    if (*mig_count_p > 0)
        printf("Get %u vm info\n", *mig_count_p);

    tmi_free_ctx(virtcca_client_ctx);
    return ret;
}

int virtcca_transfer_mig_key(virtcca_tls_handle handle, uint64_t rd)
{
    unsigned long long migrate_key_package[10];
    struct mig_host_key_info key_info = {0};
    struct virtcca_mig_host_agent_info agent_info = {0};
    tmi_ctx *c;
    int ret;

    agent_info.rd = rd;
    agent_info.content = &key_info;
    agent_info.size = sizeof(struct mig_host_key_info);
    c = tmi_new_ctx();
    ret = virtcca_tmi_ioctl(c, VIRTCCA_GET_MIG_KEY, 0, &agent_info, NULL);
    if (ret != 0) {
        printf("Failed to cal tmi ioctl %d\n", ret);
        tmi_free_ctx(c);
        return ret;
    }

    tmi_free_ctx(c);

    memcpy(migrate_key_package, key_info.msk, sizeof(key_info.msk));
    memcpy(migrate_key_package + (MIG_KEY_MASK_LEN / BYTES_PER_ULL),
           key_info.rand_iv, sizeof(key_info.rand_iv));
    memcpy(migrate_key_package + ((MIG_KEY_MASK_LEN + MIG_KEY_RAND_IV_LEN) / BYTES_PER_ULL),
           key_info.tag, sizeof(key_info.tag));
    size_t len = sizeof(migrate_key_package);
    ret = virtcca_tls_transmit(handle, migrate_key_package, &len);
    if (ret != TLS_ERR_OK || len != sizeof(migrate_key_package)) {
        memset(migrate_key_package, 0, sizeof(migrate_key_package));
        printf("Failed to transmit %#x\n", ret);
        return ret;
    }

    return 0;
}

static int virtcca_receive_mig_key(virtcca_tls_handle handle, uint64_t rd)
{
    unsigned long long migrate_key_package[10];
    struct mig_host_key_info key_info = {0};
    struct virtcca_mig_host_agent_info agent_info = {0};
    tmi_ctx *c;
    int ret;

    size_t len = sizeof(migrate_key_package);
    ret = virtcca_tls_receive(handle, migrate_key_package, &len);
    if (ret != TLS_ERR_OK || len != sizeof(migrate_key_package)) {
        memset(migrate_key_package, 0, sizeof(migrate_key_package));
        printf("Failed to receive %#x\n", ret);
        return ret;
    }

    agent_info.rd = rd;
    agent_info.content = &key_info;
    agent_info.size = sizeof(struct mig_host_key_info);

    memcpy(key_info.msk, migrate_key_package, sizeof(key_info.msk));
    memcpy(key_info.rand_iv, migrate_key_package + (MIG_KEY_MASK_LEN / BYTES_PER_ULL),
           sizeof(key_info.rand_iv));
    memcpy(key_info.tag, migrate_key_package + ((MIG_KEY_MASK_LEN + MIG_KEY_RAND_IV_LEN) / BYTES_PER_ULL),
           sizeof(key_info.tag));

    c = tmi_new_ctx();
    ret = virtcca_tmi_ioctl(c, VIRTCCA_SET_MIG_KEY, 0, &agent_info, NULL);
    if (ret != 0) {
        printf("Failed to cal tmi ioctl, %d\n", ret);
        tmi_free_ctx(c);
        return ret;
    }
    tmi_free_ctx(c);

    return 0;
}

static int virtcca_mig_client(struct virtcca_mig_agent_notify_info *data, virtcca_tls_handle *handle,
                              struct mig_thread_args *client_args)
{
    int mig_count = 0;
    int ret = 0;
    int i = 0;
    integrity_socket_t *params = NULL;
    int io_thread_cpu_start = client_args->cpu_end + 1 - IO_THREAD_NUM;
    int io_thread_cpu_end = client_args->cpu_end;

    ret = get_virtcca_mig_info(data, &mig_count);
    if (ret == 0) {
        while (i < mig_count) {
            int sockfd = socket(AF_INET, SOCK_STREAM, 0);
            if (sockfd < 0) {
                perror("socket creation failed");
                return -1;
            }

            struct sockaddr_in server_addr = {0};
            server_addr.sin_family = AF_INET;
            server_addr.sin_port = htons(client_args->port);
            server_addr.sin_addr.s_addr = inet_addr(client_args->ip);

            printf("connect to %s\n", client_args->ip);
            if (connect(sockfd, (struct sockaddr*)&server_addr, sizeof(server_addr)) < 0) {
                perror("client connect failed");
                close(sockfd);
                return -1;
            }

            if (virtcca_tls_negotiate(*handle, sockfd) != TLS_ERR_OK) {
                fprintf(stderr, "TLS negotiation failed.\n");
                close(sockfd);
                return -1;
            }

            size_t len = strlen(data[i].name);
            tls_err_t ret = virtcca_tls_transmit(*handle, (void *)data[i].name, &len);
            if (ret != TLS_ERR_OK || len != strlen(data[i].name)) {
                printf("Failed to transmit %#x\n", ret);
                close(sockfd);
                return -1;
            }

            printf("transfer mig key!\n");
            ret = virtcca_transfer_mig_key(*handle, data[i].rd);
            if (ret != 0) {
                printf("Failed to transmit mig key\n");
                close(sockfd);
                return -1;
            }

            params = (integrity_socket_t *)calloc(1, sizeof(integrity_socket_t));
            if (!params) {
                printf("Failed to alloc memory\n");
                close(sockfd);
                return -1;
            }

            params->guest_rd = data[i].rd;
            params->socket_fd = sockfd;
            params->handle = handle;
            params->is_server = false;
            params->cpu_start = io_thread_cpu_start;
            params->cpu_end = io_thread_cpu_end;
            pthread_t tid;
            pthread_create(&tid, NULL, io_thread, params);
            pthread_detach(tid);

            i++;
        }
    } else {
        printf("Failed to run virtcca host mig agent, ret = %d\n", ret);
        exit(EXIT_FAILURE);
    }
    return 0;
}

void *virtcca_mig_client_thread_func(void *arg)
{
    int ret = 0;
    struct virtcca_mig_agent_notify_info *data = NULL;
    struct mig_thread_args *client_args = (struct mig_thread_args *)arg;
    virtcca_tls_handle handle;

    tls_conf_t conf = {
        .cert_file = MIG_CERT,
        .key_file = MIG_KEY,
        .ca_cert_file = MIG_CA,
        .verify_peer = 1,
        .flags = 0
    };

    if (client_args->cpu_end - client_args->cpu_start + 1 > IO_THREAD_NUM)
        set_affinity(client_args->cpu_start, client_args->cpu_end - IO_THREAD_NUM);

    if (virtcca_tls_init(&conf, &handle) != TLS_ERR_OK) {
        fprintf(stderr, "Failed to initialize TLS.\n");
        return NULL;
    }

    data = calloc(MAX_MIG_THREADS, sizeof(struct virtcca_mig_agent_notify_info));
    if (!data) {
        printf("Failed to alloc memory\n");
        virtcca_tls_cleanup(handle);
        return NULL;
    }

    while (1) {
        ret = virtcca_mig_client(data, &handle, client_args);
        if (ret < 0) {
            break;
        }
        sleep(1);
    }

    if (data)
        free(data);
    virtcca_tls_cleanup(handle);
    return 0;
}

void *virtcca_mig_server_thread_func(void *arg)
{
    struct mig_thread_args *server_args = (struct mig_thread_args *)arg;
    int sockfd = -1;
    int client_fd = -1;
    virtcca_tls_handle handle = NULL;
    int io_thread_cpu_start = server_args->cpu_end + 1 - IO_THREAD_NUM;
    int io_thread_cpu_end = server_args->cpu_end;

    if (server_args->cpu_end - server_args->cpu_start + 1 > IO_THREAD_NUM)
        set_affinity(server_args->cpu_start, server_args->cpu_end - IO_THREAD_NUM);

    sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        printf("Failed to call socket()\n");
        goto cleanup;
    }

    int reuse = 1;
    if (setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, (const void *)&reuse, sizeof(int)) < 0) {
        printf("Failed to call setsockopt(SO_REUSEADDR)\n");
        goto cleanup;
    }

    /* Set keepalive options */
    int flag = 1;
    int tcp_keepalive_time = 30;
    int tcp_keepalive_intvl = 10;
    int tcp_keepalive_probes = 5;
    if (setsockopt(sockfd, SOL_SOCKET, SO_KEEPALIVE, &flag, sizeof(flag)) < 0) {
        printf("Failed to call setsockopt(SO_KEEPALIVE)\n");
        goto cleanup;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPIDLE, &tcp_keepalive_time,
                   sizeof(tcp_keepalive_time)) < 0) {
        printf("Failed to call setsockopt(TCP_KEEPIDLE)\n");
        goto cleanup;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPINTVL, &tcp_keepalive_intvl,
                   sizeof(tcp_keepalive_intvl)) < 0) {
        printf("Failed to call setsockopt(TCP_KEEPINTVL)\n");
        goto cleanup;
    }
    if (setsockopt(sockfd, SOL_TCP, TCP_KEEPCNT, &tcp_keepalive_probes,
                   sizeof(tcp_keepalive_probes)) < 0) {
        printf("Failed to call setsockopt(TCP_KEEPCNT)\n");
        goto cleanup;
    }

    printf("set socket success.\n");
    struct sockaddr_in s_addr = {0};
    s_addr.sin_family = AF_INET;
    s_addr.sin_addr.s_addr = inet_addr(server_args->ip);
    s_addr.sin_port = htons(server_args->port);

    /* Bind the server socket */
    if (bind(sockfd, (struct sockaddr *)&s_addr, sizeof(s_addr)) == -1) {
        printf("Failed to call bind()\n");
        goto cleanup;
    }
    printf("bind socket success.\n");
    /* Listen for a new connection, allow 5 pending connections */
    if (listen(sockfd, 5) == -1) {
        printf("Failed to call listen()\n");
        goto cleanup;
    }
    printf("TLS Server: Waiting for incoming connections...\n");

    while (1) {
        char cvm_name[MAX_NAME_LENGTH];
        size_t len = sizeof(cvm_name);
        uint64_t rd;
        int ret;
        struct sockaddr_in client_addr;
        socklen_t client_len = sizeof(client_addr);

        client_fd = accept(sockfd, (struct sockaddr *)&client_addr, &client_len);
        if (client_fd < 0) {
            perror("Failed to accept connection");
            break;
        }
        printf("TLS Server: New conn from %s:%d\n",
            inet_ntoa(client_addr.sin_addr), ntohs(client_addr.sin_port));

        tls_conf_t conf = {
            .cert_file      = MIG_CERT,
            .key_file       = MIG_KEY,
            .ca_cert_file   = MIG_CA,
            .verify_peer    = 1,
            .flags          = VIRTCCA_TLS_CONF_FLAGS_SERVER
        };

        if (virtcca_tls_init(&conf, &handle) != TLS_ERR_OK) {
            fprintf(stderr, "Failed to initialize TLS.\n");
            break;
        }

        printf("TLS Server: TLS initialized, starting negotiation...\n");

        if (virtcca_tls_negotiate(handle, client_fd) != TLS_ERR_OK) {
            fprintf(stderr, "TLS negotiation failed.\n");
            break;
        }
        printf("TLS Server: TLS negotiate successful\n");

        ret = virtcca_tls_receive(handle, cvm_name, &len);
        if (ret != TLS_ERR_OK) {
            printf("Failed to receive %#x\n", ret);
            break;
        }

        tmi_ctx *c = tmi_new_ctx();
        ret = virtcca_tmi_ioctl(c, VIRTCCA_GET_DSTVM_RD, 0, cvm_name, &rd);
        if (ret != 0) {
            printf("failed to get rd of cvm %s\n", cvm_name);
            break;
        }
        tmi_free_ctx(c);
        printf("receive mig key!\n");
        ret = virtcca_receive_mig_key(handle, rd);
        if (ret != 0) {
            printf("Failed to receive mig key\n");
            close(sockfd);
            break;
        }

        integrity_socket_t *params = (integrity_socket_t *)calloc(1, sizeof(integrity_socket_t));
        if (!params) {
            printf("failed to allocate params");
            break;
        }

        params->guest_rd = rd;
        params->socket_fd = sockfd;
        params->connd_fd = client_fd;
        params->handle = &handle;
        params->is_server = true;
        params->cpu_start = io_thread_cpu_start;
        params->cpu_end = io_thread_cpu_end;
        pthread_t tid;
        pthread_create(&tid, NULL, io_thread, params);
        pthread_detach(tid);
    }

cleanup:
    if (client_fd > 0) {
        close(client_fd);
    }
    if (sockfd >= 0) {
        shutdown(sockfd, SHUT_RDWR);
        close(sockfd);
    }
    virtcca_tls_cleanup(handle);

    return NULL;
}
