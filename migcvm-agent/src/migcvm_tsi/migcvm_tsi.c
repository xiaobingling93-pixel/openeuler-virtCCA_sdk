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

tsi_ctx *tsi_new_ctx(void)
{
    tsi_ctx *ctx = calloc(1, sizeof(tsi_ctx));
    if (ctx == NULL) {
        printf("Failed to allocate TSI context: out of memory\n");
        return NULL;
    }
    ctx->fd = open("/dev/tsi", O_RDWR | O_CLOEXEC);
    if (ctx->fd == -1) {
        printf("Failed to open TSI device: (errno=%d)\n", errno);
        free(ctx);
        return NULL;
    }
    return ctx;
}

void tsi_free_ctx(tsi_ctx *ctx)
{
    if (ctx == NULL) {
        return;
    }
    close(ctx->fd);
    free(ctx);
}

int get_migration_info_and_mask(tsi_ctx *ctx, virtcca_mig_info_t *migvm_info, migration_info_t *attest_info)
{
    int ret;
    if (ctx == NULL || migvm_info == NULL || attest_info == NULL) {
        return NULL_INPUT;
    }

    migvm_info->ops = OP_MIGRATE_GET_ATTR;
    migvm_info->size = sizeof(migration_info_t);
    printf("migvm_info->size: %zu\n", migvm_info->size);
    migvm_info->mig_info = attest_info;

    ret = ioctl(ctx->fd, TMM_GET_MIGRATION_INFO, migvm_info);
    if (ret != 0) {
        char error_message[256] = {0};
        strerror_r(errno, error_message, sizeof(error_message));
        printf("Failed to get migration info: %s (errno=%d)\n", error_message, errno);
        return TSI_ERROR;
    }

    if (attest_info->set_key) {
        printf("This is a source VM.\n");
    } else {
        printf("This is a destination VM.\n");
    }
    return TSI_SUCCESS;
}

int set_migration_bind_slot_and_mask(tsi_ctx *ctx, virtcca_mig_info_t *migvm_info, migration_info_t *attest_info)
{
    int ret;
    if (ctx == NULL || migvm_info == NULL || attest_info == NULL) {
        return NULL_INPUT;
    }

    migvm_info->size = sizeof(migration_info_t);
    printf("migvm_info->size: %zu\n", migvm_info->size);
    migvm_info->ops = OP_MIGRATE_SET_SLOT;
    migvm_info->mig_info = attest_info;

    ret = ioctl(ctx->fd, TMM_GET_MIGRATION_INFO, migvm_info);
    if (ret != 0) {
        printf("Failed to set migration info. errno: %d\n", errno);
        return TSI_ERROR;
    }

    return TSI_SUCCESS;
}

int get_migration_binded_rds(tsi_ctx *ctx, virtcca_mig_info_t *migvm_info, migration_info_t *attest_info)
{
    int ret;
    if (ctx == NULL || migvm_info == NULL || attest_info == NULL) {
        return NULL_INPUT;
    }

    migvm_info->ops = OP_MIGRATE_PEEK_RDS;
    migvm_info->size = sizeof(migration_info_t);
    printf("migvm_info->size: %zu\n", migvm_info->size);
    if (attest_info->pending_guest_rds == NULL) {
        printf("Failed to allocate memory for get_migration_binded_rds: out of memory\n");
        return TSI_ERROR;
    }
    migvm_info->mig_info = attest_info;

    ret = ioctl(ctx->fd, TMM_GET_MIGRATION_INFO, migvm_info);
    if (ret != 0) {
        printf("Failed to get migration info binding rds: (errno=%d)\n", errno);
        return TSI_ERROR;
    }

    if (attest_info->pending_guest_rds) {
        for (unsigned int i = 0; i < MAX_BIND_VM; ++i) {
            if (attest_info->pending_guest_rds->guest_rd[i] != 0) {
                printf("Pending guest rd %u: 0x%llx\n", i,
                       (unsigned long long)attest_info->pending_guest_rds->guest_rd[i]);
                migvm_info->guest_rd = attest_info->pending_guest_rds->guest_rd[i];
            }
        }
    } else {
        printf("the pending_guest_rds is not set\n");
    }

    return TSI_SUCCESS;
}