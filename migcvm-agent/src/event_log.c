#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <openssl/evp.h>
#include <openssl/sha.h>
#include "event_log.h"
#include "config.h"
#include "firmware_state.h"
/* Event log header magic number */
#define EVENT_LOG_MAGIC 0xFFFFFFFF


/* Function declarations */
static const char* get_event_type_string(uint32_t type);
static void print_hex_dump(const uint8_t* data, size_t length, size_t base_addr);
static void update_rem(rem_t* rem, const uint8_t* digest);
static const char* get_algorithm_string(uint16_t algoid);
static int get_digest_size(uint16_t algoid);

/* Event log entry structure */
typedef struct {
    uint32_t magic;
    uint32_t type;
    uint32_t digest_count;
    uint8_t* digests;
    uint32_t event_size;
    uint8_t* event;
} event_log_header_t;

bool process_event_log_entry(event_log_t* log, size_t* pos,
                              event_log_entry_t* entry)
{
    if (!log || !pos || !entry || *pos >= log->blob.length) {
        return false;
    }

    /* Initialize entry */
    memset(entry, 0, sizeof(event_log_entry_t));

    /* Save initial position */
    size_t initial_pos = *pos;

    /* Read event header */
    uint32_t register_index = binary_blob_get_uint32(&log->blob, pos);
    entry->event_type = binary_blob_get_uint32(&log->blob, pos);

    /* Check if reached end of file */
    if (register_index == EVENT_LOG_MAGIC &&
        entry->event_type == EVENT_LOG_MAGIC) {
        return false;
    }

    /* Decrease register_index by 1 to ensure REM index starts from 0 */
    entry->rem_index = register_index > 0 ? register_index - 1 : 0;

    /* Read digest count */
    entry->digest_count = binary_blob_get_uint32(&log->blob, pos);

    /* Special handling for EV_NO_ACTION event */
    if (entry->event_type == EV_NO_ACTION) {
        /* Skip 20 bytes of digest */
        *pos += 20;
        
        /* Read Spec ID Event03 string (24 bytes) */
        uint8_t spec_id[24];
        binary_blob_get_bytes(&log->blob, pos, 24, spec_id);
        
        /* Read algorithm count */
        entry->algorithms_number = binary_blob_get_uint32(&log->blob, pos);
        
        /* Read algorithm information */
        entry->algorithms = (algorithm_info_t*)malloc(entry->algorithms_number * sizeof(algorithm_info_t));
        if (!entry->algorithms) {
            return false;
        }
        
        for (uint32_t i = 0; i < entry->algorithms_number; i++) {
            entry->algorithms[i].algoid = binary_blob_get_uint16(&log->blob, pos);
            entry->algorithms[i].digestsize = binary_blob_get_uint16(&log->blob, pos);
        }
        
        /* Read vendor information size and skip */
        uint8_t vendorsize = binary_blob_get_uint8(&log->blob, pos);
        *pos += vendorsize;
        
        /* Set event size */
        entry->event_size = *pos - initial_pos;
        if (entry->event_size > 0) {
            entry->event = (uint8_t*)malloc(entry->event_size);
            if (entry->event) {
                memcpy(entry->event, log->blob.data + initial_pos, entry->event_size);
            }
        }
        
        return true;
    }

    /* Process other type events */
    if (entry->digest_count > 0) {
        entry->digests = (uint8_t*)malloc(entry->digest_count * SHA256_DIGEST_LENGTH);
        entry->alg_ids = (uint16_t*)malloc(entry->digest_count * sizeof(uint16_t));
        if (!entry->digests || !entry->alg_ids) {
            free(entry->digests);
            free(entry->alg_ids);
            return false;
        }

        /* Read each digest */
        for (uint32_t i = 0; i < entry->digest_count; i++) {
            /* Read algorithm ID */
            entry->alg_ids[i] = binary_blob_get_uint16(&log->blob, pos);
            
            /* Read digest data */
            binary_blob_get_bytes(&log->blob, pos, SHA256_DIGEST_LENGTH,
                                entry->digests + i * SHA256_DIGEST_LENGTH);
        }
    }

    /* Read event data size */
    uint32_t event_data_size = binary_blob_get_uint32(&log->blob, pos);
    
    /* Read event data */
    if (event_data_size > 0) {
        if (event_data_size > 10240) {
            free(entry->digests);
            free(entry->alg_ids);
            entry->digests = NULL;
            entry->alg_ids = NULL;
            return false;
        }
    }

    /* Set total event size (including header, digest, and event data) */
    entry->event_size = *pos - initial_pos + event_data_size;

    /* Allocate and save complete event data */
    if (entry->event_size > 0) {
        entry->event = (uint8_t*)malloc(entry->event_size);
        if (!entry->event) {
            free(entry->digests);
            free(entry->alg_ids);
            entry->digests = NULL;
            entry->alg_ids = NULL;
            return false;
        }

        /* Copy header and digest data */
        memcpy(entry->event, log->blob.data + initial_pos, *pos - initial_pos);

        /* Copy event data */
        if (event_data_size > 0) {
            binary_blob_get_bytes(&log->blob, pos, event_data_size,
                                entry->event + (*pos - initial_pos));
        }
    }

    return true;
}

static void update_rem(rem_t* rem, const uint8_t* digest)
{
    uint8_t hash[SHA256_DIGEST_LENGTH];
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) {
        printf("Error: Failed to create EVP context\n");
        return;
    }

    if (EVP_DigestInit_ex(ctx, EVP_sha256(), NULL) != 1) {
        printf("Error: Failed to initialize SHA256\n");
        EVP_MD_CTX_free(ctx);
        return;
    }

    /* Update REM data */
    if (EVP_DigestUpdate(ctx, rem->data, REM_LENGTH_BYTES) != 1) {
        printf("Error: Failed to update REM data\n");
        EVP_MD_CTX_free(ctx);
        return;
    }

    /* Update digest data */
    if (EVP_DigestUpdate(ctx, digest, SHA256_DIGEST_LENGTH) != 1) {
        printf("Error: Failed to update digest data\n");
        EVP_MD_CTX_free(ctx);
        return;
    }

    /* Get final hash value */
    unsigned int hash_len;
    if (EVP_DigestFinal_ex(ctx, hash, &hash_len) != 1) {
        printf("Error: Failed to finalize hash\n");
        EVP_MD_CTX_free(ctx);
        return;
    }

    /* Copy hash value to REM */
    memcpy(rem->data, hash, REM_LENGTH_BYTES);

    EVP_MD_CTX_free(ctx);
}

bool event_log_init(event_log_t* log, size_t base, size_t length)
{
    if (!log) {
        return false;
    }

    /* Read event log data from file */
    size_t file_size;
    uint8_t* data = read_file_data(g_config.event_log_file, &file_size);
    if (!data) {
        return false;
    }

    /* Initialize binary blob */
    if (!binary_blob_init(&log->blob, data, file_size, base)) {
        printf("Error: Failed to initialize binary blob\n");
        free(data);
        return false;
    }

    log->log_base = base;
    log->log_length = file_size;

    /* Initialize all REM values to 0 */
    for (int i = 0; i < REM_COUNT; i++) {
        rem_init(&log->rems[i]);
    }

    return true;
}

static void print_hex_dump(const uint8_t* data, size_t length, size_t base_addr)
{
    char ascii_buf[17] = {0};

    for (size_t i = 0; i < length; i++) {
        if (i % 16 == 0) {
            if (i > 0) {
                printf("  %s\n", ascii_buf);
            }
            if (base_addr) {
                printf("%08zX  ", base_addr + i);
            } else {
                printf("%08zX  ", i);
            }
            memset(ascii_buf, 0, sizeof(ascii_buf));
        }
        printf("%02X ", data[i]);
        ascii_buf[i % 16] = isprint(data[i]) ? data[i] : '.';
    }

    /* Process last line */
    if (length % 16 != 0) {
        /* Pad with spaces */
        for (size_t i = length % 16; i < 16; i++) {
            printf("   ");
        }
    }
    printf("  %s\n", ascii_buf);
}

/* Move function definitions here */
static const char* get_event_type_string(uint32_t type)
{
    switch (type) {
        case EV_PREBOOT_CERT: return "EV_PREBOOT_CERT";
        case EV_POST_CODE: return "EV_POST_CODE";
        case EV_UNUSED: return "EV_UNUSED";
        case EV_NO_ACTION: return "EV_NO_ACTION";
        case EV_SEPARATOR: return "EV_SEPARATOR";
        case EV_ACTION: return "EV_ACTION";
        case EV_EVENT_TAG: return "EV_EVENT_TAG";
        case EV_S_CRTM_CONTENTS: return "EV_S_CRTM_CONTENTS";
        case EV_S_CRTM_VERSION: return "EV_S_CRTM_VERSION";
        case EV_CPU_MICROCODE: return "EV_CPU_MICROCODE";
        case EV_PLATFORM_CONFIG_FLAGS: return "EV_PLATFORM_CONFIG_FLAGS";
        case EV_TABLE_OF_DEVICES: return "EV_TABLE_OF_DEVICES";
        case EV_COMPACT_HASH: return "EV_COMPACT_HASH";
        case EV_IPL: return "EV_IPL";
        case EV_IPL_PARTITION_DATA: return "EV_IPL_PARTITION_DATA";
        case EV_NONHOST_CODE: return "EV_NONHOST_CODE";
        case EV_NONHOST_CONFIG: return "EV_NONHOST_CONFIG";
        case EV_NONHOST_INFO: return "EV_NONHOST_INFO";
        case EV_OMIT_BOOT_DEVICE_EVENTS: return "EV_OMIT_BOOT_DEVICE_EVENTS";
        case EV_EFI_VARIABLE_DRIVER_CONFIG: return "EV_EFI_VARIABLE_DRIVER_CONFIG";
        case EV_EFI_VARIABLE_BOOT: return "EV_EFI_VARIABLE_BOOT";
        case EV_EFI_BOOT_SERVICES_APPLICATION: return "EV_EFI_BOOT_SERVICES_APPLICATION";
        case EV_EFI_BOOT_SERVICES_DRIVER: return "EV_EFI_BOOT_SERVICES_DRIVER";
        case EV_EFI_RUNTIME_SERVICES_DRIVER: return "EV_EFI_RUNTIME_SERVICES_DRIVER";
        case EV_EFI_GPT_EVENT: return "EV_EFI_GPT_EVENT";
        case EV_EFI_ACTION: return "EV_EFI_ACTION";
        case EV_EFI_PLATFORM_FIRMWARE_BLOB: return "EV_EFI_PLATFORM_FIRMWARE_BLOB";
        case EV_EFI_HANDOFF_TABLES: return "EV_EFI_HANDOFF_TABLES";
        case EV_EFI_VARIABLE_AUTHORITY: return "EV_EFI_VARIABLE_AUTHORITY";
        default: return "UNKNOWN";
    }
}

/* Add function to get algorithm name */
static const char* get_algorithm_string(uint16_t algoid)
{
    switch(algoid) {
        case TPM_ALG_ERROR: return "TPM_ALG_ERROR";
        case TPM_ALG_RSA: return "TPM_ALG_RSA";
        case TPM_ALG_SHA1: return "TPM_ALG_SHA1";
        case TPM_ALG_SHA256: return "TPM_ALG_SHA256";
        case TPM_ALG_SHA384: return "TPM_ALG_SHA384";
        case TPM_ALG_SHA512: return "TPM_ALG_SHA512";
        case TPM_ALG_ECDSA: return "TPM_ALG_ECDSA";
        default: return "UNKNOWN";
    }
}

/* Add function to get digest length */
static int get_digest_size(uint16_t algoid)
{
    switch(algoid) {
        case TPM_ALG_SHA1: return 20;
        case TPM_ALG_SHA256: return 32;
        case TPM_ALG_SHA384: return 48;
        case TPM_ALG_SHA512: return 64;
        default: return 0;
    }
}

bool event_log_process(event_log_t* log)
{
    if (!log) {
        return false;
    }

    printf("=> Read Event Log Data - Address: 0x%zX(0x%zX)\n",
           log->log_base, log->log_length);

    size_t pos = 0;
    event_log_entry_t entry = {0};
    int entry_count = 0;

    while (pos < log->blob.length) {
        if (!process_event_log_entry(log, &pos, &entry)) {
            break;
        }

        printf("\n==== VCCA Event Log Entry - %d [0x%zX] ====\n",
               entry_count, log->log_base + pos - entry.event_size);
        /* REM index */
        printf("REM               : %d\n", entry.rem_index);
        printf("Type              : 0x%X (%s)\n", entry.event_type,
               get_event_type_string(entry.event_type));
        printf("Length            : %d\n", entry.event_size);

        if (entry.event_type == 0x3) { /* EV_NO_ACTION */
            printf("Algorithms Number : %d\n", entry.algorithms_number);
            for (uint32_t i = 0; i < entry.algorithms_number; i++) {
                printf("  Algorithms[0x%X] Size: %d\n",
                       entry.algorithms[i].algoid,
                       entry.algorithms[i].digestsize * 8);
            }
        }

        if (entry.digest_count > 0) {
            printf("Algorithms ID     : %d (%s)\n",
                   entry.alg_ids[0],
                   get_algorithm_string(entry.alg_ids[0]));
            
            int digest_size = get_digest_size(entry.alg_ids[0]);
            if (digest_size > 0) {
                printf("Digest[0] :\n");
                print_hex_dump(entry.digests, digest_size, 0);
            }
        }

        if (entry.event_size > 0 && entry.event) {
            printf("RAW DATA: ----------------------------------------------\n");
            print_hex_dump(entry.event, entry.event_size,
                         log->log_base + pos - entry.event_size);
            printf("RAW DATA: ----------------------------------------------\n");
        }

        /* Free memory */
        if (entry.digests) {
            free(entry.digests);
            entry.digests = NULL;
        }
        if (entry.alg_ids) {
            free(entry.alg_ids);
            entry.alg_ids = NULL;
        }
        if (entry.event) {
            free(entry.event);
            entry.event = NULL;
        }
        if (entry.algorithms) {
            free(entry.algorithms);
            entry.algorithms = NULL;
        }
        entry_count++;
    }

    return true;
}

bool event_log_replay(event_log_t* log)
{
    if (!log) {
        return false;
    }

    size_t pos = 0;
    event_log_entry_t entry = {0};
    bool success = true;

    printf("\n=> Replay Rolling Hash - REM\n");

    /* Initialize all REM values to 0 */
    for (int i = 0; i < REM_COUNT; i++) {
        rem_init(&log->rems[i]);
    }

    /* Create firmware state object */
    firmware_log_state_t* firmware_state = firmware_log_state_create(log);
    if (!firmware_state) {
        printf("Error: Failed to create firmware state\n");
        return false;
    }

    /* First pass: Process EV_NO_ACTION events */
    while (pos < log->blob.length) {
        if (!process_event_log_entry(log, &pos, &entry)) {
            break;
        }

        /* Check if reached end of file */
        if (entry.rem_index == EVENT_LOG_MAGIC &&
            entry.event_type == EVENT_LOG_MAGIC) {
            break;
        }

        if (entry.event_type == 0x3) { /* EV_NO_ACTION */
            if (entry.rem_index < REM_COUNT && entry.digest_count > 0) {
                update_rem(&log->rems[entry.rem_index], entry.digests);
            }
        }

        /* Free memory */
        if (entry.digests) {
            free(entry.digests);
            entry.digests = NULL;
        }
        if (entry.event) {
            free(entry.event);
            entry.event = NULL;
        }
    }

    /* Reset position */
    pos = 0;

    /* Second pass: Process other events */
    while (pos < log->blob.length) {
        if (!process_event_log_entry(log, &pos, &entry)) {
            break;
        }

        /* Check if reached end of file */
        if (entry.rem_index == EVENT_LOG_MAGIC &&
            entry.event_type == EVENT_LOG_MAGIC) {
            break;
        }

        if (entry.event_type != 0x3) { /* Non EV_NO_ACTION */
            if (entry.rem_index < REM_COUNT && entry.digest_count > 0) {
                update_rem(&log->rems[entry.rem_index], entry.digests);
            }
        }

        /* Free memory */
        if (entry.digests) {
            free(entry.digests);
            entry.digests = NULL;
        }
        if (entry.event) {
            free(entry.event);
            entry.event = NULL;
        }
    }

    /* Print final REM values */
    for (int i = 0; i < REM_COUNT; i++) {
        printf("\n==== REM[%d] ====\n", i);
        print_hex_dump(log->rems[i].data, REM_LENGTH_BYTES, 0);
    }

    /* Extract firmware state information */
    if (!firmware_log_state_extract(log, firmware_state)) {
        printf("Warning: Failed to extract complete firmware state\n");
        success = false;
    } else {
        /* Print firmware state information */
        firmware_log_state_print(firmware_state);
    }

    /* Free firmware state object */
    firmware_log_state_free(firmware_state);

    return success;
}

void event_log_dump(event_log_t* log)
{
    if (!log) {
        return;
    }

    printf("Event log base: 0x%zX, length: 0x%zX\n", log->log_base, log->log_length);
    printf("Actual data size: %zu bytes\n\n", log->blob.length);

    event_log_process(log);
    printf("\n");  /* Add empty line */
    event_log_replay(log);
}