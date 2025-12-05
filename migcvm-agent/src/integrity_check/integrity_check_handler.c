/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdbool.h>
#include <unistd.h>
#include <errno.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <pthread.h>
#include <sys/mman.h>
#include <sys/epoll.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <internal/core.h>
#include <rats-tls/api.h>
#include <rats-tls/log.h>
#include <rats-tls/claim.h>
#include "integrity_check_handler.h"

#define TSI_MAGIC 'T'
#define QUEUE_IOCTL_MAGIC 'q'
#define MIGVM_DESTROY_QUEUE _IO(QUEUE_IOCTL_MAGIC, 2)
#define MIGVM_CREATE_QUEUE _IOWR(QUEUE_IOCTL_MAGIC, 1, unsigned long)
#define TMM_GET_MIGVM_MEM_CHECKSUM _IOW(TSI_MAGIC, 4, unsigned long)

#define TSI_SUCCESS 0
#define TSI_ERROR_INPUT 1
#define TSI_ERROR_STATE 2
#define TSI_INCOMPLETE 3
#define TSI_ERROR_FAILED 4

#define MAX_EVENTS 64
#define EPOLL_SIZE 1023
#define TSI_PATH "/dev/tsi"
#define DEVICE_PATH "/dev/migvm_queue_mem"

#define WAIT_TIME_OUT 500000
#define CLOSE_LENGTH 12
#define RECV_CLOSE_REQ (-2)

#define QUEUE_SIZE (64 * 1024 - 8) // (64KB- 8B) queue size
#define PAGE_SIZE (4 * 1024)
#define _64K_SIZE (16 * PAGE_SIZE)

typedef struct {
    uint8_t *send_buf;  // Send buffer base address
    uint8_t *recv_buf;  // Receive buffer base address
    uint64_t *send_offset;  // Send queue head pointer (offset)
    uint64_t *recv_offset;  // Receive queue head pointer (offset)
} mig_integrity_share_queue_s;

// Dynamically add EPOLLOUT when data needs to be sent
static int enable_epollout(int epoll_fd, int fd)
{
    struct epoll_event ev;
    ev.events = EPOLLIN | EPOLLOUT | EPOLLERR | EPOLLHUP;
    ev.data.fd = fd;
    return epoll_ctl(epoll_fd, EPOLL_CTL_MOD, fd, &ev);
}

// Restore EPOLLIN after sending is completed
static int disable_epollout(int epoll_fd, int fd)
{
    struct epoll_event ev;
    ev.events = EPOLLIN | EPOLLERR | EPOLLHUP;
    ev.data.fd = fd;
    return epoll_ctl(epoll_fd, EPOLL_CTL_MOD, fd, &ev);
}

static int is_recv_queue_full(mig_integrity_share_queue_s *q, uint32_t len)
{
    uint64_t used = *(q->recv_offset);
    return (len > (QUEUE_SIZE - used)); // Check if remaining space is sufficient
}

static int enqueue_recv_data(mig_integrity_share_queue_s *q, uint8_t *buffer, uint32_t len)
{
    // If it exceeds the end, there is a program issue
    if (*(q->recv_offset) >= QUEUE_SIZE) {
        return -1;
    }

    // Direct linear write (no wrap-around handling needed)
    memcpy(q->recv_buf + *(q->recv_offset), buffer, len * sizeof(uint8_t));
    // Updatae receive offset
    *(q->recv_offset) += len;

    if (*(q->recv_offset) >= QUEUE_SIZE) {
        return -1;
    }
    return 1;
}

static int send_queue_data(rats_tls_handle *handle, mig_integrity_share_queue_s *q)
{
    int ret = 0;
    uint64_t send_len = *(q->send_offset);
    size_t len = sizeof(send_len);

    if (send_len > QUEUE_SIZE) {
        return -1;
    }

    // 1. Send data len
    size_t total_sent = 0;
    uint8_t *len_ptr = (uint8_t*)&send_len;
    
    while (total_sent < sizeof(uint64_t)) {
        size_t remaining = sizeof(uint64_t) - total_sent;
        ret = rats_tls_transmit(*handle, len_ptr + total_sent, &remaining);
        if (ret != RATS_TLS_ERR_NONE) {
            printf("Failed to send len %#x\n", ret);
            return -1;
        }
        if (remaining == 0) {
            continue;
        }
        total_sent += remaining;
    }

    total_sent = 0;
    while (total_sent < send_len) {
        size_t remaining = send_len - total_sent;
        ret = rats_tls_transmit(*handle, q->send_buf + total_sent, &remaining);
        if (ret != RATS_TLS_ERR_NONE) {
            printf("Failed to send data %#x\n", ret);
            return -1;
        }
        if (remaining == 0) {
            continue;
        }
        total_sent += remaining;
    }

    // 3. Clear the send area and reset the offset
    memset(q->send_buf, 0, send_len * sizeof(uint8_t));
    *(q->send_offset) = 0;
    return 0;
}

static int handle_send_event(rats_tls_handle *handle, mig_integrity_share_queue_s *queue)
{
    if (*(queue->send_offset) == 0) {
        return 0;
    }

    return send_queue_data(handle, queue);
}

static int handle_recv_event(int epoll_fd, int socket_fd, int tsi_fd,
    integrity_socket_t *params, mig_integrity_share_queue_s *queue)
{
    int ret = 0;
    int tsi_ret = TSI_INCOMPLETE;
    uint64_t recv_len = 0;
    size_t len = sizeof(uint64_t);

    size_t total_received = 0;
    uint8_t *len_ptr = (uint8_t*)&recv_len;
    while (total_received < sizeof(uint64_t)) {
        size_t remaining = sizeof(uint64_t) - total_received;
        ret = rats_tls_receive(*params->handle, len_ptr + total_received, &remaining);
        if (ret != RATS_TLS_ERR_NONE) {
            printf("Failed to receive len %lx\n", ret);
            return -1;
        }
        if (remaining == 0) {
            continue;
        }
        total_received += remaining;
    }

    if (recv_len > QUEUE_SIZE - sizeof(uint64_t)) {
        printf("Receive len is invalid: %lu\n", recv_len);
        return -1;
    }

    while (is_recv_queue_full(queue, recv_len)) {
        if (*(queue->send_offset) > 0) {
            if (enable_epollout(epoll_fd, socket_fd) < 0) {
                printf("Recv event: Failed to enable epollout\n");
                return -1;
            }

            if (handle_send_event(params->handle, queue) < 0) {
                printf("Recv event: Failed to send data\n");
                return -1;
            }

            if (disable_epollout(epoll_fd, socket_fd) < 0) {
                printf("Recv event: Failed to disable epollout\n");
                return -1;
            }
        }

        tsi_ret = ioctl(tsi_fd, TMM_GET_MIGVM_MEM_CHECKSUM, &params->guest_rd);
        if (tsi_ret == TSI_ERROR_FAILED) {
            return ret;
        }
    }

    uint64_t check_len = recv_len;
    uint8_t *buffer = malloc(recv_len);
    if (!buffer) {
        printf("Failed to allocate buffer for received data\n");
        return -1;
    }

    total_received = 0;
    while (total_received < check_len) {
        size_t remaining = check_len - total_received;
        ret = rats_tls_receive(*params->handle, buffer + total_received, &remaining);
        if (ret != RATS_TLS_ERR_NONE) {
            printf("Failed to receive data: %lx\n", ret);
            free(buffer);
            return -1;
        }
        if (remaining == 0) {
            continue;
        }
        total_received += remaining;
    }

    if (total_received >= CLOSE_LENGTH && memcmp(buffer, "CLOSE_NOTIFY", CLOSE_LENGTH) == 0) {
        printf("Received application close notification\n");
        free(buffer);
        return RECV_CLOSE_REQ;
    }

    int enqueue_ret = enqueue_recv_data(queue, buffer, total_received);
    free(buffer);
    if (enqueue_ret < 0) {
        return enqueue_ret;
    }
    return tsi_ret;
}

static void close_connection(int epoll_fd, int socket_fd, rats_tls_handle *handle)
{
    shutdown(socket_fd, SHUT_WR);

    struct timeval tv = {2, 0};
    setsockopt(socket_fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    close(socket_fd);
    if (epoll_fd >= 0) {
        epoll_ctl(epoll_fd, EPOLL_CTL_DEL, socket_fd, NULL);
    }
}

static int send_close_notification(rats_tls_handle *handle)
{
    const char *close_msg = "CLOSE_NOTIFY";
    uint64_t msg_len = strlen(close_msg);
    int ret;

    size_t len_size = sizeof(msg_len);
    ret = rats_tls_transmit(*handle, (uint8_t*)&msg_len, &len_size);
    if (ret != RATS_TLS_ERR_NONE) {
        printf("Failed to send close notification length: %#x\n", ret);
        return -1;
    }

    size_t msg_size = msg_len;
    ret = rats_tls_transmit(*handle, (uint8_t*)close_msg, &msg_size);
    if (ret != RATS_TLS_ERR_NONE) {
        printf("Failed to send close notification: %#x\n", ret);
        return -1;
    }

    printf("Close notification sent successfully\n");
    return 0;
}

void* io_thread(void* arg)
{
    struct epoll_event events[MAX_EVENTS];
    mig_integrity_share_queue_s share_queue;
    int socket_fd = -1;
    int dev_fd = -1;
    int tsi_fd = -1;
    int epoll_fd = -1;
    int ret = TSI_SUCCESS;
    integrity_socket_t *params = (integrity_socket_t*)arg;
    if (!params) {
        printf("Params is NULL\n");
        return NULL;
    }
    
    dev_fd = open(DEVICE_PATH, O_RDWR);
    if (dev_fd < 0) {
        printf("Failed to open device\n");
        goto failed_alloc_dev;
    }

    if (ioctl(dev_fd, MIGVM_CREATE_QUEUE, &params->guest_rd) < 0) {
        printf("Failed to create first queue\n");
        goto failed_alloc_queue;
    }

    share_queue.send_buf = mmap(NULL, _64K_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, dev_fd, 0);
    if (share_queue.send_buf == MAP_FAILED) {
        printf("Failed to map send_buf\n");
        share_queue.send_buf = NULL;
        goto failed_mmap;
    }
    memset(share_queue.send_buf, 0, PAGE_SIZE);

    share_queue.recv_buf = mmap(NULL, _64K_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, dev_fd, 1 * PAGE_SIZE);
    if (share_queue.recv_buf == MAP_FAILED) {
        printf("Failed to map recv_buf\n");
        share_queue.recv_buf = NULL;
        goto failed_mmap;
    }
    memset(share_queue.recv_buf, 0, PAGE_SIZE);

    share_queue.send_offset = (uint64_t *)(share_queue.send_buf + QUEUE_SIZE);
    share_queue.recv_offset = (uint64_t *)(share_queue.recv_buf + QUEUE_SIZE);

    *(share_queue.send_offset) = 0;
    *(share_queue.recv_offset) = 0;

    tsi_fd = open(TSI_PATH, O_RDWR | O_CLOEXEC);
    if (tsi_fd < 0) {
        printf("Failed to open tsi device\n");
        goto failed_open_tsi;
    }

    epoll_fd = epoll_create1(0);
    if (epoll_fd < 0) {
        goto failed_alloc_epoll;
    }

    struct epoll_event ev;
    ev.events = EPOLLIN | EPOLLERR | EPOLLHUP;
    if (params->is_server) {
        socket_fd = params->connd_fd;
    } else {
        socket_fd = params->socket_fd;
    }
    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, socket_fd, &ev) < 0) {
        printf("Failed to add epoll_ctl\n");
        goto out;
    }

    while (1) {
        // tsi interface
        ret = ioctl(tsi_fd, TMM_GET_MIGVM_MEM_CHECKSUM, &params->guest_rd);
        if ((params->is_server == 0 && ret == TSI_ERROR_FAILED) ||
        (params->is_server == 0 && ret == TSI_SUCCESS) || ret == TSI_ERROR_INPUT) {
            send_close_notification(params->handle);
            close_connection(epoll_fd, socket_fd, params->handle);
            usleep(WAIT_TIME_OUT);
            goto out;
        }
        // send handle
        if (*(share_queue.send_offset) > 0) {
            if (enable_epollout(epoll_fd, socket_fd) < 0) {
                printf("Failed to enable epollout\n");
                goto out;
            }

            if (handle_send_event(params->handle, &share_queue) < 0) {
                printf("Failed to send data\n");
                goto out;
            }

            if (disable_epollout(epoll_fd, socket_fd) < 0) {
                printf("Failed to disable epollout\n");
                goto out;
            }
        }

        int timeout_ms = 100;
        int n = epoll_wait(epoll_fd, events, MAX_EVENTS, timeout_ms);
        for (int i = 0; i < n; i++) {
            // error handle
            if (events[i].events & (EPOLLERR | EPOLLHUP)) {
                close(events[i].data.fd);
                events[i].data.fd = -1;
                epoll_ctl(epoll_fd, EPOLL_CTL_DEL, events[i].data.fd, NULL);
                continue;
            }

            // receive handle
            if (events[i].events & EPOLLIN) {
                ret = handle_recv_event(epoll_fd, socket_fd, tsi_fd, params, &share_queue);
                if (ret < 0 || (params->is_server == 0 && ret == TSI_ERROR_FAILED) ||
                (params->is_server == 0 && ret == TSI_SUCCESS) || ret == TSI_ERROR_INPUT) {
                    if (ret != RECV_CLOSE_REQ) {
                        send_close_notification(params->handle);
                    }
                    close_connection(epoll_fd, socket_fd, params->handle);
                    usleep(WAIT_TIME_OUT);
                    goto out;
                }
            }
        }
    }

out:
    printf("close io thread\n");
    close(epoll_fd);
failed_alloc_epoll:
    close(tsi_fd);
failed_mmap:
failed_open_tsi:
    ioctl(dev_fd, MIGVM_DESTROY_QUEUE);
failed_alloc_queue:
    close(dev_fd);
failed_alloc_dev:
    if (params->handle) {
        /* Clear custom_claims before cleanup to prevent freeing static memory */
        rtls_core_context_t *ctx = (rtls_core_context_t *)(*params->handle);
        if (ctx) {
            ctx->config.custom_claims = NULL;
            ctx->config.custom_claims_length = 0;
            rats_tls_cleanup(*params->handle);
        }
        free(params->handle);
    }

    if (params->is_server == true && params->connd_fd != -1)
        close(params->connd_fd);

    if (params->socket_fd != -1) {
        shutdown(params->socket_fd, SHUT_RDWR);
        close(params->socket_fd);
    }
    free(params);
    return NULL;
}
