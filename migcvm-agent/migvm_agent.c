/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "socket_agent/socket_agent.h"

#define MIGCVM_AGENT_PORT 9000
#define MIGCVM_CID 3

static void CustomHandler(const struct SocketMsg *msg, int connFd)
{
    printf("Custom handling: cmd=%s, payload=0x%llx\n",
           msg->cmd, msg->payload);
    /* todo: custom handling logic */
    /* multi-thread */
    const char *resp = "ACK";
    /* 1.send msg to dest migcvm */
    /* 2.DH channel setup */
    /* 3.get migration info */
    /* 4.exchange keys */
    /* 5.set_migration_bind_slot */
    write(connFd, resp, strlen(resp) + 1);
}

int main()
{
    struct SocketAgentCfg cfg = {
        .cid = MIGCVM_CID,
        .port = MIGCVM_AGENT_PORT,
        .backlog = 5            /* the length of the listening queue */
    };

    int ret = SocketAgentStartWithHandler(&cfg, CustomHandler); /* host socket */
    if (ret != 0) {
        fprintf(stderr, "Failed to start socket agent: %d\n", ret);
        return ret;
    }
    
    printf("Socket agent started successfully on port %lu with custom handler\n", cfg.port);
    return 0;
}

