/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <stdbool.h>
#include <stddef.h>
#include "migcvm_tsi.h"

#define MIN_REQUIRED_ARGS 4
#define GUEST_RD_BASE 16
#define GET_MIGRATION_INFO 1
#define BIND_MIGRATION_SLOT 2
#define SET_MIGRATION_SLOT 3
#define GET_MIGRATION_BINDED_RDS 4

static int switch_request_function(tsi_ctx *ctx, int function_to_test,
                                   migration_info_t *attest_info,
                                   virtcca_mig_info_t *migvm_info)
{
    int ret;
    switch (function_to_test) {
        case GET_MIGRATION_INFO:
            printf("Testing get_migration_info...\n");
            ret = get_migration_info_and_mask(ctx, migvm_info, attest_info);
            if (ret == TSI_SUCCESS) {
                printf("get_migration_info succeeded\n");
            } else {
                printf("get_migration_info failed with error: 0x%08x\n", ret);
                tsi_free_ctx(ctx);
                return -1;
            }
            break;

        case BIND_MIGRATION_SLOT:
            // Parse rd value if provided
            printf("Testing set_migration_bind_slot with guest_rd=0x%llx...\n", migvm_info->guest_rd);
            attest_info->slot_status = SLOT_IS_BINDED;
            attest_info->set_key = false;
            ret = set_migration_bind_slot_and_mask(ctx, migvm_info, attest_info);
            if (ret == TSI_SUCCESS) {
                printf("set_migration_bind_slot succeeded\n");
            } else {
                printf("set_migration_bind_slot failed with error: 0x%08x\n", ret);
                tsi_free_ctx(ctx);
                return -1;
            }
            break;

        case SET_MIGRATION_SLOT:
            // Parse rd value if provided
            printf("Testing set_migration_bind_slot with guest_rd=0x%llx...\n", migvm_info->guest_rd);
            attest_info->slot_status = SLOT_IS_READY;
            attest_info->set_key = true;
            ret = set_migration_bind_slot_and_mask(ctx, migvm_info, attest_info);
            if (ret == TSI_SUCCESS) {
                printf("set_migration_bind_slot succeeded\n");
            } else {
                printf("set_migration_bind_slot failed with error: 0x%08x\n", ret);
                tsi_free_ctx(ctx);
                return -1;
            }
            break;

        case GET_MIGRATION_BINDED_RDS:
            printf("Testing get_migration_binded_rds...\n");
            ret = get_migration_binded_rds(ctx, migvm_info, attest_info);
            if (ret == TSI_SUCCESS) {
                printf("get_migration_binded_rds succeeded\n");
            } else {
                printf("get_migration_binded_rds failed with error: 0x%08x\n", ret);
                tsi_free_ctx(ctx);
                return -1;
            }
            break;
        default:
            printf("Invalid function selection: %d\n", function_to_test);
            tsi_free_ctx(ctx);
            return -1;
    }
    return ret;
}

int main(int argc, char *argv[])
{
    tsi_ctx *ctx = NULL;
    virtcca_mig_info_t *migvm_info = NULL;
    migration_info_t *attest_info = NULL;
    pending_guest_rd_t *pending_guest_rds = NULL;
    int ret;
    unsigned long long guest_rd = 0;
    unsigned long long msk_value = 0;
    int function_to_test = 0; /* 1 for get_migration_info, 2 for set_migration_bind_slot */

    /* Parse command line arguments */
    if (argc < MIN_REQUIRED_ARGS) {
        printf("Usage: %s <function> <guest_rd> <msk>\n", argv[0]);
        printf("  function: 1 for get_migration_info, 2 for set_migration_bind_slot\n");
        printf("  guest_rd: guest_rd value in hex (e.g., 0x20000000)\n");
        printf("  msk: msk value in hex (e.g., 0x111)\n");
        return -1;
    }

    function_to_test = atoi(argv[1]);
    guest_rd = strtoull(argv[2], NULL, 0);
    msk_value = strtoull(argv[3], NULL, 0);
    printf("using guest_rd: 0x%llx\n", guest_rd);
    printf("using msk: 0x%llx\n", msk_value);

    /* Initialize TSI context */
    ctx = tsi_new_ctx();
    if (ctx == NULL) {
        printf("Failed to create TSI context\n");
        return -1;
    }

    printf("using guest_rd: 0x%llx\n", guest_rd);
    migvm_info = (virtcca_mig_info_t *)malloc(sizeof(virtcca_mig_info_t));
    if (migvm_info == NULL) {
        printf("Failed to allocate memory for migvm_info: out of memory\n");
        tsi_free_ctx(ctx);
        return -1;
    }
    migvm_info->guest_rd = guest_rd;
    attest_info = (migration_info_t *)malloc(sizeof(migration_info_t));
    pending_guest_rds = (pending_guest_rd_t *)malloc(sizeof(pending_guest_rd_t));
    if (!pending_guest_rds) {
        perror("Failed to allocate pending_guest_rds");
        return -1;
    }
    attest_info->msk[0] = msk_value;
    attest_info->pending_guest_rds = pending_guest_rds;
    ret = switch_request_function(ctx, function_to_test, attest_info, migvm_info);
    free(migvm_info);
    free(attest_info);
    free(pending_guest_rds);
    return ret;
}