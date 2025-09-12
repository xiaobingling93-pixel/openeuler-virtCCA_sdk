/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#include <errno.h>
#include <sys/ioctl.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <stddef.h>
#include <fcntl.h>
#include <unistd.h>
#include "migcvm_tsi.h"

TsiCtx *TsiNewCtx(void)
{
    TsiCtx *ctx = calloc(1, sizeof(TsiCtx));
    if (ctx == NULL) {
        printf("Failed to allocate TSI context: out of memory\n");
        return NULL;
    }
    ctx->fd = open("/dev/tsi", O_RDWR | O_CLOEXEC);
    if (ctx->fd == -1) {
        char errorMessage[256] = {0};
        strerror_r(errno, errorMessage, sizeof(errorMessage));
        printf("Failed to open TSI device: %s (errno=%d)\n", errorMessage, errno);
        free(ctx);
        return NULL;
    }
    return ctx;
}

void TsiFreeCtx(TsiCtx *ctx)
{
    if (ctx == NULL) {
        return;
    }
    if (ctx->fd != -1) {
        close(ctx->fd);
    }
    close(ctx->fd);
    free(ctx);
}

int GetMigrationInfoAndMsk(TsiCtx *ctx, VirtccaMigvmInfoT *migvmInfo, MigrationInfoT *attestInfo)
{
    int ret;
    if (ctx == NULL || migvmInfo == NULL || attestInfo == NULL) {
        return NULL_INPUT;
    }

    migvmInfo->ops = OP_MIGRATE_GET_ATTR;
    migvmInfo->size = sizeof(MigrationInfoT);
    if (attestInfo == NULL) {
        printf("Failed to allocate memory for MigrationInfo: out of memory\n");
        return TSI_ERROR;
    }
    migvmInfo->migInfo = attestInfo;

    ret = ioctl(ctx->fd, TMM_GET_MIGRATION_INFO, migvmInfo);
    if (ret != 0) {
        char errorMessage[256] = {0};
        strerror_r(errno, errorMessage, sizeof(errorMessage));
        printf("Failed to get migration info: %s (errno=%d)\n", errorMessage, errno);
        free(attestInfo);
        return TSI_ERROR;
    }

    if (attestInfo->msk) {
        printf("the local msk is 0x%lx\n", attestInfo->msk);
    } else {
        printf("the msk is not set\n");
    }

    if (attestInfo->isSrc) {
        printf("This is a source VM.\n");
    } else {
        printf("This is a destination VM.\n");
    }
    free(attestInfo);
    return TSI_SUCCESS;
}

int SetMigrationBindSlotAndMsk(TsiCtx *ctx, VirtccaMigvmInfoT *migvmInfo, MigrationInfoT *attestInfo)
{
    int ret;
    if (ctx == NULL || migvmInfo == NULL || attestInfo == NULL) {
        return NULL_INPUT;
    }

    migvmInfo->size = sizeof(MigrationInfoT);
    migvmInfo->ops = OP_MIGRATE_SET_SLOT;
    migvmInfo->migInfo = attestInfo;

    ret = ioctl(ctx->fd, TMM_GET_MIGRATION_INFO, migvmInfo);
    if (ret != 0) {
        printf("Failed to get migration info. errno: %d\n", errno);
        return TSI_ERROR;
    }

    return TSI_SUCCESS;
}
