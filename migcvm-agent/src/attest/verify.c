/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <ctype.h>
#include "config.h"
#include "binary_blob.h"
#include "event_log.h"
#include "firmware_state.h"
#include "verify.h"

/* Length of REM value read from rem.txt file (each value is 32 bytes, represented as 64 hex characters) */
#define REM_HEX_LENGTH 64
#define HASH_STR_LENGTH 64

/* Forward declarations of all static functions */
static bool hex_str_to_bytes(const char* hex_str, uint8_t* bytes, size_t length);
static void bytes_to_hex_string(const uint8_t* bytes, size_t len, char* hex_str);
static bool parse_json_file(const char* filename, firmware_reference_t* ref);
static void free_firmware_reference(firmware_reference_t* ref);
static bool compare_and_print_hash(const char* component_name, const char* ref_hash,
                                   const uint8_t* actual_hash, size_t hash_size);
static char* extract_json_string(const char* json, const char* key);

static bool hex_str_to_bytes(const char* hex_str, uint8_t* bytes, size_t length)
{
    if (!hex_str || !bytes || strlen(hex_str) != length * 2) {
        return false;
    }

    for (size_t i = 0; i < length; i++) {
        char hex[3] = {hex_str[i * 2], hex_str[i * 2 + 1], 0};
        unsigned int value;
        if (sscanf(hex, "%02x", &value) != 1) {
            return false;
        }
        bytes[i] = (uint8_t)value;
    }
    return true;
}

bool read_token_rem(rem_t rems[REM_COUNT])
{
    /* Read REM file content */
    size_t file_size;
    char* file_content = read_text_file(g_config.rem_file, &file_size);
    if (!file_content) {
        return false;
    }

    char* line = file_content;
    int rem_index = 0;
    bool success = false;

    /* Process each line */
    while (line && rem_index < REM_COUNT) {
        /* Find end of line */
        char* newline = strchr(line, '\n');
        if (newline) {
            *newline = '\0';
        }

        /* Find REM marker */
        char* pos = strstr(line, "REM[");
        if (pos) {
            /* Find the REM value hex string */
            pos = strchr(line, ':');
            if (pos) {
                pos++; /* Skip colon */

                /* Skip spaces */
                while (*pos == ' ') {
                    pos++;
                }

                /* Convert hex string to byte array */
                if (!hex_str_to_bytes(pos, rems[rem_index].data, REM_LENGTH_BYTES)) {
                    printf("Error: Failed to parse REM[%d] value\n", rem_index);
                    goto cleanup;
                }

                rem_index++;
            }
        }

        /* Move to next line */
        line = newline ? newline + 1 : NULL;
    }

    success = (rem_index == REM_COUNT);

cleanup:
    free(file_content);
    return success;
}

void verify_single_rem(int rem_index, const rem_t* rem1, const rem_t* rem2)
{
    if (!rem1 || !rem2) {
        printf("Error: Invalid REM pointers for verification\n");
        return;
    }

    if (rem_compare(rem1, rem2)) {
        printf("REM[%d] passed the verification.\n", rem_index);
        printf("Expected: ");
        rem_dump(rem1);
        printf("Got:      ");
        rem_dump(rem2);
    } else {
        printf("REM[%d] did not pass the verification\n", rem_index);
        printf("Expected: ");
        rem_dump(rem1);
        printf("Got:      ");
        rem_dump(rem2);
    }
}

bool verify_firmware_state(const char* json_file, const firmware_log_state_t* state)
{
    if (!json_file || !state) {
        return false;
    }

    firmware_reference_t ref = {0};
    bool result = false;

    /* Parse JSON file */
    if (!parse_json_file(json_file, &ref)) {
        printf("Error: Failed to parse JSON file\n");
        return false;
    }

    /* Verify hash algorithm */
    if (strcmp(ref.hash_alg, "sha-256") != 0) {
        printf("Error: Unsupported hash algorithm: %s\n", ref.hash_alg);
        goto cleanup;
    }

    printf("\nVerifying firmware components...\n");

    /* Verify EFI state (grub) */
    if (state->efi && state->efi->image_count > 0) {
        bool found_match = false;
        for (uint32_t i = 0; i < state->efi->image_count; i++) {
            if (compare_and_print_hash("GRUB", ref.grub,
                state->efi->images[i].image_hash,
                state->efi->images[i].image_hash_size)) {
                found_match = true;
                break;
            }
        }
        if (!found_match) {
            goto cleanup;
        }
    }

    /* Verify GRUB configuration */
    if (state->grub && state->grub->config_hash) {
        if (!compare_and_print_hash("GRUB config", ref.grub_cfg,
            state->grub->config_hash,
            state->grub->config_hash_size)) {
            goto cleanup;
        }
    }

    /* Verify kernel and initramfs - match any kernel version */
    if (state->linux_kernel) {
        bool kernel_match = false;
        
        /* Try to match against any kernel version in the reference */
        for (int i = 0; i < ref.kernel_count; i++) {
            bool version_match = true;
            
            /* Check kernel hash if available */
            if (state->linux_kernel->kernel_hash) {
                if (!ref.kernels[i].kernel) {
                    printf("FAILED: Kernel hash exists but reference is missing\n");
                    version_match = false;
                } else if (!compare_and_print_hash("Kernel", ref.kernels[i].kernel,
                    state->linux_kernel->kernel_hash,
                    state->linux_kernel->kernel_hash_size)) {
                    version_match = false;
                }
            }
            
            /* Check initramfs hash if available */
            if (version_match && state->linux_kernel->initrd_hash) {
                if (!ref.kernels[i].initramfs) {
                    printf("FAILED: Initramfs hash exists but reference is missing\n");
                    version_match = false;
                } else if (!compare_and_print_hash("Initramfs", ref.kernels[i].initramfs,
                    state->linux_kernel->initrd_hash,
                    state->linux_kernel->initrd_hash_size)) {
                    version_match = false;
                }
            }
            
            /* If this version matches, we're done */
            if (version_match) {
                if (ref.kernels[i].version) {
                    printf("Matched kernel version: %s\n", ref.kernels[i].version);
                }
                kernel_match = true;
                break;
            }
        }
        
        /* If no kernel matched, verification fails */
        if (!kernel_match) {
            goto cleanup;
        }
    }

    printf("\nAll firmware components verification passed\n");
    result = true;

cleanup:
    free_firmware_reference(&ref);
    return result;
}


/* Helper function: Convert byte array to hex string */
static void bytes_to_hex_string(const uint8_t* bytes, size_t len, char* hex_str)
{
    for (size_t i = 0; i < len; i++) {
        sprintf(hex_str + (i * 2), "%02x", bytes[i]);
    }
}

/* Helper function: Extract string value from JSON */
static char* extract_json_string(const char* json, const char* key)
{
    char* value = NULL;
    char search_key[64];
    snprintf(search_key, sizeof(search_key), "\"%s\":", key);
    
    char* pos = strstr(json, search_key);
    if (pos) {
        pos = strchr(pos + strlen(search_key), '"');
        if (pos) {
            pos++; /* Skip quote */
            char* end = strchr(pos, '"');
            if (end) {
                size_t len = end - pos;
                value = (char*)malloc(len + 1);
                if (value) {
                    strncpy(value, pos, len);
                    value[len] = '\0';
                }
            }
        }
    }
    return value;
}

/* Helper function: Parse JSON file */
static bool parse_json_file(const char* filename, firmware_reference_t* ref)
{
    if (!filename || !ref) {
        return false;
    }

    size_t file_size;
    char* json_content = read_text_file(filename, &file_size);
    if (!json_content) {
        return false;
    }

    /* Initialize kernels array */
    ref->kernels = NULL;
    ref->kernel_count = 0;

    ref->grub = extract_json_string(json_content, "grub");
    ref->grub_cfg = extract_json_string(json_content, "grub.cfg");
    ref->hash_alg = extract_json_string(json_content, "hash_alg");
    
    /* Parse kernels array */
    char* kernels_start = strstr(json_content, "\"kernels\":");
    if (kernels_start) {
        kernels_start = strchr(kernels_start, '[');
        if (kernels_start) {
            char* kernels_end = strchr(kernels_start, ']');
            if (kernels_end) {
                /* Count number of kernel objects */
                char* ptr = kernels_start;
                while (ptr < kernels_end) {
                    if (*ptr == '{') {
                        ref->kernel_count++;
                    }
                    ptr++;
                }
                
                if (ref->kernel_count > 0) {
                    /* Allocate memory for kernel objects */
                    ref->kernels = (kernel_version_t*)calloc(ref->kernel_count, sizeof(kernel_version_t));
                    if (!ref->kernels) {
                        goto error;
                    }
                    
                    /* Extract each kernel object */
                    int idx = 0;
                    ptr = kernels_start;
                    while (ptr < kernels_end && idx < ref->kernel_count) {
                        ptr = strchr(ptr, '{');
                        if (!ptr || ptr >= kernels_end) break;
                        
                        char* obj_end = strchr(ptr, '}');
                        if (!obj_end || obj_end >= kernels_end) break;
                        
                        /* Extract temporary JSON object */
                        size_t obj_len = obj_end - ptr + 1;
                        char* obj_json = (char*)malloc(obj_len + 1);
                        if (!obj_json) break;
                        
                        strncpy(obj_json, ptr, obj_len);
                        obj_json[obj_len] = '\0';
                        
                        /* Parse kernel version object */
                        ref->kernels[idx].version = extract_json_string(obj_json, "version");
                        ref->kernels[idx].kernel = extract_json_string(obj_json, "kernel");
                        ref->kernels[idx].initramfs = extract_json_string(obj_json, "initramfs");
                        
                        free(obj_json);
                        idx++;
                        ptr = obj_end + 1;
                    }
                }
            }
        }
    }
    
    free(json_content);
    return (ref->grub && ref->grub_cfg && ref->hash_alg && ref->kernel_count > 0);

error:
    free(json_content);
    free_firmware_reference(ref);
    return false;
}

/* Helper function: Free JSON parsing results */
static void free_firmware_reference(firmware_reference_t* ref)
{
    if (!ref) {
        return;
    }
    free(ref->grub);
    free(ref->grub_cfg);
    free(ref->hash_alg);
    
    /* Free kernel version data */
    if (ref->kernels) {
        for (int i = 0; i < ref->kernel_count; i++) {
            free(ref->kernels[i].version);
            free(ref->kernels[i].kernel);
            free(ref->kernels[i].initramfs);
        }
        free(ref->kernels);
        ref->kernels = NULL;
    }
    ref->kernel_count = 0;
}

/* Helper function: Compare hash value and print result */
static bool compare_and_print_hash(const char* component_name, const char* ref_hash,
                                   const uint8_t* actual_hash, size_t hash_size)
{
    if (!ref_hash || !actual_hash) {
        return false;
    }
    
    char actual_hex[HASH_STR_LENGTH + 1] = {0};
    bytes_to_hex_string(actual_hash, hash_size, actual_hex);
    
    bool match = (strncmp(ref_hash, actual_hex, HASH_STR_LENGTH) == 0);
    printf("\n%s verification %s\n", component_name, match ? "passed" : "failed");
    printf("Expected: %s\n", ref_hash);
    printf("Got:      %s\n", actual_hex);
    return match;
}