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

static int SwitchRequestFunction(TsiCtx *ctx, int functionToTest,
                                 MigrationInfoT *attestInfo,
                                 VirtccaMigvmInfoT *migvmInfo)
{
    int ret;
    switch (functionToTest) {
        case GET_MIGRATION_INFO:
            printf("Testing get_migration_info...\n");
            ret = GetMigrationInfoAndMsk(ctx, migvmInfo, attestInfo);
            if (ret == TSI_SUCCESS) {
                printf("get_migration_info succeeded\n");
            } else {
                printf("get_migration_info failed with error: 0x%08x\n", ret);
                TsiFreeCtx(ctx);
                return -1;
            }
            break;

        case SET_MIGRATION_SLOT:
            // Parse rd value if provided
            printf("Testing set_migration_bind_slot with guestRd=0x%llx...\n", migvmInfo->guestRd);
            attestInfo->slotStatus = SLOT_IS_READY;
            ret = SetMigrationBindSlotAndMsk(ctx, migvmInfo, attestInfo);
            if (ret == TSI_SUCCESS) {
                printf("set_migration_bind_slot succeeded\n");
            } else {
                printf("set_migration_bind_slot failed with error: 0x%08x\n", ret);
                TsiFreeCtx(ctx);
                return -1;
            }
            break;

        default:
            printf("Invalid function selection: %d\n", functionToTest);
            TsiFreeCtx(ctx);
            return -1;
    }
    return ret;
}

int main(int argc, char *argv[])
{
    TsiCtx *ctx = NULL;
    VirtccaMigvmInfoT migvmInfo;
    MigrationInfoT *attestInfo;
    int ret;
    unsigned long long guestRd = 0;
    int functionToTest = 0; /* 1 for get_migration_info, 2 for set_migration_bind_slot */

    /* Parse command line arguments */
    if (argc < MIN_REQUIRED_ARGS) {
        printf("Usage: %s <function> [rd=<value>]\n", argv[0]);
        printf("  function: 1 for get_migration_info, 2 for set_migration_bind_slot\n");
        printf("  rd: guestRd value in hex (e.g., rd=0x20000000)\n");
        return -1;
    }

    functionToTest = atoi(argv[1]);
    /* Initialize TSI context */
    ctx = TsiNewCtx();
    if (ctx == NULL) {
        printf("Failed to create TSI context\n");
        return -1;
    }
    if (strncmp(argv[MIN_REQUIRED_ARGS - 1], "rd=", MIN_REQUIRED_ARGS) != 0) {
        printf("lack of guestRd value for set_migration_bind_slot\n");
        TsiFreeCtx(ctx);
        return -1;
    }

    guestRd = strtoull(argv[MIN_REQUIRED_ARGS - 1] + MIN_REQUIRED_ARGS, NULL, GUEST_RD_BASE);
    printf("using guestRd: 0x%llx\n", guestRd);
    
    if (memset_s(&migvmInfo, sizeof(migvmInfo), 0, sizeof(migvmInfo)) != 0) {
        printf("Failed to initialize migvmInfo\n");
        TsiFreeCtx(ctx);
        return -1;
    }
    migvmInfo.guestRd = guestRd;
    attestInfo = (MigrationInfoT *)malloc(sizeof(MigrationInfoT));
    attestInfo->msk = 0x11;

    ret = SwitchRequestFunction(ctx, functionToTest, attestInfo, &migvmInfo);
    // Clean up
    TsiFreeCtx(ctx);
    return ret;
}