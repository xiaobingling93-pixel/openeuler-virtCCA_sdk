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
        printf("Failed to get migration info: (errno=%d)\n", errno);
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

    if (!attest_info->pending_guest_rds) {
        return TSI_ERROR;
    }

    return TSI_SUCCESS;
}

int get_attestation_token(tsi_ctx *ctx, unsigned char *challenge, size_t challenge_len,
                          unsigned char *token, size_t *token_len)
{
    int ret;
    cvm_attestation_cmd_t user_cmd = {0};

    if (ctx == NULL || challenge == NULL || token == NULL || token_len == NULL) {
        return NULL_INPUT;
    }
    if (challenge_len > CHALLENGE_SIZE) {
        printf("challenge too long.\n");
        return INVALID_PARAM;
    }

    memcpy(user_cmd.challenge, challenge, challenge_len);

    ret = ioctl(ctx->fd, TMM_GET_ATTESTATION_TOKEN, &user_cmd);
    if (ret != 0) {
        printf("Failed to get attestation token. errno: %d\n", errno);
        return TSI_ERROR;
    }

    if (*token_len < user_cmd.token_size) {
        printf("Input token buf too small.\n");
        return INSUFFICIENT_BUFFER_LEN;
    }
    *token_len = user_cmd.token_size;
    memcpy(token, user_cmd.token, user_cmd.token_size);

    return TSI_SUCCESS;
}