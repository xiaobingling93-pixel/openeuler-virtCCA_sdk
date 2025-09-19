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
#include "securec.h"

#define MIN_REQUIRED_ARGS 3
#define GUEST_RD_BASE 16
#define GET_MIGRATION_INFO 1
#define SET_MIGRATION_SLOT 2

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

        case SET_MIGRATION_SLOT:
            // Parse rd value if provided
            printf("Testing set_migration_bind_slot with guest_rd=0x%llx...\n", migvm_info->guest_rd);
            attest_info->slot_status = SLOT_IS_READY;
            ret = set_migration_bind_slot_and_mask(ctx, migvm_info, attest_info);
            if (ret == TSI_SUCCESS) {
                printf("set_migration_bind_slot succeeded\n");
            } else {
                printf("set_migration_bind_slot failed with error: 0x%08x\n", ret);
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
    virtcca_mig_info_t migvm_info;
    migration_info_t *attest_info;
    int ret;
    unsigned long long guest_rd = 0;
    int function_to_test = 0; /* 1 for get_migration_info, 2 for set_migration_bind_slot */

    /* Parse command line arguments */
    if (argc < MIN_REQUIRED_ARGS) {
        printf("Usage: %s <function> [rd=<value>]\n", argv[0]);
        printf("  function: 1 for get_migration_info, 2 for set_migration_bind_slot\n");
        printf("  rd: guest_rd value in hex (e.g., rd=0x20000000)\n");
        return -1;
    }

    function_to_test = atoi(argv[1]);
    /* Initialize TSI context */
    ctx = tsi_new_ctx();
    if (ctx == NULL) {
        printf("Failed to create TSI context\n");
        return -1;
    }
    if (strncmp(argv[MIN_REQUIRED_ARGS - 1], "rd=", MIN_REQUIRED_ARGS) != 0) {
        printf("lack of guest_rd value for set_migration_bind_slot\n");
        tsi_free_ctx(ctx);
        return -1;
    }

    guest_rd = strtoull(argv[MIN_REQUIRED_ARGS - 1] + MIN_REQUIRED_ARGS, NULL, GUEST_RD_BASE);
    printf("using guest_rd: 0x%llx\n", guest_rd);
    
    // if (memset_s(&migvm_info, sizeof(migvm_info), 0, sizeof(migvm_info)) != 0) {
    if (memset(&migvm_info, 0, sizeof(migvm_info))) {
        printf("Failed to initialize migvm_info\n");
        tsi_free_ctx(ctx);
        return -1;
    }
    migvm_info.guest_rd = guest_rd;
    attest_info = (migration_info_t *)malloc(sizeof(migration_info_t));
    attest_info->msk = 0x11;

    ret = switch_request_function(ctx, function_to_test, attest_info, &migvm_info);
    // Clean up
    tsi_free_ctx(ctx);
    return ret;
}