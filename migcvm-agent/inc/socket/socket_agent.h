/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef MIGCVM_SOCKET_AGENT_H
#define MIGCVM_SOCKET_AGENT_H
#include <stdint.h>
#include <sys/socket.h>
#include <linux/vm_sockets.h>

#define CLIENT_AGENT_PORT 9000
#define SERVER_AGENT_PORT 9001
#define MIGCVM_CID VMADDR_CID_ANY
#define MAX_PAYLOAD_SIZE 256

#define PAYLOAD_TYPE_NONE     0
#define PAYLOAD_TYPE_CHAR     1
#define PAYLOAD_TYPE_ULL      2
#define VSOCK_MSG_ACK     0xb
#pragma pack(push, 1)
typedef struct socket_payload {
    char            char_payload[MAX_PAYLOAD_SIZE];
    unsigned long long ull_payload;
} socket_payload_t;
typedef struct socket_msg {
    socket_payload_t payload;
    unsigned long long session_id;
    char            cmd[16];
    unsigned int    payload_type;
    unsigned int    payload_char_len;
    unsigned int    success;
} socket_msg_t;
#pragma pack(pop)

typedef struct {
    int agent_type;

    char *attester_type;
    char *verifier_type;
    char *tls_type;
    char *crypto_type;
    char *srv_ip;
    uint16_t port;
    char *digest_file;
    rats_tls_log_level_t log_level;
    bool mutual;
    bool provide_endorsements;
    bool use_firmware;
    bool dump_eventlog;
    char *ref_json_file;
    bool use_fde;
    char* rootfs_key_file;
    bool verify_platform_components;
    char* platform_ref_json_file;
    /* guest cvm info */
    unsigned long long guest_rd;
    unsigned long long msk[4]; /* encrypted msk */
    unsigned long long rand_iv[4];
    unsigned long long tag[2];
    bool success;
} mig_agent_args;

struct socket_agent_cfg {
    mig_agent_args  *args;
    unsigned long cid;
    unsigned long port;
    int      backlog;
};

int socket_agent_start(const struct socket_agent_cfg *cfg);

typedef void (*socket_msg_handler)(const struct socket_msg *msg, int conn_fd, mig_agent_args *args);

int socket_agent_start_with_handler(const struct socket_agent_cfg *cfg,
                                    socket_msg_handler handler);

void payload_encode_all(struct socket_msg *msg, socket_payload_t *in);
void payload_encode_char(struct socket_msg *msg, const char *in);
static void payload_encode_ull(struct socket_msg *msg, unsigned long long in);
void payload_decode_all(const struct socket_msg *msg, socket_payload_t *out);
void payload_decode_one_type(const struct socket_msg *msg, socket_payload_t *out);
int rats_tls_server_startup(mig_agent_args *args);
ssize_t readn(int fd, void *buf, size_t n);
ssize_t writen(int fd, const void *buf, size_t n);
#endif