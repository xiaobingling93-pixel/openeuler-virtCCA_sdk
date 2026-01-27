#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <fcntl.h>
#include <errno.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#include "mig_thread.h"
#include "tmi.h"
#include "tls_core.h"

struct mig_thread g_mig_threads[MAX_MIG_THREADS];
pthread_mutex_t g_mig_thread_lock = PTHREAD_MUTEX_INITIALIZER;

int main(int argc, char *argv[])
{
    pthread_t server_tid, client_tid;

    switch (argv[1][0]) {
        case 's': {
            if (argc != 2) {
                printf("Usage for server: %s s\n", argv[0]);
                return 1;
            }

            if (pthread_create(&server_tid, NULL, virtcca_mig_server_thread_func, NULL) != 0) {
                perror("Failed to create server thread");
                return 1;
            }

            pthread_join(server_tid, NULL);
            break;
        }
        case 'c': {
            if (argc != 3) {
                printf("Usage for client: %s c <server_ip>\n", argv[0]);
                return 1;
            }

            char *server_ip = argv[2];
            printf("Connecting to server at: %s\n", server_ip);

            struct mig_client_thread_args *client_args = (struct mig_client_thread_args *)calloc(1, sizeof(struct mig_client_thread_args));
            if (!client_args) {
                printf("Failed to alloc memory\n");
                return 1;
            }
            client_args->dst_ip = server_ip;
            client_args->dst_port = DEFAULT_PORT;

            if (pthread_create(&client_tid, NULL, virtcca_mig_client_thread_func, client_args) != 0) {
                perror("Failed to create server thread");
                return 1;
            }
            pthread_join(client_tid, NULL);
            break;
        }
        default:
            printf("Invalid argument. Use 'c' for client or 's' for server.\n");
            return 1;
    }

    return 0;
}
