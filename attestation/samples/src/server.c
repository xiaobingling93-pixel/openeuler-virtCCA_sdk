#include <stdio.h>
#include <netdb.h>
#include <netinet/in.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <getopt.h>
#include "attestation.h"
#include "common.h"
#include "utils.h"

#define CCEL_ACPI_TABLE_PATH "/sys/firmware/acpi/tables/CCEL"
#define CCEL_EVENT_LOG_PATH "/sys/firmware/acpi/tables/data/CCEL"
#define KEY_FILE_PATH "/root/rootfs_key.bin"
#define MAX 4096
#define PORT 7220

bool use_fde = false;


int handle_connect(int connfd, tsi_ctx *ctx)
{
    int ret;
    unsigned char buff[MAX];
    int n;
    enum MSG_ID msg_id;

    int major, minor;
    ret = get_version(ctx, &major, &minor);
    if (ret != TSI_SUCCESS) {
        printf("Failed to get TSI version.\n");
        return ret;
    }
    printf("TSI version %d.%d advertised\n", major, minor);

    for (;;) {
        bzero(buff, MAX);

        read(connfd, &msg_id, sizeof(msg_id));
        if (msg_id == DEVICE_CERT_MSG_ID) {
            printf("Get device cert.\n");
            unsigned char dev_cert[MAX] = {};
            size_t dev_cert_len = MAX;
            ret = get_dev_cert(ctx, dev_cert, &dev_cert_len);
            if (ret != TSI_SUCCESS) {
                printf("Failed to get TSI version.\n");
                return ret;
            }
            write(connfd, dev_cert, dev_cert_len);
        } else if (msg_id == ATTEST_MSG_ID) {
            printf("Get attestation token.\n");
            unsigned char challenge[CHALLENGE_SIZE] = {};
            read(connfd, challenge, CHALLENGE_SIZE);
            unsigned char token[MAX] = {};
            size_t token_len = MAX;
            ret = get_attestation_token(ctx, challenge, CHALLENGE_SIZE, token, &token_len);
            if (ret != TSI_SUCCESS) {
                printf("Failed to get attestation token.\n");
                return ret;
            }
            write(connfd, token, token_len);
        } else if (msg_id == CCEL_ACPI_TABLE_ID) {
            printf("Get ccel acpi table.\n");
            unsigned char *ccel_table = NULL;
            size_t ccel_table_len = MAX;
            ret = read_file_data(CCEL_ACPI_TABLE_PATH, &ccel_table, &ccel_table_len);
            if (ret != TSI_SUCCESS) {
                printf("Failed to read ccel acpi table.\n");
                return ret;
            }
            write(connfd, ccel_table, ccel_table_len);
        } else if (msg_id == CCEL_EVENT_LOG_ID) {
            printf("Get ccel event log.\n");
            unsigned char *ccel_data = NULL;
            size_t ccel_data_len = 0;
            ret = read_file_data(CCEL_EVENT_LOG_PATH, &ccel_data, &ccel_data_len);
            if (ret != TSI_SUCCESS) {
                printf("Failed to read ccel log data.\n");
                return ret;
            }
            
            /* First send the event log size */
            ssize_t size_sent = write(connfd, &ccel_data_len, sizeof(size_t));
            if (size_sent != sizeof(size_t)) {
                printf("Failed to send event log size.\n");
                free(ccel_data);
                return 1;
            }
            
            /* Loop sending data until complete */
            size_t total_sent = 0;
            while (total_sent < ccel_data_len) {
                ssize_t bytes_sent = write(connfd, ccel_data + total_sent, ccel_data_len - total_sent);
                if (bytes_sent <= 0) {
                    printf("Failed to send event log data at offset %zu.\n", total_sent);
                    free(ccel_data);
                    return 1;
                }
                total_sent += bytes_sent;
                printf("Sent %zd bytes, total %zu of %zu bytes\n", bytes_sent, total_sent, ccel_data_len);
            }
            
            free(ccel_data);
            printf("Successfully sent complete event log (%zu bytes)\n", ccel_data_len);
        } else if (msg_id == VERIFY_SUCCESS_MSG_ID) {
            printf("Succeed to verify!\n");
            ret = VERIFY_SUCCESS;
            
            /* Receive FDE usage information */
            if (read(connfd, &msg_id, sizeof(msg_id)) != sizeof(msg_id)) {
                printf("Failed to receive FDE usage info.\n");
                return VERIFY_FAILED;
            }
            
            use_fde = (msg_id == USE_FDE_MSG_ID);
            if (use_fde) {
                printf("Client indicated FDE is enabled, receiving key file...\n");
                unsigned char key_file[MAX] = {};
                ssize_t key_file_len = 0;
                key_file_len = read(connfd, key_file, sizeof(key_file));
                if (key_file_len <= 0) {
                    printf("Failed to receive key file data.\n");
                    return VERIFY_FAILED;
                }
                ret = save_file_data(KEY_FILE_PATH, key_file, key_file_len);
                if (ret != 0) {
                    printf("Failed to save key file data.\n");
                    return VERIFY_FAILED;
                }
            }
            break;
        } else if (msg_id == VERIFY_FAILED_MSG_ID) {
            printf("Failed to verify!\n");
            ret = VERIFY_FAILED;
            break;
        } else if (msg_id == VERIFY_REM_MSG_ID) {
            printf("Need to verify REM further...\n");
            ret = VERIFY_FAILED;
            break;
        } else {
            ret = VERIFY_FAILED;
            break;
        }
    }

    return ret;
}

void print_usage(char *name)
{
    printf("Usage: %s [options]\n", name);
    printf("Options:\n");
    printf("\t-i, --ip <ip>                      Listening IP address\n");
    printf("\t-p, --port <port>                  Listening tcp port\n");
    printf("\t-k, --fdekey                       Enable Full Disk Encryption with rootfs key file\n");
    printf("\t-h, --help                         Print Help (this message) and exit\n");
}

int main(int argc, char *argv[])
{
    int ret = 1;
    int sockfd, connfd, len;
    struct sockaddr_in servaddr, cli;
    int ip = htonl(INADDR_LOOPBACK);
    int port = htons(PORT);

    int option;
    struct option const long_options[] = {
        { "ip", required_argument, NULL, 'i' },
        { "port", required_argument, NULL, 'p' },
        { "fdekey", no_argument, NULL, 'k'},
        { "help", no_argument, NULL, 'h' },
        { NULL, 0, NULL, 0 }
    };
    while (1) {
        int option_index = 0;
        option = getopt_long(argc, argv, "i:p:kh", long_options, &option_index);
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
            case 'k':
                use_fde = true;
                break;
            case 'h':
                print_usage(argv[0]);
            default:
                fprintf(stderr, "Try '%s --help' for more information.\n", argv[0]);
                exit(1);
        }
    }

    tsi_ctx *ctx = tsi_new_ctx();
    if (ctx == NULL) {
        return 1;
    }

    sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd == -1) {
        printf("socket creation failed...\n");
        goto end;
    } else {
        printf("Socket successfully created..\n");
    }
    bzero(&servaddr, sizeof(servaddr));

    servaddr.sin_family = AF_INET;
    servaddr.sin_addr.s_addr = ip;
    servaddr.sin_port = port;

    if ((bind(sockfd, (struct sockaddr *)&servaddr, sizeof(servaddr))) != 0) {
        printf("socket bind failed...\n");
        goto end;
    } else {
        printf("Socket successfully binded..\n");
    }

    if ((listen(sockfd, 5)) != 0) {
        printf("Listen failed...\n");
        goto end;
    } else {
        printf("Server listening..\n");
    }
    len = sizeof(cli);

    connfd = accept(sockfd, (struct sockaddr *)&cli, &len);
    if (connfd < 0) {
        printf("server accept failed...\n");
        goto end;
    } else {
        printf("server accept the client...\n");
    }

    ret = handle_connect(connfd, ctx);

    close(sockfd);

end:
    tsi_free_ctx(ctx);
    return ret;
}
