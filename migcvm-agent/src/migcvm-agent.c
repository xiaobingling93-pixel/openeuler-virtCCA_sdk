/* Copyright (c) 2021 Intel Corporation
 * Copyright (c) 2020-2021 Alibaba Cloud
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <getopt.h>
#include <errno.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/socket.h>
#include <rats-tls/api.h>
#include <rats-tls/log.h>
#include <rats-tls/claim.h>
#include "utils.h"
#include "common.h"
#include "socket_agent.h"
#include "migcvm_tsi.h"
#include "rats_tls_handler.h"

uint8_t g_rim_ref[MAX_MEASUREMENT_SIZE];
size_t g_rim_ref_size = MAX_MEASUREMENT_SIZE;

#define    MIG_TYPE_SERVER 1
#define    MIG_TYPE_CLIENT 2

rats_tls_log_level_t global_log_level = RATS_TLS_LOG_LEVEL_DEFAULT;

static int start_listening = 1;
pending_guest_rd_t *pending_guest_rds = NULL;

#define CHECK_LENGHT_ASSIGN(src, max_len, dst) \
do { \
    if (strnlen(src, max_len) == max_len) { \
        printf("input param len too long.\n"); \
        return -1; \
    } \
    dst = src; \
} while(0)

static int mig_agent_init(mig_agent_args *args)
{
    args->agent_type = 0;

    args->attester_type = strdup("");
    args->verifier_type = strdup("");
    args->tls_type = strdup("");
    args->crypto_type = strdup("");
    args->port = MIGCVM_PORT;
    args->digest_file = strdup("");
    args->log_level = RATS_TLS_LOG_LEVEL_INFO;
    args->mutual = false;
    args->provide_endorsements = false;
    args->use_firmware = false;
    args->dump_eventlog = false;
    args->ref_json_file = NULL;
    args->use_fde = false;
    args->rootfs_key_file = NULL;
    args->verify_platform_components = false;
    args->platform_ref_json_file = NULL;

    return 0;
}

static int mig_agent_exit(mig_agent_args *args)
{
    free(args->srv_ip);
    free(args->attester_type);
    free(args->verifier_type);
    free(args->tls_type);
    free(args->crypto_type);
    free(args->digest_file);
    return 0;
}

static void ras_tls_handler_client(const struct socket_msg *msg, int conn_fd, mig_agent_args *args)
{
    socket_payload_t payload;
    memset(&payload, 0, sizeof(socket_payload_t));
    socket_msg_t ack_msg;
    memset(&ack_msg, 0, sizeof(socket_msg_t));
    tsi_ctx *virtcca_client_ctx = tsi_new_ctx();
    char* host_srv_ip;
    int ret = 0;

    virtcca_mig_info_t *migvm_info = NULL;
    migration_info_t *attest_info = NULL;
    mig_agent_init(args);
    ack_msg.success = 1;

    host_srv_ip = calloc(MAX_PAYLOAD_SIZE, 1);
    if (!host_srv_ip) {
        printf("Failed to allocate host_srv_ip\n");
        ret = TSI_ERROR_STATE;
        goto out;
    }
    if (strcmp(msg->cmd, "START_CLIENT") == 0) {
        payload_decode_all(msg, &payload);
        if (payload.payload_char_len > 0) {
            strncpy(host_srv_ip, payload.char_payload, MAX_PAYLOAD_SIZE - 1);
            host_srv_ip[MAX_PAYLOAD_SIZE - 1] = '\0';
        } else {
            host_srv_ip[0] = '\0';
        }
        args->guest_rd = payload.ull_payload;
        printf("Received host START_CLIENT with peer IP: %s\n", host_srv_ip);
        printf("Received host START_CLIENT with rd: %llx\n", args->guest_rd);
    } else {
        printf("Unknown command from host: %s\n", msg->cmd);
        ret = TSI_ERROR_INPUT;
        goto out;
    }
    printf("peer IP: %s\n", args->srv_ip);
    if (strcmp(args->srv_ip, "0.0.0.0") == 0 || args->guest_rd == 0) {
        ret = TSI_ERROR_INPUT;
        goto out;
    }
    printf("using guest_rd: 0x%llx\n", args->guest_rd);
    migvm_info = (virtcca_mig_info_t *)malloc(sizeof(virtcca_mig_info_t));
    if (!migvm_info) {
        printf("Failed to initialize migvm_info\n");
        ret = TSI_ERROR_STATE;
        goto out;
    }
    migvm_info->guest_rd = args->guest_rd;
    attest_info = (migration_info_t *)malloc(sizeof(migration_info_t));
    if (!attest_info) {
        printf("Failed to initialize attest_info\n");
        ret = TSI_ERROR_STATE;
        goto out;
    };
    attest_info->pending_guest_rds = NULL;

    /* Get migration info and mask(get msk to dst) */
    ret = get_migration_info_and_mask(virtcca_client_ctx, migvm_info, attest_info);
    if (ret == TSI_SUCCESS) {
        printf("get_migration_info succeeded\n");
    } else {
        printf("get_migration_info failed with error: 0x%08x\n", ret);
        goto out;
    }
    memcpy(args->msk, attest_info->msk, sizeof(attest_info->msk));
    ret = rats_tls_client_startup(args);
    if (ret != 0) {
        printf("rats_tls_client_startup failed with error: %d\n", ret);
        goto out;
    }
    attest_info->slot_status = SLOT_IS_READY;
    /* Set migration bind slot and mask : SLOT_IS_READY */
    ret = set_migration_bind_slot_and_mask(virtcca_client_ctx, migvm_info, attest_info);
    if (ret == TSI_SUCCESS) {
        printf("get_migration_info succeeded\n");
    } else {
        printf("get_migration_info failed with error: 0x%08x\n", ret);
        goto out;
    }

out:
    if (ret != TSI_SUCCESS) {
        ack_msg.success = 0;
    }
    strncpy(ack_msg.cmd, "START_CLIENT_ACK", sizeof(ack_msg.cmd));
    ack_msg.msg_type = VSOCK_MSG_ACK;
    ack_msg.session_id = msg->session_id;
    if (write(conn_fd, &ack_msg, sizeof(ack_msg)) != sizeof(ack_msg)) {
        printf("Failed to send ACK for START_CLIENT\n");
        close(conn_fd);
    }

    if (attest_info) {
        free(attest_info);
    }
    if (migvm_info) {
        free(migvm_info);
    }
    if (virtcca_client_ctx) {
        tsi_free_ctx(virtcca_client_ctx);
    }
    if (host_srv_ip) {
        free(host_srv_ip);
    }
    return;
}

static void ras_tls_handler_server(const struct socket_msg *msg, int conn_fd, mig_agent_args *args)
{
    socket_payload_t payload;
    memset(&payload, 0, sizeof(socket_payload_t));

    socket_msg_t ack_msg;
    memset(&ack_msg, 0, sizeof(socket_msg_t));
    ack_msg.success = 1;

    if (strcmp(msg->cmd, "START_SERVER") == 0) {
        if (msg->payload_type != PAYLOAD_TYPE_ULL) {
            printf("Received host START_SERVER with no payload\n");
            return;
        }
        payload_decode_one_type(msg, &payload);
        args->guest_rd = payload.ull_payload;
        printf("Received host START_CLIENT with rd: %d\n", args->guest_rd);

        /* rats-tls server startup */
        if (args->guest_rd == 0) {
            ack_msg.success = 0;
        }

        /* send ACK to host */
        strncpy(ack_msg.cmd, "START_SERVER_ACK", sizeof(ack_msg.cmd));
        ack_msg.msg_type = VSOCK_MSG_ACK;
        ack_msg.session_id = msg->session_id;
        if (write(conn_fd, &ack_msg, sizeof(ack_msg)) != sizeof(ack_msg)) {
            close(conn_fd);
            printf("Failed to send ACK for START_SERVER\n");
        }
        printf("Sent ACK for START_SERVER successfully\n");
        return;
    } else {
        printf("Unknown command from host: %s\n", msg->cmd);
        close(conn_fd);

        return;
    }
}

static int rats_tls_client_func(mig_agent_args* args)
{
    int ret = 0;
    struct socket_agent_cfg socket_cfg_client = {
        .args = args,
        .cid = MIGCVM_CID,
        .port = CLIENT_AGENT_PORT,
        .backlog = 5            /* the length of the listening queue */
    };

    printf("[Client] Starting client socket agent...\n");
    ret = socket_agent_start_with_handler(&socket_cfg_client, ras_tls_handler_client);
    printf("[Client] Rats-tls done...\n");

    return ret;
}

static int rats_tls_server_func(mig_agent_args* args)
{
    virtcca_mig_info_t *migvm_info = NULL;
    migration_info_t *attest_info = NULL;
    int ret = 0;
    // tsi_ctx *virtcca_server_ctx = tsi_new_ctx();
    char *srv_ip = strdup("0.0.0.0");
    mig_agent_init(args);
    args->srv_ip = srv_ip;

    struct socket_agent_cfg socket_cfg_server = {
        .args = args,
        .cid = MIGCVM_CID,
        .port = SERVER_AGENT_PORT,
        .backlog = 5            /* the length of the listening queue */
    };

    printf("[SERVER] Initializing RATS-TLS server...\n");
    ret = socket_agent_start_with_handler(&socket_cfg_server, ras_tls_handler_server);
    if (ret) {
        goto out;
    }

    printf("[SERVER] Server thread ready, listening on port: %d\n", args->port);
    printf("[SERVER] Starting RATS-TLS server...\n");

    if (args->guest_rd == 0) {
        goto out;
    }
    printf("[SERVER] Using guest_rd: 0x%llx\n", args->guest_rd);
    // migvm_info = (virtcca_mig_info_t *)malloc(sizeof(virtcca_mig_info_t));
    // if (!migvm_info) {
    //     printf("Failed to initialize migvm_info\n");
    //     goto out;
    // }
    // migvm_info->guest_rd = args->guest_rd;
    // attest_info = (migration_info_t *)malloc(sizeof(migration_info_t));
    // if (!attest_info) {
    //     printf("Failed to initialize attest_info\n");
    //     goto out;
    // };
    // attest_info->pending_guest_rds = NULL;

    if (rats_tls_server_startup(args) != 0) {
        printf("[SERVER]Go out!!!!");
        goto out;
    }
    printf("[SERVER]server close");
    // rats_tls_server_startup(args);
    // printf("the msk is %llx\n", args->msk[0]);
    // printf("the msk is %llx\n", args->msk[1]);
    // printf("the msk is %llx\n", args->msk[2]);
    // printf("the msk is %llx\n", args->msk[3]);
    // attest_info->slot_status = SLOT_IS_READY;
    // memcpy(attest_info->msk, args->msk, sizeof(attest_info->msk));

    // /* SET MSK into TMM*/
    // ret = set_migration_bind_slot_and_mask(virtcca_server_ctx, migvm_info, attest_info);
    // if (ret == TSI_SUCCESS) {
    //     printf("get_migration_info succeeded\n");
    // } else {
    //     printf("get_migration_info failed with error: 0x%08x\n", ret);
    // }

out:
    if (attest_info) {
        free(attest_info);
    }
    if (migvm_info) {
        free(migvm_info);
    }
    // if (virtcca_server_ctx) {
    //     tsi_free_ctx(virtcca_server_ctx);
    // }
    return ret;
}

static void init_rim_ref(const char *hex_str)
{
    if (hex_to_bytes((unsigned char *)hex_str, strlen(hex_str), g_rim_ref, &g_rim_ref_size) != 0) {
        printf("Failed to initialize g_rim_ref\n");
    }
}

static void* server_thread_func(void* arg)
{
    printf("Server thread started\n");
    mig_agent_args* args = (mig_agent_args*)arg;
    rats_tls_server_func(args);
    return NULL;
}

static void* client_thread_func(void* arg)
{
    printf("Client thread started\n");
    mig_agent_args* args = (mig_agent_args*)arg;
    rats_tls_client_func(args);
    return NULL;
}

static char* parse_input(int argc, char* argv[], const char* default_ip, const char* default_rim)
{
    int opt;
    char* ip = NULL;
    char* rim = NULL;

    if (default_ip != NULL) {
        ip = strdup(default_ip);
    } else {
        ip = strdup("0.0.0.0");
    }
    if (ip == NULL) {
        perror("Failed to allocate memory for IP");
        exit(EXIT_FAILURE);
    }

    if (default_rim != NULL) {
        rim = strdup(default_rim);
    } else {
        rim = strdup("cd0e1a1ae54ebbbbdb7793af0f2abac3f4aa148aeedebb071e8d5c27e46b4ba6");
    }
    if (rim == NULL) {
        perror("Failed to allocate memory for RIM");
        free(ip);
        exit(EXIT_FAILURE);
    }

    while ((opt = getopt(argc, argv, "i:r:")) != -1) {
        switch (opt) {
            case 'i':
                free(ip);
                ip = strdup(optarg);
                if (ip == NULL) {
                    perror("Failed to allocate memory for IP");
                    exit(EXIT_FAILURE);
                }
                break;
            case 'r':
                free(rim);
                rim = strdup(optarg);
                if (rim == NULL) {
                    perror("Failed to allocate memory for RIM");
                    free(ip);
                    exit(EXIT_FAILURE);
                }
                break;
            default:
                fprintf(stderr, "Usage: %s [-i server_ip] [-r rim_ref]\n", argv[0]);
                free(ip);
                free(rim);
                exit(EXIT_FAILURE);
        }
    }
    init_rim_ref(rim);
    free(rim);
    return ip;
}

int main(int argc, char *argv[])
{
    int ret = 0;
    pthread_t server_thread, client_thread;
    char* client_srv_ip = parse_input(argc, argv, "0.0.0.0", NULL);

    mig_agent_args* server_args = (mig_agent_args*)malloc(sizeof(mig_agent_args));
    if (server_args == NULL) {
        printf("Failed to allocate memory for server_args\n");
        exit(EXIT_FAILURE);
    }
    memset(server_args, 0, sizeof(mig_agent_args));

    mig_agent_args* client_args = (mig_agent_args*)malloc(sizeof(mig_agent_args));
    if (client_args == NULL) {
        printf("Failed to allocate memory for client_args\n");
        free(server_args);
        exit(EXIT_FAILURE);
    }
    memset(client_args, 0, sizeof(mig_agent_args));

    client_args->srv_ip = strdup(client_srv_ip);
    printf("Starting server and client threads with server IP: %s...\n", client_args->srv_ip);
    printf("Starting server and client threads...\n");

    if (pthread_create(&server_thread, NULL, server_thread_func, server_args) != 0) {
        perror("Failed to create server thread");
        return -1;
    }

    if (pthread_create(&client_thread, NULL, client_thread_func, client_args) != 0) {
        perror("Failed to create client thread");
        return -1;
    }

    pthread_join(server_thread, NULL);
    pthread_join(client_thread, NULL);

    free(server_args);
    free(client_args);
    free(client_srv_ip);

    return ret;
}
