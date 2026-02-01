/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */

#ifndef MIG_THREAD_H
#define MIG_THREAD_H

#include <stdlib.h>
#include <pthread.h>
#include <unistd.h>
#include <linux/types.h>
#include <string.h>
#include <stdatomic.h>

#include "tmi.h"
#include "tls_core.h"

#define MAX_MIG_THREADS 1

#define MIG_CA "/etc/virtcca-mig/ca.crt"
#define MIG_CERT "/etc/virtcca-mig/mig.crt"
#define MIG_KEY "/etc/virtcca-mig/mig.key"
#define DEFAULT_PORT 4433

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

int create_mig_thread(struct virtcca_mig_agent_notify_info *data, void *(*start_routine) (void *));
int get_active_thread_by_vmid(uint16_t	cvm_vmid);
int destroy_mig_thread_by_index(int index);

void *virtcca_mig_client_thread_func(void *arg);
void *virtcca_mig_server_thread_func(void *arg);

#endif