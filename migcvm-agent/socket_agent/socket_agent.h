/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef MIGCVM_SOCKET_AGENT_H
#define MIGCVM_SOCKET_AGENT_H
#include <stdint.h>

#pragma pack(push, 1)

struct SocketMsg {
    char     cmd[16];
    unsigned long long payload;
};
#pragma pack(pop)

struct SocketAgentCfg {
    unsigned long cid;
    unsigned long port;
    int      backlog;
};

int SocketAgentStart(const struct SocketAgentCfg *cfg);

typedef void (*SocketMsgHandler)(const struct SocketMsg *msg, int connFd);

int SocketAgentStartWithHandler(const struct SocketAgentCfg *cfg,
                                SocketMsgHandler handler);
#endif