/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef MIGCVM_SOCKET_AGENT_H
#define MIGCVM_SOCKET_AGENT_H
#include <stdint.h>
#include <linux/vm_sockets.h>

#define HOST_AGENT_PORT 9000
#define MIGCVM_CID VMADDR_CID_ANY
#define MAX_PAYLOAD_SIZE 256

#define PAYLOAD_TYPE_CHAR     0
#define PAYLOAD_TYPE_ULL      1
#pragma pack(push, 1)

struct socket_msg {
    char     cmd[16];
    unsigned int payload_type;
    unsigned int payload_len;
    union {
        char char_payload[MAX_PAYLOAD_SIZE];
        unsigned long long ull_payload;
    } payload;
};
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

void payload_encode(struct socket_msg *msg, const char *in);
void payload_decode(const struct socket_msg *msg, void *out);
#endif