/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */
 
#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <fcntl.h>
#include <errno.h>
#include "tmi.h"

tmi_ctx *tmi_new_ctx(void)
{
    tmi_ctx *ctx = calloc(1, sizeof(tmi_ctx));
    if (ctx == NULL) {
        printf("Failed to allocate TMI context: out of memory\n");
        return NULL;
    }
    ctx->fd = open("/dev/tmi", O_RDWR | O_CLOEXEC);
    if (ctx->fd == -1) {
        printf("Failed to open TMI device: (errno=%d)\n", errno);
        free(ctx);
        return NULL;
    }
    return ctx;
}

void tmi_free_ctx(tmi_ctx *ctx)
{
    if (ctx == NULL) {
        return;
    }
    close(ctx->fd);
    free(ctx);
}

int virtcca_tmi_ioctl(tmi_ctx *ctx, int cmd_id, int flags, void *data, uint64_t *ret_val)
{
    struct virtcca_tmi_cmd cmd= {0};
    int ret = 0;

    cmd.id = cmd_id;
    cmd.flags = flags;
    if (data)
        cmd.data = (__u64)data;

    ret = ioctl(ctx->fd, VIRTCCA_TMI_IOCTL_ENTER, &cmd);
    if (ret != 0) {
        printf("Failed to call ioctl: (errno=%d)\n", errno);
        return -1;
    }

    if (ret_val)
        *ret_val = cmd.ret_val;

    return 0;
}
