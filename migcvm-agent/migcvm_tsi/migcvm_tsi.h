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

enum slot_status {
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
} tsi_ctx;

/*
 * @brief   Init ctx.
 * @return  TSI context
 */
tsi_ctx *tsi_new_ctx(void);

/*
 * @brief   Free ctx.
 * @param   ctx [IN] TSI context
 */
void tsi_free_ctx(tsi_ctx *ctx);

typedef struct migration_info {
    /* Algorithm to use for measurements */
    // enum HashAlgo measurement_algo;
    /* cvm measurement */
    // unsigned char measurement[MEASUREMENT_SLOT_NR][MAX_MEASUREMENT_SIZE];
    bool is_src;
    unsigned short slot_status;
    unsigned long msk;
} migration_info_t;

typedef struct virtcca_migvm_info {
    enum Ops {
        OP_MIGRATE_GET_ATTR = 0,
        OP_MIGRATE_SET_SLOT
	} ops;
    migration_info_t *mig_info;    /* if ops == OP_MIGRATE_GET_ATTR, the size is sizeof(content) */
    unsigned long long guest_rd;  /* if ops == OP_MIGRATE_SET_SLOT, the size is sizeof(guest_rd) */
    unsigned long size;
} virtcca_mig_info_t;

#define TMM_GET_MIGRATION_INFO _IOWR(TSI_MAGIC, 3, struct virtcca_migvm_info)

int get_migration_info_and_mask(tsi_ctx *ctx, virtcca_mig_info_t *migvm_info, migration_info_t *attest_info);
int set_migration_bind_slot_and_mask(tsi_ctx *ctx, virtcca_mig_info_t *migvm_info, migration_info_t *attest_info);
#endif