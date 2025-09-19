#ifndef FIRMWARE_STATE_H
#define FIRMWARE_STATE_H

#include <stdint.h>
#include <stdbool.h>
#include "event_log.h"

/* EFI state structure */
typedef struct {
    uint8_t* image_hash;
    uint32_t image_hash_size;
    char* image_path;
} efi_image_t;

typedef struct {
    efi_image_t* images;
    uint32_t image_count;
} efi_state_t;

/* GRUB conf state structure */
typedef struct {
    uint8_t* config_hash;
    uint32_t config_hash_size;
} grub_state_t;

/* Linux kernel state structure */
typedef struct {
    uint8_t* kernel_hash;
    uint32_t kernel_hash_size;
    uint8_t* initrd_hash;
    uint32_t initrd_hash_size;
} linux_kernel_state_t;

/* Firmware log state structure */
typedef struct {
    efi_state_t* efi;
    grub_state_t* grub;
    linux_kernel_state_t* linux_kernel;
    event_log_entry_t* raw_events;
    uint32_t raw_events_count;
    uint16_t hash_algo;
} firmware_log_state_t;

/* JSON parsing state */
typedef struct kernel_version_data {
    char* version;
    char* kernel;
    char* initramfs;
} kernel_version_t;

typedef struct {
    char* grub;
    char* grub_cfg;
    kernel_version_t* kernels;
    int kernel_count;
    char* hash_alg;
} firmware_reference_t;

/* ACPI table parsing structure */
typedef struct {
    uint8_t revision;
    uint8_t checksum;
    char oem_id[6];
    uint8_t cc_type;
    uint8_t cc_subtype;
    uint64_t log_length;
    uint64_t log_address;
} acpi_table_info_t;

/* Function declarations */
firmware_log_state_t* firmware_log_state_create(event_log_t* log);
void firmware_log_state_free(firmware_log_state_t* state);
bool firmware_log_state_extract(event_log_t* log, firmware_log_state_t* state);
void firmware_log_state_print(const firmware_log_state_t* state);

#endif /* FIRMWARE_STATE_H */