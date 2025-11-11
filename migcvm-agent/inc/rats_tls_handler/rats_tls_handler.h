/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef RATS_TLS_HANDLER_H
#define RATS_TLS_HANDLER_H

extern uint8_t g_rim_ref[MAX_MEASUREMENT_SIZE];
extern size_t g_rim_ref_size;

int rats_tls_client_startup(mig_agent_args *args);
int rats_tls_server_startup(mig_agent_args *args);

#endif