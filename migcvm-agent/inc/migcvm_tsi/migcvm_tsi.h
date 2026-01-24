/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef MIGCVM_TSI_H
#define MIGCVM_TSI_H
#include <stdbool.h>
#include <linux/ioctl.h>

#define TSI_MAGIC 'T'
#define TSI_SUCCESS             0
#define TSI_ERROR_INPUT         1
#define TSI_ERROR_STATE         2
#define TSI_INCOMPLETE          3

/* Measurement Related Defination */
#define TMI_HASH_ALGO_SHA256    0
#define TMI_HASH_ALGO_SHA512    1
#define TMI_HASH_ALGO_SM3        2

#define MAX_BIND_VM                (256U)

enum slot_status {
    SLOT_IS_EMPTY = 0,
    SLOT_NOT_BINDED,
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

#define MEASUREMENT_SLOT_NR        (5U)
typedef struct pending_guest_rd_s {
    unsigned long long guest_rd[MAX_BIND_VM];
} pending_guest_rd_t;

typedef struct migration_info {
    unsigned long long msk[4];
    unsigned long long rand_iv[4];
    unsigned long long tag[2];
    pending_guest_rd_t *pending_guest_rds;
    unsigned short slot_status;
    bool set_key;
} migration_info_t;

typedef struct virtcca_migvm_info {
    enum Ops {
        OP_MIGRATE_GET_ATTR = 0,
        OP_MIGRATE_SET_SLOT,
        OP_MIGRATE_PEEK_RDS
    } ops;
    migration_info_t *mig_info;    /* if ops == OP_MIGRATE_GET_ATTR, the size is sizeof(content) */
    unsigned long long guest_rd;  /* if ops == OP_MIGRATE_SET_SLOT, the size is sizeof(guest_rd) */
    unsigned long size;
} virtcca_mig_info_t;

/*
 * Size in bytes of the largest measurement type that can be supported.
 * This macro needs to be updated accordingly if new algorithms are supported.
 */
#define MAX_DEV_CERT_SIZE          (4096U)
#define GRANULE_SIZE               (4096U)
#define MAX_TOKEN_GRANULE_COUNT    (2U)
#define CHALLENGE_SIZE             (64U)


typedef struct cvm_tsi_version {
    int major;
    int minor;
} cvm_tsi_version_t;

typedef struct cvm_attestation_cmd {
    unsigned char challenge[CHALLENGE_SIZE]; /* input: challenge value */
    unsigned char token[GRANULE_SIZE * MAX_TOKEN_GRANULE_COUNT];
    unsigned long token_size; /* return: token size */
} cvm_attestation_cmd_t;

typedef struct cca_dev_cert {
    unsigned long size;
    unsigned char value[MAX_DEV_CERT_SIZE];
} cca_dev_cert_t;


#define TMM_GET_ATTESTATION_TOKEN _IOWR(TSI_MAGIC, 1, cvm_attestation_cmd_t)

#define TMM_GET_DEV_CERT _IOR(TSI_MAGIC, 2, cca_dev_cert_t)

#define TMM_GET_MIGRATION_INFO _IOWR(TSI_MAGIC, 3, struct virtcca_migvm_info)

int get_migration_info_and_mask(tsi_ctx *ctx, virtcca_mig_info_t *migvm_info, migration_info_t *attest_info);
int set_migration_bind_slot_and_mask(tsi_ctx *ctx, virtcca_mig_info_t *migvm_info, migration_info_t *attest_info);
int get_migration_binded_rds(tsi_ctx *ctx, virtcca_mig_info_t *migvm_info, migration_info_t *attest_info);
int prepare_migration(unsigned long long guest_rd);

/*
 * @brief   Get attestation token.
 * @param   ctx [IN] TSI context
 * @param   challenge [IN] Challenge
 * @param   challenge_len [IN] Size of challenge. The maxinum value is 64.
 * @param   token [OUT] Attestation token
 * @param   token_len [IN/OUT] Size of attestation token
 * @param   rim_ref [OUT] RIM reference extracted from token (optional, can be NULL)
 * @return  TSI_SUCCESS Success
 *          For other error codes, see TSI_ERROR.
 */
int get_attestation_token(tsi_ctx *ctx, unsigned char *challenge, size_t challenge_len,
                          unsigned char *token, size_t *token_len);
#endif