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

static int insert_a_guest_rd_in_pending_guest_rds(unsigned long long guest_rd)
{
    for (int i = 0; i < MAX_BIND_VM; i++) {
        if (pending_guest_rds->guest_rd[i] == 0) {
            pending_guest_rds->guest_rd[i] = guest_rd;
            return 0;
        }
    }
    return -1;
}

static unsigned long long get_first_rd(pending_guest_rd_t *pending_guest_rds)
{
    for (int i = 0; i < MAX_BIND_VM; i++) {
        if (pending_guest_rds->guest_rd[i]) {
            return pending_guest_rds->guest_rd[i];
        }
    }
    return -1;
}

int prepare_migration(unsigned long long guest_rd)
{
    tsi_ctx *ctx = NULL;
    virtcca_mig_info_t *migvm_info;
    migration_info_t *attest_info;
    int ret;
    int function_to_test = 0; /* 1 for get_migration_info, 2 for set_migration_bind_slot */

    /* Initialize TSI context */
    ctx = tsi_new_ctx();
    if (ctx == NULL) {
        printf("Failed to create TSI context\n");
        return -1;
    }

    printf("using guest_rd: 0x%llx\n", guest_rd);
    migvm_info = (virtcca_mig_info_t *)malloc(sizeof(virtcca_mig_info_t));
    if (!migvm_info) {
        printf("Failed to initialize migvm_info\n");
        tsi_free_ctx(ctx);
        return -1;
    }
    migvm_info->guest_rd = guest_rd;
    attest_info = (migration_info_t *)malloc(sizeof(migration_info_t));
    if (!attest_info) {
        printf("Failed to initialize attest_info\n");
        tsi_free_ctx(ctx);
        return -1;
    };
    attest_info->msk[0] = 0x11;

    attest_info->pending_guest_rds = pending_guest_rds;
    migvm_info->mig_info = attest_info;

    printf("Testing get_rd_info with guestRd=0x%llx...\n", migvm_info->guest_rd);
    ret = set_migration_bind_slot_and_mask(ctx, migvm_info, attest_info);
    if (ret == TSI_SUCCESS) {
        printf("set_migration_bind_slot_and_mask succeeded\n");
    } else {
        printf("set_migration_bind_slot_and_mask failed with error: 0x%08x\n", ret);
        return -1;
    }
    free(attest_info);
    free(migvm_info);
    tsi_free_ctx(ctx);
    return ret;
}

unsigned long long get_guest_rd(pending_guest_rd_t *pending_guest_rds, bool *startup)
{
    tsi_ctx *ctx = NULL;
    virtcca_mig_info_t *migvm_info;
    migration_info_t *attest_info;
    int ret;
    int function_to_test = 0; /* 1 for get_migration_info, 2 for set_migration_bind_slot */

    printf("size of virtcca_mig_info_t is %zu\n", sizeof(virtcca_mig_info_t));
    printf("size of migration_info_t is %zu\n", sizeof(migration_info_t));
    if (!*startup)
        return get_first_rd(pending_guest_rds);
    ctx = tsi_new_ctx();
    if (ctx == NULL) {
        printf("Failed to create TSI context\n");
        return -1;
    }
    attest_info = (migration_info_t *)malloc(sizeof(migration_info_t));
    if (!attest_info) {
        printf("Failed to initialize attest_info\n");
        tsi_free_ctx(ctx);
        return -1;
    };
    migvm_info = (virtcca_mig_info_t *)malloc(sizeof(virtcca_mig_info_t));
    // if (memset_s(&migvm_info, sizeof(migvm_info), 0, sizeof(migvm_info)) != 0) {
    if (!migvm_info) {
        printf("Failed to initialize migvm_info\n");
        tsi_free_ctx(ctx);
        return -1;
    }
    attest_info->pending_guest_rds = pending_guest_rds;
    ret = get_migration_binded_rds(ctx, migvm_info, attest_info);

    if (ret == TSI_SUCCESS) {
        printf("get_rd_info succeeded\n");
    } else {
        printf("get_rd_info failed with error: 0x%08x\n", ret);
        tsi_free_ctx(ctx);
        return -1;
    }
    tsi_free_ctx(ctx);
    *startup = false;
    free(migvm_info);
    free(attest_info);
    return get_first_rd(pending_guest_rds);
}