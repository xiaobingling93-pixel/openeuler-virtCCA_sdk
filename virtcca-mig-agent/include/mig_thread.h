/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */

#ifndef MIG_THREAD_H
#define MIG_THREAD_H

#include <stdlib.h>
#include <pthread.h>
#include <unistd.h>
#include <string.h>
#include <stdatomic.h>
#include <linux/types.h>

#include "tmi.h"
#include "tls_core.h"

#define MAX_MIG_THREADS 1

#define MIG_CA "/etc/virtcca-mig/ca.crt"
#define MIG_CERT "/etc/virtcca-mig/mig.crt"
#define MIG_KEY "/etc/virtcca-mig/mig.key"
#define DEFAULT_PORT 4433
#define MIG_KEY_MASK_LEN 32
#define MIG_KEY_RAND_IV_LEN 32
#define MIG_KEY_TAG_LEN 16
#define BYTES_PER_ULL 8

typedef enum {
    THREAD_INACTIVE,
    THREAD_ACTIVE
} thread_status_t;

struct mig_thread {
    pthread_t  thread;
    struct virtcca_mig_agent_notify_info mig_info;
    thread_status_t status;
};

struct mig_prover_thread_args {
    pthread_t           *thread;
    virtcca_tls_handle  handle;
    int                 *client_fd;
    thread_status_t     status;
};

struct input_params {
    char        *client_ip;
    char        *server_ip;
    int         cpu_start;
    int         cpu_end;
};

struct mig_thread_args {
    char        *ip;
    uint16_t    port;
    int    cpu_start;
    int    cpu_end;
};

struct mig_host_key_info {
    uint8_t msk[MIG_KEY_MASK_LEN];
    uint8_t rand_iv[MIG_KEY_RAND_IV_LEN];
    uint8_t tag[MIG_KEY_TAG_LEN];
};

/* used for mig agent forwarding data between the secure and non-secure worlds. */
struct virtcca_mig_host_agent_info {
    uint64_t      rd;
    void          *content;
    unsigned long size;
};

void *virtcca_mig_client_thread_func(void *arg);
void *virtcca_mig_server_thread_func(void *arg);

#endif