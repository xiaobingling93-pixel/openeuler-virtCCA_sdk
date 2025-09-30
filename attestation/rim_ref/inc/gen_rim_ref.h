/*
 * SPDX-License-Identifier: BSD-3-Clause
 * SPDX-FileCopyrightText: Copyright TF-RMM Contributors.
 */

#ifndef GEN_RIM_REF_H
#define GEN_RIM_REF_H

#include <glib.h>
#include <stdbool.h>
#include <stdint.h>

#define GRANULE_SIZE				4096
#define TMI_HASH_ALGO_SHA256		(0U)
#define TMI_HASH_ALGO_SHA512		(1U)
#define MEASUREMENT_CVM_HEADER		(1U)
#define MEASUREMENT_DATA_HEADER		(2U)
#define MEASUREMENT_REC_HEADER		(3U)
#define SHA256_SIZE					(32U)
#define SHA512_SIZE					(64U)
#define MAX_MEASUREMENT_SIZE		SHA512_SIZE
#define TMI_NO_MEASURE_CONTENT		(0U)
#define TMI_MEASURE_CONTENT			(1U)
#define RPV_SIZE					64
#define TEC_CREATE_NR_GPRS			(8U)
#define MEASURE_DESC_TYPE_DATA		0x0
#define MEASURE_DESC_TYPE_REC		0x1
#define MEASURE_DESC_TYPE_RIPAS		0x2
#define L2_GRANULE					0x200000 /* 2MB */
#define L3_GRANULE					0x1000	 /* 4KB */
#define BOOTLOADER_LEN_UINT32		10
#define GiB 						0x40000000
#define MB							0x100000
#define KERNEL_LOAD_OFFSET			2*MB
#define BLOCK_SIZE					L2_GRANULE
#define LOADER_START_ADDR			0x40000000  /* 1 GIB */
#define ARM64_MAGIC_OFFSET			56
#define ARM64_TEXT_OFFSET_OFFSET	8
#define INITRD_LOAD_OFFSET			0x8000000
#define UEFI_LOAD_SIZE				0x8000000
#define UEFI_LOAD_START				0x0
#define PATH_LEN_MAX				1000
#define FILE_SIZE_MAX				(1 * GiB)
#define SVE_VECTOR_MIN_LEN          128

#define LPA2_BIT					0
#define SVE_BIT						1
#define PMU_BIT						2


enum hash_algo {
    HASH_ALGO_SHA256 = TMI_HASH_ALGO_SHA256,
    HASH_ALGO_SHA512 = TMI_HASH_ALGO_SHA512,
};

#define SET_MEMBER(member, start, end)            \
    union {                                       \
        member;                                   \
        unsigned char reserved##end[(end) - (start)]; \
    }

#define SET_BIT(number, n) \
    ((number) |= ((uint64_t)1 << (n)))

#define CLEAR_BIT(number, n) \
    ((number) &= ~((uint64_t)1 << (n)))

#define __typeof__ typeof
#define round_mask(x, y) ((__typeof__(x))((y) - 1))
#define round_up(x, y) ((((x) - 1) | round_mask(x, y)) + 1)
#define round_down(x, y) ((x) & ~round_mask(x, y))

#define gen_err(fmt, ...) fprintf(stderr, "[ERROR] " fmt "\n", ##__VA_ARGS__)

typedef struct tmi_cvm_create_params {
    uint64_t flags;
    uint64_t s2sz;
    uint64_t sve_vl;
    uint64_t num_bps;
    uint64_t num_wps;
    uint64_t pmu_num_cnts;
    uint64_t measurement_algo;
} tmi_cvm_create_params_t;

typedef struct tmi_tec_crreate_params {
    uint64_t gprs[TEC_CREATE_NR_GPRS];
    uint64_t pc;
    uint64_t flags;
} tmi_tec_create_params_t;

typedef struct tmi_data_crreate_params {
    uint64_t *data;
    uint64_t size;
    uint64_t flags;
    uint64_t ipa;
} tmi_data_create_params_t;

/* TmmMeasurementDescriptorCVM type as per RMM spec */
typedef struct tmi_measure_cvm {
    /* Flags */
    SET_MEMBER(unsigned long flags, 0, 0x8); /* Offset 0 */
    /* Requested IPA width */
    SET_MEMBER(unsigned int s2sz, 0x8, 0x10); /* 0x8 */
    /* Requested SVE vector length */
    SET_MEMBER(unsigned int sve_vl, 0x10, 0x18); /* 0x10 */
    /* Requested number of breakpoints */
    SET_MEMBER(unsigned int num_bps, 0x18, 0x20); /* 0x18 */
    /* Requested number of watchpoints */
    SET_MEMBER(unsigned int num_wps, 0x20, 0x28); /* 0x20 */
    /* Requested number of PMU counters */
    SET_MEMBER(unsigned int pmu_num_cnts, 0x28, 0x30); /* 0x28 */
    /* Measurement algorithm */
    SET_MEMBER(unsigned char measurement_algo, 0x30, 0x400); /* 0x30 */
    /* Realm Personalization Value */
    unsigned char reserved0x800[0x800 - 0x400];   /* 0x400 */
    unsigned char reserved0x1000[0x1000 - 0x800]; /* 0x800 */
} tmi_measure_cvm_t;

typedef struct tmi_tec_params {
    uint64_t gprs[TEC_CREATE_NR_GPRS];
    uint64_t pc;
    uint64_t flags;
} tmi_tec_params_t;

/* TmmMeasurementDescriptorData type as per RMM spec */
typedef struct tmi_measure_data {
    /* Measurement descriptor type, value 0x0 */
    SET_MEMBER(unsigned char desc_type, 0x0, 0x8);
    /* Length of this data structure in bytes */
    SET_MEMBER(unsigned long len, 0x8, 0x10);
    /* Current RIM value */
    SET_MEMBER(unsigned char rim[MAX_MEASUREMENT_SIZE], 0x10, 0x50);
    /* IPA at which the DATA Granule is mapped in the cvm */
    SET_MEMBER(unsigned long ipa, 0x50, 0x58);
    /* Flags provided by Host */
    SET_MEMBER(unsigned long flags, 0x58, 0x60);
    /*
     * Hash of contents of DATA Granule, or zero if flags indicate DATA
     * Granule contents are unmeasured
     */
    SET_MEMBER(unsigned char content[MAX_MEASUREMENT_SIZE], 0x60, 0x100);
} tmi_measure_data_t;

/* TmmMeasurementDescriptorRec type as per RMM spec */
typedef struct tmi_measure_tec {
    /* Measurement descriptor type, value 0x1 */
    SET_MEMBER(unsigned char desc_type, 0x0, 0x8);
    /* Length of this data structure in bytes */
    SET_MEMBER(unsigned long len, 0x8, 0x10);
    /* Current RIM value */
    SET_MEMBER(unsigned char rim[MAX_MEASUREMENT_SIZE], 0x10, 0x50);
    /* Hash of 4KB page which contains REC parameters data structure */
    SET_MEMBER(unsigned char content[MAX_MEASUREMENT_SIZE], 0x50, 0x100);
} tmi_measure_tec_t;

typedef struct cvm_init_measure {
    enum hash_algo measurement_algo;
    unsigned char rim[MAX_MEASUREMENT_SIZE];
} cvm_init_measure_t;

typedef struct blob {
    uint64_t guest_start;
    uint8_t *data;
    size_t size;
    struct blob *next;
} blob;

typedef struct {
    blob *head;
} blob_list;

typedef struct {
    char kernel_path[PATH_LEN_MAX];
    char dtb_path[PATH_LEN_MAX];
    char initramfs_path[PATH_LEN_MAX];
    char firmware_path[PATH_LEN_MAX];
    char kata_config_path[PATH_LEN_MAX];
    char pod_config_path[PATH_LEN_MAX];
    uint64_t vcpu_num;
    int sve_vector_length;
    int pmu_counter_num;
} tools_args;

void measure_create_cvm(cvm_init_measure_t *meas,
                        bool lpa2_enable,
                        bool sve_enable,
                        bool pmu_enable,
                        uint64_t ipa_width,
                        uint64_t sve_vector_length,
                        uint64_t num_bps,
                        uint64_t num_wps,
                        uint64_t num_pmu,
                        uint64_t hash_algo);

void measure_create_tecs(cvm_init_measure_t *meas,
                         uint64_t loader_start,
                         unsigned int tec_num);

void measure_load_data(cvm_init_measure_t *meas,
                       uint64_t loader_start,
                       uint64_t initrd_start,
                       const char *kernel_path,
                       const char *ramdisk_path,
                       const char *dtb_path);

void generate_rim_reference(uint64_t tec_num,
                            uint64_t sve_vector_size,
                            uint64_t pmu_counter_num,
                            const blob_list *rim_blobs,
                            bool use_firmware);
void print_hash(unsigned char *measurement,
                const enum hash_algo algorithm);

#endif /* GEN_RIM_REF_H */
