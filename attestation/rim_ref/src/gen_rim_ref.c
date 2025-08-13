/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024. All rights reserved.
 * virtCCA_sdk is licensed under the Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan PSL v2.
 * You may obtain a copy of Mulan PSL v2 at:
 *     http://license.coscl.org.cn/MulanPSL2
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
 * PURPOSE.
 * See the Mulan PSL v2 for more details.
 */
#include <assert.h>
#include <errno.h>
#include <getopt.h>
#include <openssl/evp.h>
#include <openssl/sha.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gen_dtb.h"
#include "libQemuGen.h"
#include "gen_rim_ref.h"

#if LOG_PRINT
int data_measure_cnt = 0;
int data_unknown_cnt = 0;
#endif

typedef enum {
    KERNEL_FILE = 0,
    UEFI_FILE,
    DEFAULT_FILE,
} FILE_TYPE;

#define ARM_MAGIC_LEN   4
#define OFF_32   32
#define BIT_OFFSET_4    4
#define TEMP_DUMP_SIZE  130
#define NO_ARGUMENT     2

static inline size_t measurement_get_size(
    const enum hash_algo algorithm)
{
    size_t ret = 0;
    switch (algorithm) {
        case HASH_ALGO_SHA256:
            ret = (size_t)SHA256_SIZE;
            break;
        case HASH_ALGO_SHA512:
            ret = (size_t)SHA512_SIZE;
            break;
        default:
            assert(false);
    }
    return ret;
}

static int load_file_data(const char *file_path, uint8_t **data, size_t *size, FILE_TYPE type)
{
    FILE *file = NULL;
    gsize file_size = 0;
    gchar *file_data = NULL;
    uint64_t hdrvals[2] = {0};
    int ret = -1;

    if (!g_file_get_contents(file_path, &file_data, &file_size, NULL)) {
        gen_err("open file failed, %s", strerror(errno));
        return -1;
    }

    switch (type) {
        case KERNEL_FILE:
            if (file_size > ARM64_MAGIC_OFFSET + ARM_MAGIC_LEN &&
                memcmp(file_data + ARM64_MAGIC_OFFSET, "ARM\x64", ARM_MAGIC_LEN) == 0) {
                memcpy(&hdrvals, file_data + ARM64_TEXT_OFFSET_OFFSET, sizeof(hdrvals));
                *size = round_up(hdrvals[1], L3_GRANULE);
            }
            break;
        case UEFI_FILE:
            if (file_size > UEFI_LOAD_SIZE) {
                gen_err("uefi is too large %ld", file_size);
                goto free_file;
            }
            *size = UEFI_LOAD_SIZE;
            break;
        case DEFAULT_FILE:
            *size = round_up(file_size + 1, L2_GRANULE);
            break;
        default:
            gen_err("unsupport type %u", type);
            goto free_file;
    }

    if (*size == 0 || *size > FILE_SIZE_MAX) {
        gen_err("file is invalid %lu", *size);
        goto free_file;
    }

    *data = (unsigned char *)malloc(*size);
    if (*data == NULL) {
        perror("malloc buffer for kernel failed.");
        goto free_file;
    }
    memset(*data, 0, *size);
    memcpy(*data, file_data, file_size);
    ret = 0;

free_file:
    free(file_data);
    return ret;
}

static int get_bootloader_aarch64(uint64_t kernel_start,
                                  uint64_t dtb_start,
                                  uint8_t **data,
                                  size_t *size)
{
    uint32_t bootloader[BOOTLOADER_LEN_UINT32] = {
        0x580000c0,             /* 0x 58 00 00 c0      ; ldr x0, arg ; Load the lower 32-bits of DTB */
        0xaa1f03e1,             /* 0x aa 1f 03 e1      ; mov x1, xzr */
        0xaa1f03e2,             /* 0x aa 1f 03 e2      ; mov x2, xzr */
        0xaa1f03e3,             /* 0x aa 1f 03 e3      ; mov x3, xzr */
        0x58000084,             /* 0x 58 00 00 84      ; ldr x4, entry ; Load the lower 32-bits of kernel entry */
        0xd61f0080,             /* 0x d6 1f 00 80      ; br x4      ; Jump to the kernel entry point */
        dtb_start,              /* FIXUP_ARGPTR_LO     ; arg: .word @DTB Lower 32-bits */
        dtb_start >> OFF_32,    /* FIXUP_ARGPTR_HI     ; .word @DTB Higher 32-bits */
        kernel_start,           /* FIXUP_ENTRYPOINT_LO ; entry: .word @Kernel Entry Lower 32-bits */
        kernel_start >> OFF_32, /* FIXUP_ENTRYPOINT_HI ; .word @Kernel Entry Higher 32-bits */
    };

    *size = BLOCK_SIZE;
    if ((*data = malloc(*size)) == NULL) {
        gen_err("malloc buffer failed");
        return -1;
    }

    memset(*data, 0, *size);
    memcpy(*data, bootloader, BOOTLOADER_LEN_UINT32 * sizeof(uint32_t));
    return 0;
}

static void print_data(unsigned char *data, size_t size, const char *name)
{
    char hexDigits[] = "0123456789ABCDEF";
    int hexIndex = 0;
    char output[TEMP_DUMP_SIZE] = {0};

    if (size > SHA512_SIZE) {
        size = SHA512_SIZE;
    }

    for (unsigned int i = 0; i < size; ++i) {
        output[hexIndex++] = hexDigits[(*(data + i) >> BIT_OFFSET_4) & 0x0F];
        output[hexIndex++] = hexDigits[*(data + i) & 0x0F];
    }

    printf("%s: %s\n", name, output);
}

void print_hash(unsigned char *measurement,
                const enum hash_algo algorithm)
{
    unsigned int size = 0U;
    assert(measurement != NULL);

    switch (algorithm) {
        case HASH_ALGO_SHA256:
            size = SHA256_SIZE;
            break;
        case HASH_ALGO_SHA512:
            size = SHA512_SIZE;
            break;
        default:
            assert(0);
    }

    print_data(measurement, size, "HASH");
}

static int do_hash(enum hash_algo hash_algo,
                   uint8_t *data,
                   size_t size,
                   unsigned char *out)
{
    int result = -1;
    EVP_MD_CTX *mdctx;
    const EVP_MD *md;
    unsigned int md_len;

    OpenSSL_add_all_digests();

    switch (hash_algo) {
        case HASH_ALGO_SHA256:
            md = EVP_sha256();
            break;
        case HASH_ALGO_SHA512:
            md = EVP_sha512();
            break;
        default:
            gen_err("Unspported hash algorithnm\n");
            return -1;
    }

    mdctx = EVP_MD_CTX_new();
    if (mdctx == NULL) {
        gen_err("Failed to initialiaze digest contex\n");
        return -1;
    }

    if (EVP_DigestInit_ex(mdctx, md, NULL) != 1) {
        gen_err("Failed to initialize digest\n");
    } else if (EVP_DigestUpdate(mdctx, data, size) != 1) {
        gen_err("Failed to update digest\n");
    } else if (EVP_DigestFinal_ex(mdctx, out, &md_len) != 1) {
        gen_err("Failed to finalize digest\n");
    }
    EVP_MD_CTX_free(mdctx);
    result = 0;

#if LOG_PRINT
    print_hash(out, hash_algo);
#endif

    return result;
}

void measure_tmi_cvm_create(cvm_init_measure_t *meas, tmi_cvm_create_params_t *params)
{
    /* Allocate a zero-filled tmi_measure_cvm_t data structure to hold
    the measured cVM parameters. By specification cVM_params is 4KB. */
    unsigned char buffer[sizeof(tmi_measure_cvm_t)] = {0};
    tmi_measure_cvm_t *tmm_params_measured = (tmi_measure_cvm_t *)buffer;

    /*
     * Copy flags, s2sz, sve_vl, num_bps, num_wps, pmu_num_cnts
     * and hash_algo to the measured cVM parameters.
     */
    tmm_params_measured->flags = params->flags;
    tmm_params_measured->s2sz = params->s2sz;
    tmm_params_measured->sve_vl = params->sve_vl;
    tmm_params_measured->num_bps = params->num_bps;
    tmm_params_measured->num_wps = params->num_wps;
    tmm_params_measured->pmu_num_cnts = params->pmu_num_cnts;
    tmm_params_measured->measurement_algo = params->measurement_algo;

    meas->measurement_algo = params->measurement_algo;

#if LOG_PRINT
    printf("Measuring tmi_cvm_create\n");
    printf("flags:   0x%016lx\n", params->flags);
    printf("s2sz:    0x%016lx\n", params->s2sz);
    printf("sve_vl:  0x%016lx\n", params->sve_vl);
    printf("num_bps: 0x%016lx\n", params->num_bps);
    printf("num_wps: 0x%016lx\n", params->num_wps);
    printf("pmu_cnt: 0x%016lx\n", params->pmu_num_cnts);
    printf("h-algo:  0x%016lx\n", params->measurement_algo);
#endif

    /* Compute the HASH on tmm_params_measured data structurem, set the RIM to
       this value, zero filling the upper bytes if the HASH output is smaller
       than the size of the RIM. */
    do_hash(meas->measurement_algo, (uint8_t *)buffer, sizeof(buffer), meas->rim);
}

void measure_tmi_tec_create(cvm_init_measure_t *meas, tmi_tec_create_params_t *params)
{
    /* Allocate a zero_filled TmiTecParams data structure to hold the measured
    TEC parametsrs. */
    unsigned char buffer[sizeof(tmi_tec_params_t)] = {0};
    tmi_tec_params_t *tec_params_measured = (tmi_tec_params_t *)buffer;

    /* Copy gprs, pc, flags into the measured TEC parameters data structure */
    tec_params_measured->pc = params->pc;
    tec_params_measured->flags = params->flags;
    memcpy(tec_params_measured->gprs, params->gprs, sizeof(params->gprs));

#if LOG_PRINT
    printf("Measuring tmi_tec_create\n");
    printf("pc:      0x%016lx\n", tec_params_measured->pc);
    printf("flags:   0x%016lx\n", tec_params_measured->flags);
    for (uint32_t i = 0; i < TEC_CREATE_NR_GPRS; i++) {
        printf("gprs[%d]: 0x%016lx\n", i, tec_params_measured->gprs[i]);
    }
#endif

    /* Initialize the measurement descriptor structure and populate the descriptor */
    tmi_measure_tec_t measure_desc = {0};
    /* Set the desc_type field to the descriptor type */
    measure_desc.desc_type = MEASURE_DESC_TYPE_REC;
    /* Set the len field to the descriptor length */
    measure_desc.len = sizeof(tmi_measure_tec_t);
    /* Set the rim field to the current RIM value of the target cVM */
    memcpy(measure_desc.rim, meas->rim, measurement_get_size(meas->measurement_algo));
    /* Set the content field to the hash of the measured REC parameters */
    do_hash(meas->measurement_algo, (uint8_t *)tec_params_measured, sizeof(*tec_params_measured), measure_desc.content);

    /* Hashing the measurement descriptor structure and get the new RIM */
    do_hash(meas->measurement_algo, (uint8_t *)&measure_desc, sizeof(measure_desc), meas->rim);
}

void measure_tmi_data_create(cvm_init_measure_t *meas, tmi_data_create_params_t *params)
{

    /* Allocate an TmiMeasurementDescriptorData data structure */
    tmi_measure_data_t measure_desc = {0};

    /* Initialize the measurement descriptior structure */
    /* Set the desc_type field to the descriptor type */
    measure_desc.desc_type = MEASURE_DESC_TYPE_DATA;
    /* Set the len field to the descriptor length */
    measure_desc.len = sizeof(tmi_measure_data_t);
    /* Set the ipa field to the IPA at which the DATA Granule is mapped in the target cVM */
    measure_desc.ipa = params->ipa;
    /* Set the flags field to the flags */
    measure_desc.flags = params->flags;
    /* Set the rim field to the current RIM value of the target cVM */
    (void)memcpy(measure_desc.rim, meas->rim, measurement_get_size(meas->measurement_algo));

    /* If flags.measure == TMI_MEASURE_CONTENT then set the content field to the hash of
     * the contents of the DATA Granule. Otherwise, set the content field to zero.
     */
    if (measure_desc.flags == TMI_MEASURE_CONTENT) {
/*
 * Hashing the data granules and store the result in the
 * measurement descriptor structure.
 */
#if LOG_PRINT
        data_measure_cnt++;
        printf("Measuring tmi_data_create %d\n", data_measure_cnt);
        print_data((unsigned char *)params->data, params->size, "DATA");
#endif

        do_hash(meas->measurement_algo, (uint8_t *)params->data, (size_t)params->size, measure_desc.content);
    } else {
#if LOG_PRINT
        data_unknown_cnt++;
        printf("Measuring tmi_data_create_unknown %d\n", data_unknown_cnt);
#endif
    }

#if LOG_PRINT
    printf("ipa:     0x%016lx\n", params->ipa);
    printf("size:    0x%016lx\n", params->size);
    printf("flags:   0x%016lx\n", params->flags);
#endif

    /*
     * Hashing the measurement descriptor structure; the result is the
     * updated RIM.
     */
    do_hash(meas->measurement_algo, (uint8_t *)&measure_desc, sizeof(measure_desc), meas->rim);
}

void measure_create_tecs(cvm_init_measure_t *meas,
                         uint64_t loader_start,
                         unsigned int tec_num)
{
    tmi_tec_create_params_t params;

    for (size_t i = 0; i < tec_num; i++) {
        memset(&params, 0, sizeof(params));
        if (i == 0) { /* The master tec */
            params.pc = loader_start;
            SET_BIT(params.flags, 0);
        }
        measure_tmi_tec_create(meas, &params);
    }
}

void measure_create_cvm(cvm_init_measure_t *meas,
                        bool lpa2_enable,
                        bool sve_enable,
                        bool pmu_enable,
                        uint64_t ipa_width,
                        uint64_t sve_vector_length,
                        uint64_t num_bps,
                        uint64_t num_wps,
                        uint64_t num_pmu,
                        uint64_t hash_algo)
{
    tmi_cvm_create_params_t params = {0};
    if (lpa2_enable) {
        SET_BIT(params.flags, LPA2_BIT);
    } else {
        CLEAR_BIT(params.flags, LPA2_BIT);
    }

    if (sve_enable) {
        SET_BIT(params.flags, SVE_BIT);
    } else {
        CLEAR_BIT(params.flags, SVE_BIT);
    }

    if (pmu_enable) {
        SET_BIT(params.flags, PMU_BIT);
    } else {
        CLEAR_BIT(params.flags, PMU_BIT);
    }

    params.s2sz = ipa_width;
    params.sve_vl = sve_vector_length;
    params.num_bps = num_bps;
    params.num_wps = num_wps;
    params.pmu_num_cnts = num_pmu;
    params.measurement_algo = hash_algo;

    measure_tmi_cvm_create(meas, &params);
}

static void init_rim_blobs(blob_list *rim_blobs)
{
    rim_blobs->head = NULL;
}

static void free_rim_blobs(blob_list *rim_blobs)
{
    blob *cur = rim_blobs->head;
    blob *next = NULL;
    while (cur) {
        blob *next = cur->next;
        free(cur->data);
        free(cur);
        cur = next;
    }
    rim_blobs->head = NULL;
}

static blob *add_rim_blob(blob_list *rim_blobs, uint64_t guest_start, uint8_t *data, size_t size)
{
    blob *new_blob = NULL, **curr;

    new_blob = (blob *)malloc(sizeof(blob));
    if (!new_blob) {
        gen_err("allocate memory for new blob failed.");
        return NULL;
    }

    new_blob->guest_start = guest_start;
    new_blob->data = data;
    new_blob->size = size;
    new_blob->next = NULL;

    curr = &rim_blobs->head;
    while (*curr && (*curr)->guest_start < guest_start) {
        curr = &(*curr)->next;
    }

    if (*curr && (*curr)->guest_start == guest_start) {
        gen_err("duplicate blob at address 0x%lx", guest_start);
        goto free;
    }

    new_blob->next = *curr;
    *curr = new_blob;
    return new_blob;

free:
    free(new_blob);
    return NULL;
}

static void print_rim_blobs(const blob_list *blobs)
{
    const blob *curr = blobs->head;
    while (curr) {
        printf("rim blob at address 0x%lx: size = %zu\n", curr->guest_start, curr->size);
        curr = curr->next;
    }
}

static void measure_rim_blobs(cvm_init_measure_t *meas, const blob_list *rim_blobs)
{
    tmi_data_create_params_t params = {0};
    uint8_t *data = NULL;
    size_t size = 0;
    uint64_t addr = 0;
    const blob *curr = rim_blobs->head;

    while (curr) {
        addr = curr->guest_start;
        data = curr->data;
        size = curr->size;

        for (uint64_t i = 0; i < size / L3_GRANULE; i++) {
            memset(&params, 0, sizeof(params));
            params.data = (uint64_t *)(data + i * L3_GRANULE);
            params.size = L3_GRANULE;
            SET_BIT(params.flags, 0);
            params.ipa = addr + i * L3_GRANULE;
            measure_tmi_data_create(meas, &params);
        }

        curr = curr->next;
    }
}

void generate_rim_reference(uint64_t tec_num, uint64_t sve_vector_size,
    uint64_t pmu_counter_num, const blob_list *rim_blobs, bool use_firmware)
{
    bool lpa2_enable = false;
    bool sve_enable = (sve_vector_size > 0) ? true : false;
    bool pmu_enable = (pmu_counter_num > 0) ? true : false;
    uint64_t ipa_width = 40;
    uint64_t sve_vector_length = sve_enable ? (sve_vector_size / SVE_VECTOR_MIN_LEN) : 0;
    uint64_t num_bps = 0;
    uint64_t num_wps = 0;
    uint64_t num_pmu = pmu_counter_num;
    uint64_t hash_algo = 0;
    uint64_t pc = 0;

    cvm_init_measure_t meas = {0};
    measure_create_cvm(&meas, lpa2_enable, sve_enable, pmu_enable,
                       ipa_width, sve_vector_length, num_bps, num_wps,
                       num_pmu, hash_algo);
    measure_rim_blobs(&meas, rim_blobs);
    pc = use_firmware ? 0 : LOADER_START_ADDR;
    measure_create_tecs(&meas, pc, tec_num);
    printf("RIM-");
    print_hash(meas.rim, meas.measurement_algo);
}

static blob *load_data_to_blobs(blob_list *rim_blobs, const char *path, FILE_TYPE type, uint64_t start_addr)
{
    uint8_t *data = NULL;
    size_t size = 0;
    blob *new_blob = NULL;

    if (load_file_data(path, &data, &size, type)) {
        gen_err("load data from file failed.");
        return NULL;
    }
    new_blob = add_rim_blob(rim_blobs, start_addr, data, size);
    if (!new_blob) {
        gen_err("add data to rim blobs failed");
        goto free;
    }
    return new_blob;

free:
    free(data);
    return NULL;
}

static blob *load_loader_to_blobs(blob_list *rim_blobs, uint64_t kernel_start, uint64_t dtb_start, uint64_t start_addr)
{
    uint8_t *data = NULL;
    size_t size = 0;
    blob *new_blob = NULL;

    if (get_bootloader_aarch64(kernel_start, dtb_start, &data, &size)) {
        gen_err("load bootloader data failed.");
        return NULL;
    }
    new_blob = add_rim_blob(rim_blobs, start_addr, data, size);
    if (!new_blob) {
        gen_err("add data to rim blobs failed");
        goto free;
    }
    return new_blob;

free:
    free(data);
    return NULL;
}

static int build_kernel_blobs(blob_list *rim_blobs, tools_args *args)
{
    uint64_t loader_start = LOADER_START_ADDR;
    uint64_t kernel_start = loader_start + KERNEL_LOAD_OFFSET;
    uint64_t initrd_start = loader_start + INITRD_LOAD_OFFSET;
    uint64_t dtb_start = initrd_start;
    blob *cur_blob = NULL;

    cur_blob = load_data_to_blobs(rim_blobs, args->kernel_path, KERNEL_FILE, kernel_start);
    if (!cur_blob) {
        gen_err("load kernel to blobs failed");
        goto free;
    }

    if (strlen(args->initramfs_path) != 0) {
        cur_blob = load_data_to_blobs(rim_blobs, args->initramfs_path, DEFAULT_FILE, initrd_start);
        if (!cur_blob) {
            gen_err("load initrd to blobs failed");
            goto free;
        }
        dtb_start += cur_blob->size;
    }

    cur_blob = load_data_to_blobs(rim_blobs, args->dtb_path, DEFAULT_FILE, dtb_start);
    if (!cur_blob) {
        gen_err("add dtb to blobs failed");
        goto free;
    }

    cur_blob = load_loader_to_blobs(rim_blobs, kernel_start, dtb_start, loader_start);
    if (!cur_blob) {
        gen_err("add bootloader to blobs failed");
        goto free;
    }
    return 0;

free:
    free_rim_blobs(rim_blobs);
    return -1;
}

static int build_firmware_blobs(blob_list *rim_blobs, tools_args *args)
{
    blob *cur_blob = NULL;

    cur_blob = load_data_to_blobs(rim_blobs, args->firmware_path, UEFI_FILE, UEFI_LOAD_START);
    if (!cur_blob) {
        gen_err("add firmware to blobs failed");
        goto free;
    }

    cur_blob = load_data_to_blobs(rim_blobs, args->dtb_path, DEFAULT_FILE, LOADER_START_ADDR);
    if (!cur_blob) {
        gen_err("add dtb to blobs failed");
        goto free;
    }
    return 0;

free:
    free_rim_blobs(rim_blobs);
    return -1;
}

static int build_coco_blobs(blob_list *rim_blobs, tools_args *args)
{
    uint64_t loader_start = LOADER_START_ADDR;
    uint64_t kernel_start = loader_start + KERNEL_LOAD_OFFSET;
    uint64_t initrd_start = loader_start + INITRD_LOAD_OFFSET;
    uint64_t dtb_start = initrd_start;
    blob *cur_blob = NULL;

    // generate the qemu instr by qemu instr generator(GOLANGlib)
    struct GenerateQemuInstr_return result = GenerateQemuInstr(args->kata_config_path, args->pod_config_path);
    char *qemu_instr = (char *)malloc(MAX_CMD_LENGTH * sizeof(char));
    char *qemu_bin_path = (char *)malloc(MAX_OPTION_LENGTH * sizeof(char));
    char *kernel_path = (char *)malloc(MAX_OPTION_LENGTH * sizeof(char));

    (void)snprintf(qemu_instr, MAX_CMD_LENGTH, "%s", result.r2);
    (void)snprintf(qemu_bin_path, MAX_OPTION_LENGTH, "%s", result.r3);
    (void)snprintf(kernel_path, MAX_OPTION_LENGTH, "%s", result.r4);
    if (result.r0) {
        generate_dtb_with_kata_config(qemu_bin_path, qemu_instr);
    } else {
        fprintf(stderr, "kata config load failed.\n");
    }

    // update vCPU number
    args->vcpu_num = result.r1;

    cur_blob = load_data_to_blobs(rim_blobs, kernel_path, KERNEL_FILE, kernel_start);
    if (!cur_blob) {
        gen_err("load kernel to blobs failed");
        goto free;
    }

    cur_blob = load_data_to_blobs(rim_blobs, DEFAULT_DUMPDTB_PATH, DEFAULT_FILE, dtb_start);
    if (!cur_blob) {
        gen_err("add dtb to blobs failed");
        goto free;
    }

    cur_blob = load_loader_to_blobs(rim_blobs, kernel_start, dtb_start, loader_start);
    if (!cur_blob) {
        gen_err("add bootloader to blobs failed");
        goto free;
    }
    return 0;

free:
    free_rim_blobs(rim_blobs);
    return -1;
}

static int build_rim_blobs(blob_list *rim_blobs, tools_args *args)
{
    int ret = -1;
    bool use_firmware = (strlen(args->firmware_path) != 0);
    bool use_kernel = (strlen(args->kernel_path) != 0);
    bool use_kata_config = (strlen(args->kata_config_path) != 0);
    bool use_pod_config = (strlen(args->pod_config_path) != 0);

    if (use_kata_config || use_pod_config) {
        if (use_kata_config ^ use_pod_config) {
            gen_err("only supports booting confidential containers when both kata_config and pod_config are provided.");
            return -1;
        }

        return build_coco_blobs(rim_blobs, args);
    }

    if (!(use_firmware ^ use_kernel)) {
        gen_err("only support boot with kernel or firmware");
        return -1;
    }
    if (strlen(args->dtb_path) == 0) {
        gen_err("should support dtb dump file");
        return -1;
    }
    if (use_kernel) {
        ret = build_kernel_blobs(rim_blobs, args);
    } else {
        ret = build_firmware_blobs(rim_blobs, args);
    }

    return ret;
}

static void print_help(const char *name)
{
    printf("\nUsage:\n");
    printf(" %s [options]...\n\n", name);
    printf("Generate rim reference value, support two three types:\n");
    printf("(a) direct kernel boot without firmware: -k -d [-i] -v -s -m\n");
    printf("(b) firmware-only boot                 : -f -d -v -s -m\n");
    printf("(c) confidential container boot        : -c -p -s -m\n\n");
    printf("Options:\n");
    printf("\t-k/--kernel    kernel_path            :     path to kernel image\n");
    printf("\t-d/--dtb       dtb_path               :     path to device tree dtb file\n");
    printf("\t-i/--initrd    initramfs_path         :     path to initramfs gzip file (optional)\n");
    printf("\t-f/--firmware  firmware_path          :     path to firmware file\n");
    printf("\t-v/--vcpu      vcpu_num               :     Number of Vcpus (must be a positive integer)\n");
    printf("\t-s/--sve       sve_vector_length      :     length of sve vector (must be a multiple of 128)\n");
    printf("\t-m/--pmu       pmu_counter_num        :     number of pmu counter (must be a positive integer)\n");
    printf("\t-c/--config    config_path            :     path to kata runtime config file (configuration.toml)\n");
    printf("\t-p/--pod       pod_path               :     path to k8s pod config file (pod.yaml)\n");
}

static int parse_args(int argc, char *argv[], tools_args *args)
{
    int opt = 0;
    char *const short_opts = "k:i:d:f:v:s:m:h:c:p:";
    struct option const long_opts[] = {
        {"kernel", required_argument, NULL, 'k'},
        {"initrd", required_argument, NULL, 'i'},
        {"dtb", required_argument, NULL, 'd'},
        {"firmware", required_argument, NULL, 'f'},
        {"vcpu", required_argument, NULL, 'v'},
        {"sve", required_argument, NULL, 's'},
        {"pmu", required_argument, NULL, 'm'},
        {"help", required_argument, NULL, 'h'},
        {"config", required_argument, NULL, 'c'},
        {"pod", required_argument, NULL, 'p'},
        {0, 0, 0, 0}};

    if (argc < NO_ARGUMENT) {
        print_help(argv[0]);
        return -1;
    }

    memset(args, 0, sizeof(tools_args));

    while ((opt = getopt_long(argc, argv, short_opts, long_opts, NULL)) != -1) {
        switch (opt) {
            case 'k':
                strncpy(args->kernel_path, optarg, PATH_LEN_MAX - 1);
                break;
            case 'i':
                strncpy(args->initramfs_path, optarg, PATH_LEN_MAX - 1);
                break;
            case 'd':
                strncpy(args->dtb_path, optarg, PATH_LEN_MAX - 1);
                break;
            case 'f':
                strncpy(args->firmware_path, optarg, PATH_LEN_MAX - 1);
                break;
            case 'v':
                args->vcpu_num = atoi(optarg);
                if (args->vcpu_num <= 0) {
                    gen_err("invalid vcpu number %lu", args->vcpu_num);
                    return -1;
                }
                break;
            case 's':
                args->sve_vector_length = atoi(optarg);
                if (args->sve_vector_length < 0 || args->sve_vector_length % SVE_VECTOR_MIN_LEN) {
                    gen_err("invalid sve vector length %d", args->sve_vector_length);
                    return -1;
                }
                break;
            case 'm':
                args->pmu_counter_num = atoi(optarg);
                if (args->pmu_counter_num < 0) {
                    gen_err("invalid pmu counter number %d", args->pmu_counter_num);
                    return -1;
                }
                break;
            case 'c':
                strncpy(args->kata_config_path, optarg, PATH_LEN_MAX - 1);
                break;
            case 'p':
                strncpy(args->pod_config_path, optarg, PATH_LEN_MAX - 1);
                break;
            default:
                print_help(argv[0]);
                return -1;
        }
    }

    return 0;
}

int main(int argc, char *argv[])
{
    tools_args args = {0};
    blob_list rim_blobs = {0};

    if (parse_args(argc, argv, &args)) {
        return -1;
    }

    init_rim_blobs(&rim_blobs);
    if (build_rim_blobs(&rim_blobs, &args)) {
        gen_err("build rim blobs failed");
        return -1;
    }

#if LOG_PRINT
    print_rim_blobs(&rim_blobs);
#endif

    generate_rim_reference(args.vcpu_num, args.sve_vector_length,
                           args.pmu_counter_num, &rim_blobs, strlen(args.firmware_path) != 0);
    free_rim_blobs(&rim_blobs);
    return 0;
}
