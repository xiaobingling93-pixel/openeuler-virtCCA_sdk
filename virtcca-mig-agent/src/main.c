/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */

#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <strings.h>
#include <getopt.h>
#include <fcntl.h>
#include <errno.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#include "mig_thread.h"
#include "tmi.h"
#include "tls_core.h"
#include "integrity_check_handler.h"

/*
 * parse_input
 *  -c client_ip        : remote server ip
 *  -s server_ip        : local server ip
 *  -a cpu_affinity     : thread cpu affinity
 *
 * default: client_ip = "127.0.0.1", server_ip = "127.0.0.1", cpu_affinity = "0-15"
 */
static void parse_input(int argc, char* argv[], struct input_params *params)
{
    int opt;
    char *client_ip = NULL;
    char *server_ip = NULL;
    char *cpu_affinity = NULL;

    client_ip = strdup("127.0.0.1");
    if (!client_ip) {
        perror("strdup for client_ip");
        exit(EXIT_FAILURE);
    }

    server_ip = strdup("127.0.0.1");
    if (!server_ip) {
        perror("strdup for server_ip");
        free(client_ip);
        exit(EXIT_FAILURE);
    }

    while ((opt = getopt(argc, argv, "c:s:a:")) != -1) {
        switch (opt) {
            case 'c':
                if (!optarg) {
                    fprintf(stderr, "Missing argument for -c\n");
                    goto cleanup_error;
                }
                free(client_ip);
                client_ip = strdup(optarg);
                if (!client_ip) {
                    perror("Failed to allocate memory for client_ip");
                    goto cleanup_error;
                }
                break;
            case 's':
                if (!optarg) {
                    fprintf(stderr, "Missing argument for -s\n");
                    goto cleanup_error;
                }
                free(server_ip);
                server_ip = strdup(optarg);
                if (!server_ip) {
                    perror("Failed to allocate memory for server_ip");
                    goto cleanup_error;
                }
                break;
            case 'a':
                if (!optarg) {
                    fprintf(stderr, "Missing argument for -a\n");
                    goto cleanup_error;
                }
                cpu_affinity = strdup(optarg);
                if (!cpu_affinity) {
                    perror("Failed to allocate memory for cpu_affinity");
                    goto cleanup_error;
                }
                break;
            default:
                fprintf(stderr, "Usage: %s [-c client_ip] [-s server_ip] [-a cpu_affinity]\n",
                        argv[0]);
                goto cleanup_error;
        }
    }

    params->client_ip = client_ip;
    params->server_ip = server_ip;
    if (cpu_affinity) {
        int n = sscanf(cpu_affinity, "%d-%d", &params->cpu_start, &params->cpu_end);
        if (n != 2) {
            perror("Failed to parse params for cpu_affinity");
            goto cleanup_error;
        }
        if (params->cpu_start < 0 ||
            params->cpu_end < 0 ||
            params->cpu_end < params->cpu_start + IO_THREAD_NUM - 1) {
            printf("Cpu range should be positive and at least %d CPUs be provided.\n", IO_THREAD_NUM);
            goto cleanup_error;
        }
    } else {
        params->cpu_start = 1;
        params->cpu_end = IO_THREAD_NUM;
    }

    return;

cleanup_error:
    if (client_ip) {
        free(client_ip);
    }
    if (server_ip) {
        free(server_ip);
    }

    exit(EXIT_FAILURE);
}

int main(int argc, char *argv[])
{
    int ret = 0;
    pthread_t server_thread;
    pthread_t client_thread;
    struct input_params params = {0};
    struct mig_thread_args *client_args = NULL;
    struct mig_thread_args *server_args = NULL;

    parse_input(argc, argv, &params);

    server_args = (struct mig_thread_args *)calloc(1, sizeof(struct mig_thread_args));
    if (!server_args) {
        printf("Failed to alloc memory\n");
        ret = -1;
        goto cleanup;
    }
    client_args = (struct mig_thread_args *)calloc(1, sizeof(struct mig_thread_args));
    if (!client_args) {
        printf("Failed to alloc memory\n");
        ret = -1;
        goto cleanup;
    }

    client_args->ip = strdup(params.client_ip);
    client_args->port = DEFAULT_PORT;
    client_args->cpu_start = params.cpu_start;
    client_args->cpu_end = params.cpu_end;
    server_args->ip = strdup(params.server_ip);
    server_args->port = DEFAULT_PORT;
    server_args->cpu_start = params.cpu_start;
    server_args->cpu_end = params.cpu_end;

    printf("Starting server thread with listen IP: %s\n", server_args->ip);
    printf("Starting client thread with peer IP:   %s\n", client_args->ip);

    if (pthread_create(&server_thread, NULL, virtcca_mig_server_thread_func, server_args) != 0) {
        perror("pthread_create server");
        ret = -1;
        goto cleanup;
    }

    if (pthread_create(&client_thread, NULL, virtcca_mig_client_thread_func, client_args) != 0) {
        perror("pthread_create client");
        pthread_join(server_thread, NULL);
        ret = -1;
        goto cleanup;
    }

    pthread_join(server_thread, NULL);
    pthread_join(client_thread, NULL);

cleanup:
    if (server_args)
        free(server_args);
    if (client_args)
        free(client_args);
    if (params.client_ip)
        free(params.client_ip);
    if (params.server_ip)
        free(params.server_ip);

    return ret;
}