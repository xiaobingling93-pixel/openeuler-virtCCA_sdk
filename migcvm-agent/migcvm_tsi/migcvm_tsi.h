/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef MIGCVM_TSI_H
#define MIGCVM_TSI_H
#include <stdbool.h>
#include <linux/ioctl.h>

#define TSI_MAGIC 'T'
#define TSI_SUCCESS 0

/* Measurement Related Defination */
#define TMI_HASH_ALGO_SHA256	0
#define TMI_HASH_ALGO_SHA512	1
#define TMI_HASH_ALGO_SM3		2

#ifndef HASH_ALGO
#define HASH_ALGO
enum HashAlgo {
    HASH_ALGO_SHA256 = TMI_HASH_ALGO_SHA256,
    HASH_ALGO_SHA512 = TMI_HASH_ALGO_SHA512,
    HASH_ALGO_SM3 = TMI_HASH_ALGO_SM3,
};
#endif

enum SlotStatus {
    SLOT_IS_EMPTY = 0,
    SLOT_IS_BINDED,
    SLOT_IS_READY
};

enum TSI_ERROR {
    NULL_INPUT = 0x00010001,  /* NULL pointer. */
    INVALID_PARAM,            /* Invalid param. */
    INSUFFICIENT_BUFFER_LEN,  /* Insufficient buffer space. */
    NO_DEVICE_FILE,           /* The TSI device file does not exist. */
    TSI_ERROR,                /* TSI error. */
};

typedef struct {
    int fd;
} TsiCtx;

/*
 * @brief   Init ctx.
 * @return  TSI context
 */
TsiCtx *TsiNewCtx(void);

/*
 * @brief   Free ctx.
 * @param   ctx [IN] TSI context
 */
void TsiFreeCtx(TsiCtx *ctx);

typedef struct MigrationInfo {
    /* Algorithm to use for measurements */
    // enum HashAlgo measurement_algo;
    /* cvm measurement */
    // unsigned char measurement[MEASUREMENT_SLOT_NR][MAX_MEASUREMENT_SIZE];
    bool isSrc;
    unsigned short slotStatus;
    unsigned long msk;
} MigrationInfoT;

typedef struct VirtccaMigvmInfo {
    enum Ops {
        OP_MIGRATE_GET_ATTR = 0,
        OP_MIGRATE_SET_SLOT
	} ops;
    MigrationInfoT *migInfo;    /* if ops == OP_MIGRATE_GET_ATTR, the size is sizeof(content) */
    unsigned long long guestRd;  /* if ops == OP_MIGRATE_SET_SLOT, the size is sizeof(guestRd) */
    unsigned long size;
} VirtccaMigvmInfoT;

#define TMM_GET_MIGRATION_INFO _IOWR(TSI_MAGIC, 3, struct VirtccaMigvmInfo)

int GetMigrationInfoAndMsk(TsiCtx *ctx, VirtccaMigvmInfoT *migvmInfo, MigrationInfoT *attestInfo);
int SetMigrationBindSlotAndMsk(TsiCtx *ctx, VirtccaMigvmInfoT *migvmInfo, MigrationInfoT *attestInfo);
#endif