/* Copyright (c) 2021 Intel Corporation
 * Copyright (c) 2020-2021 Alibaba Cloud
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
#define _GNU_SOURCE
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <getopt.h>
#include <errno.h>
#include <unistd.h>
#include <pthread.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/random.h>
#include <sys/ioctl.h>
#include <rats-tls/api.h>
#include <rats-tls/log.h>
#include <rats-tls/claim.h>
#include <rats-tls/attester.h>
#include "utils.h"
#include "common.h"
#include "socket_agent.h"
#include "migcvm_tsi.h"
#include "host_server_ip.h"
#include "rats_tls_handler.h"
#include "attest/token_parse.h"

uint8_t g_rim_ref[MAX_MEASUREMENT_SIZE];
size_t g_rim_ref_size = MAX_MEASUREMENT_SIZE;

#define    MIG_TYPE_SERVER 1
#define    MIG_TYPE_CLIENT 2

rats_tls_log_level_t global_log_level = RATS_TLS_LOG_LEVEL_DEFAULT;

static int start_listening = 1;
pending_guest_rd_t *pending_guest_rds = NULL;
unsigned int vsock_cid;

#define CHECK_LENGHT_ASSIGN(src, max_len, dst) \
do { \
    if (strnlen(src, max_len) == max_len) { \
        printf("input param len too long.\n"); \
        return -1; \
    } \
    dst = src; \
} while(0)

static int safe_strdup(char **dest, const char *src)
{
    char *tmp = strdup(src);
    if (!tmp) {
        perror("strdup failed");
        return -1;
    }
    *dest = tmp;
    return 0;
}

static void mig_agent_exit(mig_agent_args *args)
{
    if (!args) {
        return;
    }
    if (args->srv_ip) {
        free(args->srv_ip);
        args->srv_ip = NULL;
    }
    if (args->attester_type) {
        free(args->attester_type);
        args->attester_type = NULL;
    }
    if (args->verifier_type) {
        free(args->verifier_type);
        args->verifier_type = NULL;
    }
    if (args->tls_type) {
        free(args->tls_type);
        args->tls_type = NULL;
    }
    if (args->crypto_type) {
        free(args->crypto_type);
        args->crypto_type = NULL;
    }
    if (args->digest_file) {
        free(args->digest_file);
        args->digest_file = NULL;
    }
    return;
}

static int mig_agent_init(mig_agent_args *args)
{
    if (!args) {
        return -1;
    }
    args->agent_type = 0;
    if (safe_strdup(&args->attester_type, "") != 0) {
        goto err;
    }
    if (safe_strdup(&args->verifier_type, "") != 0) {
        goto err;
    }
    if (safe_strdup(&args->tls_type, "openssl") != 0) {
        goto err;
    }
    if (safe_strdup(&args->crypto_type, "openssl") != 0) {
        goto err;
    }
    if (safe_strdup(&args->digest_file, "") != 0) {
        goto err;
    }

    args->port = MIGCVM_PORT;
    args->log_level = RATS_TLS_LOG_LEVEL_INFO;
    args->mutual = true;
    args->provide_endorsements = false;
    args->use_firmware = false;
    args->dump_eventlog = false;
    args->ref_json_file = NULL;
    args->use_fde = false;
    args->rootfs_key_file = NULL;
    args->verify_platform_components = false;
    args->platform_ref_json_file = NULL;

    return 0;

err:
    mig_agent_exit(args);
    return -1;
}

static void ras_tls_handler_client(const struct socket_msg *msg, int conn_fd, mig_agent_args *args)
{
    int ret = 0;
    /* socket structues */
    socket_payload_t payload;
    memset(&payload, 0, sizeof(socket_payload_t));
    socket_msg_t ack_msg;
    memset(&ack_msg, 0, sizeof(socket_msg_t));

    /* tsi context */
    char* host_srv_ip;
    virtcca_mig_info_t *migvm_info = NULL;
    migration_info_t *attest_info = NULL;
    pending_guest_rd_t *pending_list_buf = NULL;
    bool guest_rd_legal = false;

    tsi_ctx *virtcca_client_ctx = tsi_new_ctx();
    if (!virtcca_client_ctx) {
        ret = TSI_ERROR_STATE;
        goto out;
    }
    ret = mig_agent_init(args);
    if (!ret) {
        ack_msg.success = 1;
    } else {
        goto out;
    }

    /* now the host srv_ip rely qemu input, temp is not use */
    host_srv_ip = calloc(MAX_PAYLOAD_SIZE, 1);
    if (!host_srv_ip) {
        printf("[CLIENT] Failed to allocate host_srv_ip\n");
        ret = TSI_ERROR_STATE;
        goto out;
    }
    if (strcmp(msg->cmd, "START_CLIENT") == 0) {
        payload_decode_all(msg, &payload);
        if (msg->payload_char_len > 0) {
            strncpy(host_srv_ip, payload.char_payload, MAX_PAYLOAD_SIZE - 1);
        }
        args->guest_rd = payload.ull_payload;
        host_srv_ip[MAX_PAYLOAD_SIZE - 1] = '\0';
        printf("[CLIENT] Received START_CLIENT signal");
    } else {
        printf("[CLIENT] Unknown command from host: %s\n", msg->cmd);
        ret = TSI_ERROR_INPUT;
        goto out;
    }

    if (strcmp(args->srv_ip, "0.0.0.0") == 0 || args->guest_rd == 0) {
        ret = TSI_ERROR_INPUT;
        goto out;
    }

    migvm_info = (virtcca_mig_info_t *)malloc(sizeof(virtcca_mig_info_t));
    if (!migvm_info) {
        printf("[CLIENT] Failed to initialize migvm_info\n");
        ret = TSI_ERROR_STATE;
        goto out;
    }
    memset(migvm_info, 0, sizeof(virtcca_mig_info_t));
    migvm_info->guest_rd = args->guest_rd;
    attest_info = (migration_info_t *)malloc(sizeof(migration_info_t));
    if (!attest_info) {
        printf("[CLIENT] Failed to initialize attest_info\n");
        ret = TSI_ERROR_STATE;
        goto out;
    }
    memset(attest_info, 0, sizeof(migration_info_t));

    pending_list_buf = (pending_guest_rd_t *)malloc(sizeof(pending_guest_rd_t));
    if (!pending_list_buf) {
        printf("[CLIENT] Failed to initialize pending_list_buf\n");
        ret = TSI_ERROR_STATE;
        goto out;
    }
    memset(pending_list_buf, 0, sizeof(pending_guest_rd_t));

    attest_info->pending_guest_rds = pending_list_buf;
    ret = get_migration_binded_rds(virtcca_client_ctx, migvm_info, attest_info);
    if (ret == TSI_SUCCESS) {
        printf("[CLIENT] get_migration_binded_rds succeeded\n");
    } else {
        printf("[CLIENT] get_migration_binded_rds failed with error: 0x%08x\n", ret);
        goto out;
    }

    for (int i = 0; i < MAX_BIND_VM; i++) {
        if (pending_list_buf->guest_rd[i] == migvm_info->guest_rd) {
            guest_rd_legal = true;
        }
    }
    if (!guest_rd_legal) {
        printf("[CLIENT] guest rd is ilegal\n");
        ret = TSI_ERROR_STATE;
        goto out;
    }

    /* Get migration info and mask(get msk to dst) */
    ret = get_migration_info_and_mask(virtcca_client_ctx, migvm_info, attest_info);
    if (ret == TSI_SUCCESS) {
        printf("[CLIENT] get_migration_info succeeded\n");
    } else {
        printf("[CLIENT] get_migration_info failed with error: 0x%08x\n", ret);
        goto out;
    }
    memcpy(args->msk, attest_info->msk, sizeof(attest_info->msk));
    memcpy(args->tag, attest_info->tag, sizeof(attest_info->tag));
    memcpy(args->rand_iv, attest_info->rand_iv, sizeof(attest_info->rand_iv));
    printf("[CLIENT] peer IP: %s\n", args->srv_ip);
    ret = rats_tls_client_startup(args);
    if (ret != 0) {
        printf("[CLIENT] rats_tls_client_startup failed with error: %d\n", ret);
        goto out;
    }
    attest_info->slot_status = SLOT_IS_READY;
    attest_info->set_key = true;
    /* Set migration bind slot and mask : SLOT_IS_READY */
    ret = set_migration_bind_slot_and_mask(virtcca_client_ctx, migvm_info, attest_info);
    if (ret == TSI_SUCCESS) {
        printf("[CLIENT] set_migration_bind_slot_and_mask succeeded\n");
    } else {
        printf("[CLIENT] set_migration_bind_slot_and_mask failed with error: 0x%08x\n", ret);
    }

out:
    if (ret != TSI_SUCCESS) {
        ack_msg.success = 0;
    }
    strncpy(ack_msg.cmd, "START_CLIENT_ACK", sizeof(ack_msg.cmd));
    ack_msg.payload_type = VSOCK_MSG_ACK;
    ack_msg.session_id = msg->session_id;

    if (writen(conn_fd, &ack_msg, sizeof(ack_msg)) != sizeof(ack_msg)) {
        printf("[CLIENT] Failed to send ACK for START_CLIENT: %s\n", strerror(errno));
    } else {
        printf("[CLIENT] ACK sent successfully\n");
        shutdown(conn_fd, SHUT_WR);
        char tmp[8];
        readn(conn_fd, tmp, sizeof(tmp));
    }

    if (args) {
        args->guest_rd = 0;
        memset(args->msk, 0, sizeof(args->msk));
        memset(args->tag, 0, sizeof(args->tag));
        memset(args->rand_iv, 0, sizeof(args->rand_iv));
    }

    if (attest_info) {
        if (attest_info->pending_guest_rds) {
            free(attest_info->pending_guest_rds);
            attest_info->pending_guest_rds = NULL;
        }
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

    if (strcmp(msg->cmd, "START_SERVER") != 0) {
        printf("[SERVER] Unknown command from host: %s\n", msg->cmd);
        ack_msg.success = 0;
        goto out;
    }

    if (msg->payload_type != PAYLOAD_TYPE_ULL) {
        printf("[SERVER] Received host START_SERVER with no payload\n");
        ack_msg.success = 0;
        goto out;
    }

    payload_decode_one_type(msg, &payload);
    args->guest_rd = payload.ull_payload;
    printf("[SERVER] Server thread ready, listening on port: %d\n", args->port);
    printf("[SERVER] Starting RATS-TLS server...\n");

    /* rats-tls server startup */
    if (args->guest_rd == 0) {
        ack_msg.success = 0;
    }
    printf("[SERVER] server close\n");

out:
    strncpy(ack_msg.cmd, "START_SERVER_ACK", sizeof(ack_msg.cmd));
    ack_msg.payload_type = VSOCK_MSG_ACK;
    ack_msg.session_id = msg->session_id;
    if (writen(conn_fd, &ack_msg, sizeof(ack_msg)) != sizeof(ack_msg)) {
        ack_msg.success = 0;
        printf("[SERVER] Failed to send ACK for START_SERVER: %s\n", strerror(errno));
    } else {
        printf("[SERVER] ACK sent successfully\n");
        shutdown(conn_fd, SHUT_WR);
        char tmp[8];
        readn(conn_fd, tmp, sizeof(tmp));
    }

    if (ack_msg.success == 1) {
        rats_tls_server_startup(args);
    }
    return;
}

static void* server_thread_func(void* arg)
{
    printf("[SERVER] Server thread started\n");
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(0, &cpuset);
    if (pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset)) {
        perror("pthread_setaffinity_np");
        return NULL;
    }

    mig_agent_args* args = (mig_agent_args*)arg;
    if (mig_agent_init(args)) {
        printf("[SERVER] Error initialize mig-agent args...\n");
        return NULL;
    }

    struct socket_agent_cfg *socket_cfg_server = malloc(sizeof(*socket_cfg_server));
    if (!socket_cfg_server) return NULL;
    *socket_cfg_server = (struct socket_agent_cfg) {
        .args = args,
        .cid = vsock_cid,
        .port = SERVER_AGENT_PORT,
        .backlog = 128            /* the length of the listening queue */
    };
    printf("[SERVER] Initializing RATS-TLS server...\n");
    socket_agent_start_with_handler(socket_cfg_server, ras_tls_handler_server);
    free(socket_cfg_server);
    return NULL;
}

static void* client_thread_func(void* arg)
{
    printf("Client thread started\n");
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(0, &cpuset);
    if (pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset)) {
        perror("pthread_setaffinity_np");
        return NULL;
    }
    mig_agent_args* args = (mig_agent_args*)arg;
    struct socket_agent_cfg *socket_cfg_client = malloc(sizeof(*socket_cfg_client));
    if (!socket_cfg_client) return NULL;
    *socket_cfg_client = (struct socket_agent_cfg) {
        .args = args,
        .cid = vsock_cid,
        .port = CLIENT_AGENT_PORT,
        .backlog = 128            /* the length of the listening queue */
    };
    printf("[Client] Starting client socket agent...\n");
    socket_agent_start_with_handler(socket_cfg_client, ras_tls_handler_client);
    free(socket_cfg_client);
    return NULL;
}

static int init_rim_ref(const char *hex_str)
{
    if (hex_to_bytes((unsigned char *)hex_str, strlen(hex_str), g_rim_ref, &g_rim_ref_size) != 0) {
        printf("Failed to initialize g_rim_ref\n");
        return -1;
    }
    return 0;
}

/*
 * parse_input
 *  -c client_ip  : remote server ip
 *  -s server_ip  : local server ip
 *  -r rim_ref    : RIM hex
 *
 * default: client_ip = "127.0.0.1", server_ip = "127.0.0.1"
 */
static void parse_input(int argc, char* argv[],
                        char** client_ip_out,
                        char** server_ip_out)
{
    int opt;
    char *client_ip = NULL;
    char *server_ip = NULL;
    char *rim = NULL;
    bool rim_provided = false;

    /* try get default ip of server */
    server_ip = get_local_ipv4();
    if (!server_ip) {
        server_ip = strdup("127.0.0.1");
    }

    client_ip = strdup("127.0.0.1");
    if (!client_ip) {
        perror("strdup for client_ip");
        exit(EXIT_FAILURE);
    }

    if (!client_ip || !server_ip) {
        perror("strdup for default IP");
        exit(EXIT_FAILURE);
    }

    while ((opt = getopt(argc, argv, "c:s:r:")) != -1) {
        switch (opt) {
            case 'c':
                if (!optarg) {
                    fprintf(stderr, "Missing argument for -c\n");
                    goto cleanup_error;
                }
                free(client_ip);
                client_ip = strdup(optarg);
                if (!client_ip) {
                    perror("Failed to allocate memory for client_ip");
                    goto cleanup_error;
                }
                break;
            case 's':
                if (!optarg) {
                    fprintf(stderr, "Missing argument for -s\n");
                    goto cleanup_error;
                }
                free(server_ip);
                server_ip = strdup(optarg);
                if (!server_ip) {
                    perror("Failed to allocate memory for server_ip");
                    goto cleanup_error;
                }
                break;
            case 'r':
                if (!optarg) {
                    fprintf(stderr, "Missing argument for -r\n");
                    goto cleanup_error;
                }
                free(rim);
                rim = strdup(optarg);
                if (!rim) {
                    perror("Failed to allocate memory for RIM");
                    goto cleanup_error;
                }
                rim_provided = true;
                break;
            default:
                fprintf(stderr, "Usage: %s [-c client_ip] [-s server_ip] [-r rim_ref]\n",
                        argv[0]);
                goto cleanup_error;
        }
    }

    if (rim_provided) {
        if (init_rim_ref(rim)) {
            fprintf(stderr, "RIM init failed\n");
            goto cleanup_error;
        }
    }
    for (size_t k = 0; k < MAX_MEASUREMENT_SIZE; k++) {
        printf("%02x", g_rim_ref[k]);
    }
    /* If rim not provided, keep the existing g_rim_ref (extracted from token) */
    if (rim) {
        free(rim);
    }

    *client_ip_out = client_ip;
    *server_ip_out = server_ip;
    return;

cleanup_error:
    if (client_ip) {
        free(client_ip);
    }
    if (server_ip) {
        free(server_ip);
    }
    if (rim) {
        free(rim);
    }
    exit(EXIT_FAILURE);
}

static void rim_initialize(void)
{
    /* init migcvm token */
    tsi_ctx *ctx = tsi_new_ctx();
    unsigned char challenge[CHALLENGE_SIZE] = {-1};
    size_t challenge_len = CHALLENGE_SIZE;
    size_t token_len;
    unsigned char *token;
    int ret = 0;

    virtcca_attestation_evidence_t *virtcca_token = NULL;
    virtcca_token = (virtcca_attestation_evidence_t *)malloc(sizeof(virtcca_attestation_evidence_t));
    if (!virtcca_token) {
        printf("cannot malloc evidence buffer.\n");
    }
    token = virtcca_token->report + sizeof(token_len);
    token_len = REPORT_MAX_LENGTH - sizeof(token_len);
    ret = get_attestation_token(ctx, challenge, challenge_len, token, &token_len);
    if (ret != 0) {
        printf("failed to get attestation token (%d)\n", ret);
    } else {
        /* parse token and extract RIM */
        cca_token_t parsed_token = {0};
        uint64_t parse_status = parse_cca_attestation_token(&parsed_token, token, token_len);
        if (parse_status == VIRTCCA_SUCCESS) {
            /* copy RIM to g_rim_ref */
            if (parsed_token.cvm_token.rim.len <= MAX_MEASUREMENT_SIZE) {
                memcpy(g_rim_ref, parsed_token.cvm_token.rim.ptr, parsed_token.cvm_token.rim.len);
                g_rim_ref_size = parsed_token.cvm_token.rim.len;
                printf("[get_attestation_token] RIM extracted from token, size = %zu\n", g_rim_ref_size);
            } else {
                printf("[get_attestation_token] RIM too large, truncating\n");
                memcpy(g_rim_ref, parsed_token.cvm_token.rim.ptr, MAX_MEASUREMENT_SIZE);
                g_rim_ref_size = MAX_MEASUREMENT_SIZE;
            }
        } else {
            printf("[get_attestation_token] failed to parse token (status=%lu)\n", parse_status);
        }
    }

    tsi_free_ctx(ctx);
}

int main(int argc, char *argv[])
{
    int ret = 0;
    pthread_t server_thread, client_thread;
    char *client_ip = NULL;
    char *server_ip = NULL;
    int vsock_fd = -1;

    mig_agent_args *server_args = NULL;
    mig_agent_args *client_args = NULL;

    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(0, &cpuset);
    if (pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset)) {
        perror("pthread_setaffinity_np");
        return EXIT_FAILURE;
    }
    rim_initialize();
    parse_input(argc, argv, &client_ip, &server_ip);

    vsock_fd = open("/dev/vsock", O_RDWR);
    if (vsock_fd < 0) {
        perror("open /dev/vsock");
        ret = EXIT_FAILURE;
        goto cleanup;
    }

    if (ioctl(vsock_fd, IOCTL_VM_SOCKETS_GET_LOCAL_CID, &vsock_cid) < 0) {
        perror("IOCTL_VM_SOCKETS_GET_LOCAL_CID");
        ret = EXIT_FAILURE;
        goto cleanup;
    }

    server_args = calloc(1, sizeof(*server_args));
    if (!server_args) {
        perror("malloc server_args");
        ret = EXIT_FAILURE;
        goto cleanup;
    }

    client_args = calloc(1, sizeof(*client_args));
    if (!client_args) {
        perror("malloc client_args");
        ret = EXIT_FAILURE;
        goto cleanup;
    }

    server_args->srv_ip = strdup(server_ip);
    if (!server_args->srv_ip) {
        perror("strdup server_ip");
        ret = EXIT_FAILURE;
        goto cleanup;
    }

    client_args->srv_ip = strdup(client_ip);
    if (!client_args->srv_ip) {
        perror("strdup client_ip");
        ret = EXIT_FAILURE;
        goto cleanup;
    }

    printf("Starting server thread with listen IP: %s\n", server_args->srv_ip);
    printf("Starting client thread with peer IP:   %s\n", client_args->srv_ip);

    if (pthread_create(&server_thread, NULL, server_thread_func, server_args) != 0) {
        perror("pthread_create server");
        ret = -1;
        goto cleanup;
    }

    if (pthread_create(&client_thread, NULL, client_thread_func, client_args) != 0) {
        perror("pthread_create client");
        pthread_join(server_thread, NULL);
        ret = -1;
        goto cleanup;
    }

    pthread_join(server_thread, NULL);
    pthread_join(client_thread, NULL);

cleanup:
    if (server_args) {
        mig_agent_exit(server_args);
        free(server_args);
    }
    if (client_args) {
        mig_agent_exit(client_args);
        free(client_args);
    }

    free(client_ip);
    free(server_ip);

    if (vsock_fd >= 0) {
        close(vsock_fd);
    }

    return ret;
}