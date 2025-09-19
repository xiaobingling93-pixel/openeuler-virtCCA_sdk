#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "event_log.h"
#include "firmware_state.h"

/* Helper function: Extract EFI image information from event data */
static bool extract_efi_image(event_log_entry_t* entry, efi_image_t* image)
{
    if (!entry || !image || !entry->digests || entry->digest_count == 0) {
        return false;
    }

    /* Only extract image hash */
    image->image_hash_size = SHA256_DIGEST_LENGTH;
    image->image_hash = (uint8_t*)malloc(image->image_hash_size);
    if (!image->image_hash) {
        return false;
    }
    memcpy(image->image_hash, entry->digests, image->image_hash_size);
    return true;
}

/* Helper function: Extract GRUB information from event data */
static bool extract_grub_info(event_log_entry_t* entry, grub_state_t* grub)
{
    if (!entry || !grub || !entry->event || entry->event_size == 0) {
        return false;
    }

    /* Check if it's a grub.cfg file */
    const char* grub_cfg = "grub.cfg";
    bool is_grub_cfg = false;
    for (uint32_t i = 0; i < entry->event_size - strlen(grub_cfg); i++) {
        if (memcmp(entry->event + i, grub_cfg, strlen(grub_cfg)) == 0) {
            is_grub_cfg = true;
            break;
        }
    }

    if (!is_grub_cfg) {
        return false;
    }

    /* Extract configuration hash */
    if (entry->digest_count > 0 && entry->digests) {
        grub->config_hash_size = SHA256_DIGEST_LENGTH;
        grub->config_hash = (uint8_t*)malloc(grub->config_hash_size);
        if (!grub->config_hash) {
            return false;
        }
        memcpy(grub->config_hash, entry->digests, grub->config_hash_size);
        return true;
    }

    return false;
}

/* Helper function: Print hexadecimal data */
static void print_hex(const uint8_t* data, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        printf("%02x", data[i]);
    }
}

/* Helper function: Search for substring in data */
static const uint8_t* find_substring(const uint8_t* data, size_t data_len, const char* substr, size_t substr_len)
{
    if (!data || !substr || data_len < substr_len) {
        return NULL;
    }
    
    for (size_t i = 0; i <= data_len - substr_len; i++) {
        if (memcmp(data + i, substr, substr_len) == 0) {
            return data + i;
        }
    }
    return NULL;
}

/* Print firmware state information */
void firmware_log_state_print(const firmware_log_state_t* state)
{
    if (!state) {
        printf("Firmware state is empty\n");
        return;
    }

    printf("\n============ Firmware Log State ============\n");
    printf("Hash Algorithm: 0x%x\n", state->hash_algo);

    /* Print EFI state */
    if (state->efi) {
        printf("\n----- EFI State -----\n");
        printf("Image Count: %u\n", state->efi->image_count);
        for (uint32_t i = 0; i < state->efi->image_count; i++) {
            printf("\nImage[%u]:\n", i);
            if (state->efi->images[i].image_hash) {
                printf("  Hash: ");
                print_hex(state->efi->images[i].image_hash, state->efi->images[i].image_hash_size);
                printf("\n");
            }
        }
    }

    /* Print GRUB conf state */
    if (state->grub) {
        printf("\n----- GRUB conf State -----\n");
        if (state->grub->config_hash) {
            printf("Config Hash: ");
            print_hex(state->grub->config_hash, state->grub->config_hash_size);
            printf("\n");
        }
    }

    /* Print Linux kernel state */
    if (state->linux_kernel) {
        printf("\n----- Linux Kernel State -----\n");
        if (state->linux_kernel->kernel_hash) {
            printf("Kernel Hash: ");
            print_hex(state->linux_kernel->kernel_hash, state->linux_kernel->kernel_hash_size);
            printf("\n");
        }
        if (state->linux_kernel->initrd_hash) {
            printf("Initrd Hash: ");
            print_hex(state->linux_kernel->initrd_hash, state->linux_kernel->initrd_hash_size);
            printf("\n");
        }
    }

    printf("\n=====================================\n");
}

/* Create firmware log state */
firmware_log_state_t* firmware_log_state_create(event_log_t* log)
{
    firmware_log_state_t* state = (firmware_log_state_t*)calloc(1, sizeof(firmware_log_state_t));
    if (!state) {
        return NULL;
    }

    state->efi = (efi_state_t*)calloc(1, sizeof(efi_state_t));
    state->grub = (grub_state_t*)calloc(1, sizeof(grub_state_t));
    state->linux_kernel = (linux_kernel_state_t*)calloc(1, sizeof(linux_kernel_state_t));

    if (!state->efi || !state->grub || !state->linux_kernel) {
        firmware_log_state_free(state);
        return NULL;
    }

    return state;
}

/* Free firmware log state */
void firmware_log_state_free(firmware_log_state_t* state)
{
    if (!state) {
        return;
    }

    if (state->efi) {
        for (uint32_t i = 0; i < state->efi->image_count; i++) {
            free(state->efi->images[i].image_hash);
        }
        free(state->efi->images);
        free(state->efi);
    }

    if (state->grub) {
        free(state->grub->config_hash);
        free(state->grub);
    }

    if (state->linux_kernel) {
        free(state->linux_kernel->kernel_hash);
        free(state->linux_kernel->initrd_hash);
        free(state->linux_kernel);
    }

    free(state->raw_events);
    free(state);
}

/* Extract firmware log state */
bool firmware_log_state_extract(event_log_t* log, firmware_log_state_t* state)
{
    if (!log || !state) {
        return false;
    }

    size_t pos = 0;
    event_log_entry_t entry;
    uint32_t efi_image_count = 0;
    bool has_grub_info = false;
    bool has_kernel_info = false;
    bool has_initrd_info = false;

    /* First pass: Count EFI images */
    while (process_event_log_entry(log, &pos, &entry)) {
        if (entry.event_type == EV_EFI_BOOT_SERVICES_APPLICATION) {
            efi_image_count++;
        }
    }

    /* Allocate EFI image array */
    if (efi_image_count > 0) {
        state->efi->images = (efi_image_t*)calloc(efi_image_count, sizeof(efi_image_t));
        if (!state->efi->images) {
            return false;
        }
    }

    /* Reset position */
    pos = 0;
    uint32_t current_efi_index = 0;

    /* Second pass: Extract detailed information */
    while (process_event_log_entry(log, &pos, &entry)) {
        /* Process EFI images */
        if (entry.event_type == EV_EFI_BOOT_SERVICES_APPLICATION) {
            if (extract_efi_image(&entry, &state->efi->images[current_efi_index])) {
                current_efi_index++;
            }
        /* Process GRUB configuration file */
        } else if (entry.event_type == EV_IPL && !has_grub_info) {
            if (extract_grub_info(&entry, state->grub)) {
                has_grub_info = true;
            }
        /* Process kernel and initrd */
        } else if (entry.event_type == EV_IPL) {
            /* Check if it's a kernel file path */
            if (!has_kernel_info && entry.event && entry.event_size > 0) {
                const char* kernel_path = "/vmlinuz-";
                if (find_substring(entry.event, entry.event_size, kernel_path, strlen(kernel_path)) &&
                    !find_substring(entry.event, entry.event_size, "grub_cmd:", strlen("grub_cmd:"))) {
                    if (entry.digest_count > 0 && entry.digests) {
                        state->linux_kernel->kernel_hash_size = SHA256_DIGEST_LENGTH;
                        state->linux_kernel->kernel_hash = (uint8_t*)malloc(state->linux_kernel->kernel_hash_size);
                        if (state->linux_kernel->kernel_hash) {
                            memcpy(state->linux_kernel->kernel_hash, entry.digests,
                                      state->linux_kernel->kernel_hash_size);
                            has_kernel_info = true;
                        }
                    }
                }
            /* Check if it's an initrd file path */
            } else if (!has_initrd_info && entry.event && entry.event_size > 0) {
                const char* initrd_path = "/initramfs-";
                if (find_substring(entry.event, entry.event_size, initrd_path, strlen(initrd_path)) &&
                    !find_substring(entry.event, entry.event_size, "grub_cmd:", strlen("grub_cmd:"))) {
                    if (entry.digest_count > 0 && entry.digests) {
                        state->linux_kernel->initrd_hash_size = SHA256_DIGEST_LENGTH;
                        state->linux_kernel->initrd_hash = (uint8_t*)malloc(state->linux_kernel->initrd_hash_size);
                        if (state->linux_kernel->initrd_hash) {
                            memcpy(state->linux_kernel->initrd_hash, entry.digests,
                                      state->linux_kernel->initrd_hash_size);
                            has_initrd_info = true;
                        }
                    }
                }
            }
        }

        /* Release memory */
        if (entry.digests) {
            free(entry.digests);
            entry.digests = NULL;
        }
        if (entry.event) {
            free(entry.event);
            entry.event = NULL;
        }
        if (entry.algorithms) {
            free(entry.algorithms);
            entry.algorithms = NULL;
        }
    }

    /* Update state information */
    state->efi->image_count = current_efi_index;
    state->hash_algo = TPM_ALG_SHA256; /* Currently fixed to use SHA256 */

    return true;
}