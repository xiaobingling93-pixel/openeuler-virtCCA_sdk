#include <arpa/inet.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <strings.h>
#include <sys/socket.h>
#include <unistd.h>
#include <getopt.h>
#include <linux/limits.h>
#include <stdbool.h>
#include <stdint.h>

#include "token_parse.h"
#include "token_validate.h"
#include "utils.h"
#include "common.h"
#include "event_log.h"
#include "firmware_state.h"
#include "binary_blob.h"
#include "verify.h"
#include "config.h"

#include "openssl/rand.h"
#include "openssl/x509.h"
#include "openssl/pem.h"
#include "openssl/ec.h"
#include "openssl/obj_mac.h"

#define MAX_MEASUREMENT_SIZE 64
#define CCEL_ACPI_TABLE_PATH "./ccel.bin"
#define CCEL_EVENT_LOG_PATH "./event_log.bin"
#define HASH_STR_LENGTH 64

/* Global configuration variable definition */
config_t g_config = {
    .ccel_file = CCEL_ACPI_TABLE_PATH,
    .event_log_file = CCEL_EVENT_LOG_PATH,
    .json_file = NULL  /* Will be set from command line */
};

unsigned char challenge[CHALLENGE_SIZE] = {};
unsigned char measurement[MAX_MEASUREMENT_SIZE] = {};
size_t measurement_len = MAX_MEASUREMENT_SIZE;
bool use_firmware = false;
bool dump_eventlog = false;
char* ref_json_file = NULL;
bool use_fde = false;
char* rootfs_key_file = NULL;


/*
/* Certificate format detection function
/* Returns: 0 for DER format, 1 for PEM format, -1 for unknown format
*/
static int detect_cert_format(const unsigned char *cert_data, size_t cert_len)
{
    if (!cert_data || cert_len == 0) {
        return -1;
    }

    /*
    /* Check for PEM format first
    /* PEM certificates start with "-----BEGIN CERTIFICATE-----"
    */
    const char *pem_begin = "-----BEGIN CERTIFICATE-----";
    const char *pem_end = "-----END CERTIFICATE-----";
    
    if (cert_len >= strlen(pem_begin)) {
        if (strncmp((const char*)cert_data, pem_begin, strlen(pem_begin)) == 0) {
            /* Verify it also has the end marker */
            if (strstr((const char*)cert_data, pem_end)) {
                return 1; /* PEM format */
            }
        }
    }

    /*
    /* Check for DER format
    /* DER certificates start with ASN.1 SEQUENCE tag (0x30)
    /* followed by length encoding
    */
    if (cert_len >= 4 && cert_data[0] == 0x30) {
        /* Basic ASN.1 SEQUENCE validation */
        size_t length_bytes = 1;
        size_t total_length = 0;
        
        if (cert_data[1] & 0x80) {
            /* Long form length encoding */
            length_bytes = (cert_data[1] & 0x7F) + 1;
            if (length_bytes > 4 || length_bytes + 1 >= cert_len) {
                return -1; /* Invalid length encoding */
            }
            
            for (size_t i = 0; i < length_bytes - 1; i++) {
                total_length = (total_length << 8) | cert_data[2 + i];
            }
        } else {
            /* Short form length encoding */
            total_length = cert_data[1];
        }
        
        /* Verify the total length makes sense */
        if (total_length + length_bytes + 1 <= cert_len) {
            return 0; /* DER format */
        }
    }

    return -1; /* Unknown format */
}

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

int verify_token(unsigned char *token, size_t token_len)
{
    bool ret;
    cca_token_t cca_token;
    cert_info_t cert_info;

    ret = parse_cca_attestation_token(&cca_token, token, token_len);
    if (ret != VIRTCCA_SUCCESS) {
        printf("Failed to parse attestation token.\n");
        return VERIFY_FAILED;
    }
    print_cca_attestation_token_raw(&cca_token);
    print_cca_attestation_token(&cca_token);

    strcpy(cert_info.cert_path_prefix, DEFAULT_CERT_PEM_PREFIX);
    strcpy(cert_info.root_cert_filename, DEFAULT_ROOT_CERT_PEM_FILENAME);
    strcpy(cert_info.sub_cert_filename, DEFAULT_SUB_CERT_PEM_FILENAME);
    strcpy(cert_info.aik_cert_filename, DEFAULT_AIK_CERT_PEM_FILENAME);
    strcpy(cert_info.root_cert_url, DEFAULT_ROOT_CERT_URL);
    strcpy(cert_info.sub_cert_url, DEFAULT_SUB_CERT_URL);

    /*
     * Support both legacy CVM-only tokens and complete attestation tokens (CVM and Platform)
     * Check if platform token exists to determine verification mode
     */
    if (cca_token.platform_cose.ptr != NULL && cca_token.platform_cose.len > 0) {
        /* Platform token exists - use new verification logic for CVM+Platform tokens */
        ret = verify_cca_token_signatures(&cert_info,
                                          cca_token.platform_cose,
                                          cca_token.cvm_cose,
                                          cca_token.cvm_token.pub_key,
                                          cca_token.platform_token.challenge,
                                          cca_token.cvm_token.pub_key_hash_algo_id);
    } else {
        /*
        /* No platform token - use legacy verification logic for CVM-only tokens
        /* Create empty qbuf_t structures for compatibility
        */
        qbuf_t empty_buf = {.ptr = NULL, .len = 0};
        ret = verify_cca_token_signatures(&cert_info,
                                          empty_buf,  /* platform_cose */
                                          cca_token.cvm_cose,
                                          cca_token.cvm_token.pub_key,
                                          empty_buf,  /* platform challenge */
                                          cca_token.cvm_token.pub_key_hash_algo_id);
        printf("Using legacy CVM-only token verification mode\n");
    }
    if (!ret) {
        return VERIFY_FAILED;
    }

    if (cca_token.cvm_token.challenge.len != CHALLENGE_SIZE ||
        memcmp(cca_token.cvm_token.challenge.ptr, challenge, CHALLENGE_SIZE)) {
        printf("Failed to verify challenge.\n");
        return VERIFY_FAILED;
    }

    if (cca_token.cvm_token.rim.len != measurement_len ||
        memcmp(cca_token.cvm_token.rim.ptr, measurement, measurement_len)) {
        printf("Failed to verify measurement.\n");
        return VERIFY_FAILED;
    }

    if (use_firmware) {
        /* Initialize event log processor */
        event_log_t event_log;
        if (!event_log_init(&event_log, 0, 0)) {
            printf("Error: Failed to initialize event log\n");
            return VERIFY_FAILED;
        }

        /* Replay event log to calculate REM values */
        if (!event_log_replay(&event_log)) {
            printf("Error: Failed to replay event log\n");
            return VERIFY_FAILED;
        }

        /* Verify REM values from token */
        printf("\nVerifying REM values from token...\n");
        bool all_rems_passed = true;
        for (int i = 0; i < REM_COUNT; i++) {
            if (cca_token.cvm_token.rem[i].len != sizeof(rem_t)) {
                printf("Error: Invalid REM[%d] size in token\n", i);
                return VERIFY_FAILED;
            }
            verify_single_rem(i, (rem_t*)cca_token.cvm_token.rem[i].ptr, &event_log.rems[i]);
            if (!rem_compare((rem_t*)cca_token.cvm_token.rem[i].ptr, &event_log.rems[i])) {
                all_rems_passed = false;
            }
        }

        if (!all_rems_passed) {
            printf("\nREM verification failed\n");
            return VERIFY_FAILED;
        }

        printf("\nAll REM values verified successfully\n");

        /* If JSON file is provided, verify firmware state */
        if (ref_json_file) {
            printf("\nVerifying firmware state...\n");
            firmware_log_state_t* state = firmware_log_state_create(&event_log);
            if (!state) {
                printf("Error: Failed to create firmware state\n");
                return VERIFY_FAILED;
            }

            if (!firmware_log_state_extract(&event_log, state)) {
                printf("Error: Failed to extract firmware state\n");
                firmware_log_state_free(state);
                return VERIFY_FAILED;
            }

            if (!verify_firmware_state(ref_json_file, state)) {
                printf("Error: Firmware state verification failed\n");
                firmware_log_state_free(state);
                return VERIFY_FAILED;
            }

            firmware_log_state_free(state);
        }
    }

    return VERIFY_SUCCESS;
}

int save_dev_cert(const char *prefix, const char * filename, const char *dev_cert, const size_t dev_cert_len)
{
    char fullpath[PATH_MAX] = {0};
    FILE *fp = NULL;
    const unsigned char *cert_data = (const unsigned char *)dev_cert;

    snprintf(fullpath, sizeof(fullpath), "%s/%s", prefix, filename);
    fp = fopen(fullpath, "wb");
    if (!fp) {
        printf("Cannot open dev cert file %s\n", fullpath);
        return 1;
    }

    /* Detect certificate format and parse accordingly */
    X509 *cert = NULL;
    int cert_format = detect_cert_format(cert_data, dev_cert_len);
    
    printf("Detected certificate format: ");
    
    if (cert_format == 0) {
        /* DER format */
        printf("DER\n");
        cert = d2i_X509(NULL, &cert_data, dev_cert_len);
        if (!cert) {
            printf("Failed to parse DER certificate\n");
            fclose(fp);
            return 1;
        }
    } else if (cert_format == 1) {
        /* PEM format */
        printf("PEM\n");
        BIO *bio = BIO_new_mem_buf(cert_data, dev_cert_len);
        if (bio) {
            cert = PEM_read_bio_X509(bio, NULL, NULL, NULL);
            BIO_free(bio);
        }
        if (!cert) {
            printf("Failed to parse PEM certificate\n");
            fclose(fp);
            return 1;
        }
    } else {
        /* Unknown format, try both formats as fallback */
        printf("Unknown, trying DER first\n");
        cert = d2i_X509(NULL, &cert_data, dev_cert_len);
        if (!cert) {
            printf("DER failed, trying PEM format\n");
            cert_data = (const unsigned char *)dev_cert;
            BIO *bio = BIO_new_mem_buf(cert_data, dev_cert_len);
            if (bio) {
                cert = PEM_read_bio_X509(bio, NULL, NULL, NULL);
                BIO_free(bio);
            }
        }
        
        if (!cert) {
            printf("Failed to parse certificate in any supported format\n");
            fclose(fp);
            return 1;
        }
    }

    EVP_PKEY *pkey = X509_get_pubkey(cert);
    if (pkey) {
        int key_type = EVP_PKEY_base_id(pkey);
        printf("Device certificate key type: %s\n",
               key_type == EVP_PKEY_RSA ? "RSA" :
               key_type == EVP_PKEY_EC ? "ECC" : "Unknown");
        
        if (key_type == EVP_PKEY_EC) {
            EC_KEY *ec_key = EVP_PKEY_get1_EC_KEY(pkey);
            if (ec_key) {
                const EC_GROUP *group = EC_KEY_get0_group(ec_key);
                if (group) {
                    int curve_nid = EC_GROUP_get_curve_name(group);
                    const char* curve_name = "Unknown";
                    
                    if (curve_nid == NID_secp521r1) {
                        curve_name = "P-521";
                    } else if (curve_nid == NID_secp384r1) {
                        curve_name = "P-384";
#ifdef NID_X9_62_prime256v1
                    } else if (curve_nid == NID_X9_62_prime256v1) {
                        curve_name = "P-256";
#endif
#ifdef NID_secp256r1
                    } else if (curve_nid == NID_secp256r1) {
                        curve_name = "P-256";
#endif
                    }
                    
                    printf("ECC curve: %s (NID: %d)\n", curve_name, curve_nid);
                }
                EC_KEY_free(ec_key);
            }
        }
        EVP_PKEY_free(pkey);
    }

    /* Write certificate in PEM format */
    if (PEM_write_X509(fp, cert) != 1) {
        printf("Failed to write certificate to PEM file\n");
        X509_free(cert);
        fclose(fp);
        return 1;
    }

    printf("Successfully saved device certificate to %s\n", fullpath);
    X509_free(cert);
    fclose(fp);
    return 0;
}

static void print_hex_dump_with_ascii(const uint8_t* data, size_t length)
{
    char ascii_buf[17] = {0};

    printf("=> Read CCEL ACPI Table\n");
    for (size_t i = 0; i < length; i++) {
        if (i % 16 == 0) {
            if (i > 0) {
                printf("  %s\n", ascii_buf);
            }
            printf("%08zX  ", i);
            memset(ascii_buf, 0, sizeof(ascii_buf));
        }
        printf("%02X ", data[i]);
        ascii_buf[i % 16] = isprint(data[i]) ? data[i] : '.';
    }

    /* Process the last line */
    if (length % 16 != 0) {
        for (size_t i = length % 16; i < 16; i++) {
            printf("   ");
        }
    }
    printf("  %s\n", ascii_buf);
}

static void print_acpi_table(const uint8_t* ccel_data, size_t file_size, const acpi_table_info_t* info)
{
    print_hex_dump_with_ascii(ccel_data, file_size);

    printf("Revision:     %d\n", info->revision);
    printf("Length:       %zu\n", file_size);
    printf("Checksum:     %02X\n", info->checksum);
    
    printf("OEM ID:       b'");
    for (int i = 0; i < 6; i++) {
        printf("%c", info->oem_id[i]);
    }
    printf("'\n");

    printf("CC Type:      %d\n", info->cc_type);
    printf("CC Sub-type:  %d\n", info->cc_subtype);
    
    printf("Log Lenght:   0x%08lX\n", (unsigned long)info->log_length);
    printf("Log Address:  0x%08lX\n", (unsigned long)info->log_address);
    printf("\n");
}

static bool parse_acpi_table(const uint8_t* ccel_data, size_t file_size, acpi_table_info_t* info)
{
    if (!ccel_data || !info || file_size < 56) {
        return false;
    }

    if (memcmp(ccel_data, "CCEL", 4) != 0) {
        printf("Error: Invalid CCEL signature\n");
        return false;
    }

    info->revision = ccel_data[8];
    info->checksum = ccel_data[9];
    memcpy(info->oem_id, ccel_data + 10, 6);
    info->cc_type = ccel_data[36];
    info->cc_subtype = ccel_data[37];
    info->log_length = *(uint64_t*)(ccel_data + 40);
    info->log_address = *(uint64_t*)(ccel_data + 48);

    print_acpi_table(ccel_data, file_size, info);

    return true;
}

static int handle_eventlogs_command(void)
{
    size_t file_size;
    uint8_t* ccel_data = read_binary_file(g_config.ccel_file, &file_size);
    if (!ccel_data) {
        return 1;
    }

    acpi_table_info_t table_info;
    if (!parse_acpi_table(ccel_data, file_size, &table_info)) {
        free(ccel_data);
        return 1;
    }

    event_log_t event_log;
    if (!event_log_init(&event_log, (size_t)table_info.log_address, (size_t)table_info.log_length)) {
        printf("Error: Failed to initialize event log\n");
        free(ccel_data);
        return 1;
    }

    event_log_dump(&event_log);

    free(ccel_data);
    return 0;
}

int handle_connect(int sockfd)
{
    int ret;
    int n;
    enum MSG_ID msg_id;
    unsigned char buf[MAX] = {};
    size_t dev_cert_len = 0;

    /* Step 1: Get device certificate */
    msg_id = DEVICE_CERT_MSG_ID;
    write(sockfd, &msg_id, sizeof(msg_id));
    dev_cert_len = read(sockfd, buf, MAX);
    ret = save_dev_cert(DEFAULT_CERT_PEM_PREFIX, DEFAULT_AIK_CERT_PEM_FILENAME, buf, dev_cert_len);
    if (ret != 0) {
        printf("Failed to save device certificate.\n");
        return VERIFY_FAILED;
    }

    /* Step 2: Get attestation token */
    msg_id = ATTEST_MSG_ID;
    RAND_priv_bytes(challenge, CHALLENGE_SIZE);
    memcpy(buf, &msg_id, sizeof(msg_id));
    memcpy(buf + sizeof(msg_id), challenge, CHALLENGE_SIZE);
    write(sockfd, buf, sizeof(msg_id) + CHALLENGE_SIZE);

    unsigned char token[MAX] = {};
    size_t token_len = 0;
    token_len = read(sockfd, token, sizeof(token));

    /* Step 3: If using firmware, get CCEL and event log first */
    if (use_firmware || dump_eventlog) {
        /* Get CCEL ACPI table */
        msg_id = CCEL_ACPI_TABLE_ID;
        write(sockfd, &msg_id, sizeof(msg_id));
        unsigned char ccel_table[MAX] = {};
        size_t ccel_table_len = 0;
        ccel_table_len = read(sockfd, ccel_table, sizeof(ccel_table));
        if (ccel_table_len <= 0) {
            printf("Failed to receive CCEL ACPI table data.\n");
            return VERIFY_FAILED;
        }
        ret = save_file_data(CCEL_ACPI_TABLE_PATH, ccel_table, ccel_table_len);
        if (ret != 0) {
            printf("Failed to save CCEL ACPI table.\n");
            return VERIFY_FAILED;
        }
        
        /* Get CCEL event log */
        msg_id = CCEL_EVENT_LOG_ID;
        write(sockfd, &msg_id, sizeof(msg_id));
        
        /* First read the event log size */
        size_t expected_size = 0;
        ssize_t size_received = read(sockfd, &expected_size, sizeof(size_t));
        if (size_received != sizeof(size_t)) {
            printf("Failed to receive event log size.\n");
            return VERIFY_FAILED;
        }
        
        if (expected_size == 0 || expected_size > MAX_LOG) {
            printf("Invalid event log size: %zu\n", expected_size);
            return VERIFY_FAILED;
        }
        
        printf("Expecting to receive %zu bytes of event log data\n", expected_size);
        
        /* Allocate receive buffer */
        unsigned char *ccel_data = (unsigned char *)malloc(expected_size);
        if (!ccel_data) {
            printf("Failed to allocate memory for event log.\n");
            return VERIFY_FAILED;
        }
        
        /* Loop receiving data until complete */
        size_t total_received = 0;
        while (total_received < expected_size) {
            ssize_t bytes_received = read(sockfd, ccel_data + total_received, expected_size - total_received);
            if (bytes_received <= 0) {
                printf("Failed to receive event log data at offset %zu.\n", total_received);
                free(ccel_data);
                return VERIFY_FAILED;
            }
            total_received += bytes_received;
            printf("Received %zd bytes, total %zu of %zu bytes\n", bytes_received, total_received, expected_size);
        }
        
        ret = save_file_data(CCEL_EVENT_LOG_PATH, ccel_data, expected_size);
        free(ccel_data);
        
        if (ret != 0) {
            printf("Failed to save event log data.\n");
            return VERIFY_FAILED;
        }
        
        printf("Successfully saved complete event log (%zu bytes)\n", expected_size);
    }

    if (dump_eventlog) {
        return handle_eventlogs_command();
    }

    /* Step 4: Verify token and firmware */
    ret = verify_token(token, token_len);

    /* Step 5: Send verification result */
    msg_id = ret == VERIFY_SUCCESS ? VERIFY_SUCCESS_MSG_ID : VERIFY_FAILED_MSG_ID;
    write(sockfd, &msg_id, sizeof(msg_id));

    if (ret != 0) {
        return VERIFY_FAILED;
    }

    /* Send FDE usage information to server */
    msg_id = use_fde ? USE_FDE_MSG_ID : VERIFY_REM_MSG_ID;
    write(sockfd, &msg_id, sizeof(msg_id));

    if (use_fde) {
        printf("Send keyfile for encrypted rootfs.\n");
        size_t key_file_len;
        uint8_t* key_file = read_binary_file(rootfs_key_file, &key_file_len);
        if (!key_file) {
            printf("Failed to read key file data.\n");
            return 1;
        }
        write(sockfd, key_file, key_file_len);
        free(key_file);
    }
    
    return ret;
}

void print_usage(char *name)
{
    printf("Usage: %s [options]\n", name);
    printf("Options:\n");
    printf("\t-i, --ip <ip>                      Listening IP address\n");
    printf("\t-p, --port <port>                  Listening tcp port\n");
    printf("\t-m, --measurement <measurement>    Initial measurement for cVM\n");
    printf("\t-f, --firmware <json>              Enable firmware verification with JSON reference file\n");
    printf("\t-e, --eventlog                     Dump event log\n");
    printf("\t-k, --fdekey <key_file>            Enable Full Disk Encryption with rootfs key file\n");
    printf("\t-h, --help                         Print Help (this message) and exit\n");
}

int main(int argc, char *argv[])
{
    int ret = 1;
    int sockfd, connfd;
    struct sockaddr_in servaddr, cli;

    int ip = htonl(INADDR_LOOPBACK);
    int port = htons(PORT);
    unsigned char *measurement_hex = "";

    int option;
    struct option const long_options[] = {
        { "ip", required_argument, NULL, 'i' },
        { "port", required_argument, NULL, 'p' },
        { "measurement", required_argument, NULL, 'm' },
        { "firmware", required_argument, NULL, 'f'},
        { "eventlog", no_argument, NULL, 'e'},
        { "fdekey", required_argument, NULL, 'k'},
        { "help", no_argument, NULL, 'h' },
        { NULL, 0, NULL, 0 }
    };
    while (1) {
        int option_index = 0;
        option = getopt_long(argc, argv, "i:p:m:f:k:eh", long_options, &option_index);
        if (option == -1) {
            break;
        }
        switch (option) {
            case 'i':
                ip = inet_addr(optarg);
                break;
            case 'p':
                port = htons(atoi(optarg));
                break;
            case 'm':
                measurement_hex = optarg;
                if (hex_to_bytes(measurement_hex, strlen(measurement_hex), measurement, &measurement_len) != 0) {
                    printf("Invalid measurement.\n");
                    exit(1);
                }
                break;
            case 'f':
                if (dump_eventlog) {
                    printf("Error: Cannot use -f and -e together\n");
                    exit(1);
                }
                use_firmware = true;
                ref_json_file = optarg;
                g_config.json_file = optarg;
                break;
            case 'e':
                if (use_firmware) {
                    printf("Error: Cannot use -e and -f together\n");
                    exit(1);
                }
                dump_eventlog = true;
                break;
            case 'k':
                use_fde = true;
                rootfs_key_file = optarg;
                break;
            case 'h':
                print_usage(argv[0]);
                exit(0);
            default:
                fprintf(stderr, "Try '%s --help' for more information.\n", argv[0]);
                exit(1);
        }
    }

    sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd == -1) {
        printf("socket creation failed...\n");
        return ret;
    } else {
        printf("Socket successfully created..\n");
    }
    bzero(&servaddr, sizeof(servaddr));

    servaddr.sin_family = AF_INET;
    servaddr.sin_addr.s_addr = ip;
    servaddr.sin_port = port;

    if (connect(sockfd, (struct sockaddr *)&servaddr, sizeof(servaddr)) != 0) {
        printf("connection with the server failed...\n");
        return ret;
    } else {
        printf("connected to the server..\n");
    }

    ret = handle_connect(sockfd);

    close(sockfd);
    return ret;
}
