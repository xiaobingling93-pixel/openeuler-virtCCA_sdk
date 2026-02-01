/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdbool.h>
#include <unistd.h>
#include <errno.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <semaphore.h>
#include <stdatomic.h>
#include <pthread.h>
#include <sys/mman.h>
#include <sys/epoll.h>
#include <fcntl.h>
#include <sys/ioctl.h>

#include "integrity_check_handler.h"
#include "tmi.h"

#define TSI_SUCCESS 0
#define TSI_ERROR_INPUT 1
#define TSI_ERROR_STATE 2
#define TSI_INCOMPLETE 3
#define TSI_ERROR_FAILED 4
#define TSI_NOTIFY 5

#define TOTAL_CPU_COUNT 16
#define MASTER_THREAD_ID 0

#define MAX_EVENTS 64
#define EPOLL_SIZE 1023

#define CLOSE_LENGTH 12
#define RECV_CLOSE_REQ (-2)
#define WAIT_TIME_OUT 500000

#define QUEUE_SIZE (64 * 1024 - 16) // (64KB - 16B) queue size
#define PAGE_SIZE (4 * 1024)
#define _64K_SIZE (16 * PAGE_SIZE)

#define TOTAL_DFX_COUNT 50

#define TSI_PATH "/dev/tsi"
#define DEVICE_PATH "/dev/migvm_queue_mem"

typedef struct {
    uint8_t *send_buf;      // Send buffer base address
    uint8_t *recv_buf;      // Receive buffer base address
    uint64_t *send_offset;  // Send queue head pointer (offset)
    uint64_t  *send_len;    // Send len (send all data in the queue at once)
    uint64_t *recv_offset;  // Receive queue head pointer (offset)
} mig_integrity_share_queue_s;

typedef struct {
    unsigned long guest_rd;
    unsigned long thread_id;
} virtcca_migvm_checksum_info_t;

typedef struct {
    int             tmi_fd;
    int             thread_id;
    unsigned long   guest_rd;
    pthread_t       thread;
    sem_t           wake_sem;
    bool            thread_created;
    void            *parent;
    int             cpu_start;
    int             cpu_end;
} thread_args_t;

typedef struct {
    unsigned long tsi_start[TOTAL_DFX_COUNT];
    unsigned long tsi_end[TOTAL_DFX_COUNT];
    unsigned long type[TOTAL_DFX_COUNT];
    unsigned long tsi_index;
    bool should_exit;
    thread_args_t slave_args[SLAVE_THREAD_NUM];
} io_thread_context_t;

#define TSI_MAGIC 'T'
#define QUEUE_IOCTL_MAGIC 'q'
#define MIGVM_DESTROY_QUEUE _IO(QUEUE_IOCTL_MAGIC, 2)
#define MIGVM_CREATE_QUEUE _IOWR(QUEUE_IOCTL_MAGIC, 1, unsigned long)
#define TMM_GET_MIGVM_MEM_CHECKSUM _IOW(TSI_MAGIC, 4, virtcca_migvm_checksum_info_t)

unsigned long get_timestamp_ns(void)
{
    unsigned long val, freq;
    asm volatile("mrs %0, cntvct_el0" : "=r" (val));
    asm volatile("mrs %0, cntfrq_el0" : "=r" (freq));

    /* should never happen */
    if (freq == 0)
        return 0;

    return 1000000000 / freq * val;
}

void record_tsi_time(io_thread_context_t *ctx, unsigned long t1, unsigned long t2, unsigned long type)
{
    unsigned long i = ctx->tsi_index;
    ctx->tsi_start[i] = t1;
    ctx->tsi_end[i] = t2;
    ctx->type[i] = type;
    ctx->tsi_index = (i + 1) % TOTAL_DFX_COUNT;
}

void show_tsi_time(io_thread_context_t *ctx)
{
    unsigned long j = ctx->tsi_index;
    for (unsigned long i = 0; i < TOTAL_DFX_COUNT; i++) {
        if (j == 0)
            j = TOTAL_DFX_COUNT - 1;
        else
            j = j - 1;
        printf("before notify tsi start:%lu end:%lu type:%lu\n", ctx->tsi_start[j], ctx->tsi_end[j], ctx->type[j]);
    }
}

int set_affinity(int cpu_start, int cpu_end)
{
    cpu_set_t cpuset;

    if (cpu_start < 0 || cpu_end < 0 || cpu_start > cpu_end) {
        perror("set affinity failed, invalid cpu range.");
        return -1;
    }

    CPU_ZERO(&cpuset);
    for (int i = cpu_start; i <= cpu_end; i++) {
        CPU_SET(i, &cpuset);
    }

    if (pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset)) {
        perror("pthread_setaffinity_np failed");
        return -1;
    }

    return 0;
}

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
    // Check if remaining space is sufficient
    return (len > (QUEUE_SIZE - used));
}

static int enqueue_recv_data(mig_integrity_share_queue_s *q, uint8_t *buffer, uint32_t len)
{
    if (*(q->recv_offset) >= QUEUE_SIZE) {
        return -1;
    }

    // Direct linear write (no wrap-around handling needed)
    memcpy(q->recv_buf + *(q->recv_offset), buffer, len * sizeof(uint8_t));
    // Update receive offset
    *(q->recv_offset) += len;

    if (*(q->recv_offset) >= QUEUE_SIZE) {
        return -1;
    }
    return 1;
}

static int send_queue_data(virtcca_tls_handle *handle, mig_integrity_share_queue_s *q)
{
    int ret = 0;
    uint64_t send_len = *(q->send_offset);
    uint8_t *send_addr = q->send_buf -sizeof(uint64_t);

    if (send_len > QUEUE_SIZE) {
        return -1;
    }

    size_t total_sent = 0;
    *(q->send_len) = send_len;
    send_len = send_len + sizeof(uint64_t);
    while (total_sent < send_len) {
        size_t remaining = send_len - total_sent;
        ret = virtcca_tls_transmit(*handle, send_addr + total_sent, &remaining);
        if (ret != TLS_ERR_OK) {
            printf("Failed to send data %x\n", ret);
            return -1;
        }
        if (remaining == 0) {
            continue;
        }
        total_sent += remaining;
    }

    memset(send_addr, 0, send_len * sizeof(uint8_t));
    *(q->send_offset) = 0;
    return 0;
}

static int handle_send_event(virtcca_tls_handle *handle, int epoll_fd, int socket_fd, mig_integrity_share_queue_s *queue)
{
    int ret = 0;

    if (enable_epollout(epoll_fd, socket_fd) < 0) {
        printf("Failed to enable epollout\n");
        return -1;
    }

    ret = send_queue_data(handle, queue);
    if (ret < 0) {
        return ret;
    }

    if (disable_epollout(epoll_fd, socket_fd) < 0) {
        printf("Failed to disable epollout\n");
        return -1;
    }
    return ret;
}

static int handle_recv_event(int epoll_fd, int socket_fd, tmi_ctx *virtcca_client_ctx,
    integrity_socket_t *params, mig_integrity_share_queue_s *queue, int master_thread_id)
{
    uint64_t ret = 0;
    uint64_t recv_len = 0;
    size_t total_received = 0;
    // int tsi_ret = TSI_INCOMPLETE;
    uint64_t ret_val = TSI_INCOMPLETE;
    uint8_t *len_ptr = (uint8_t*)&recv_len;
    virtcca_migvm_checksum_info_t checksum_info;

    while (total_received < sizeof(uint64_t)) {
        size_t remaining = sizeof(uint64_t) - total_received;
        ret = virtcca_tls_receive(*params->handle, len_ptr + total_received, &remaining);
        if (ret != TLS_ERR_OK) {
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
            if (handle_send_event(params->handle, epoll_fd, socket_fd, queue) < 0) {
                printf("Recv event: Failed to send data\n");
                return -1;
            }
        }
        checksum_info.guest_rd = params->guest_rd;
        checksum_info.thread_id = master_thread_id;
        ret = virtcca_tmi_ioctl(virtcca_client_ctx, VIRTCCA_GET_MIGVM_MEM_CHECKSUM, 0, &checksum_info, &ret_val);
        if (ret != 0) {
            printf("Failed to call tmi ioctl: %ld\n", ret);
            return ret;
        }
        if (ret_val == TSI_ERROR_FAILED) {
            printf("TSI_ERROR_FAILED...");
            return ret_val;
        }
        // tsi_ret = ioctl(tsi_fd, TMM_GET_MIGVM_MEM_CHECKSUM, &checksum_info);
        // if (tsi_ret == TSI_ERROR_FAILED) {
        //     return tsi_ret;
        // }
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
        ret = virtcca_tls_receive(*params->handle, buffer + total_received, &remaining);
        if (ret != TLS_ERR_OK) {
            printf("Failed to receive data: %lu\n", ret);
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

    return ret_val;
}

static void close_connection(int epoll_fd, int socket_fd)
{
    if (socket_fd >= 0) {
        shutdown(socket_fd, SHUT_WR);

        struct timeval tv = {2, 0};
        setsockopt(socket_fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

        if (epoll_fd >= 0) {
            epoll_ctl(epoll_fd, EPOLL_CTL_DEL, socket_fd, NULL);
        }
    }
}

static int send_close_notification(virtcca_tls_handle *handle)
{
    const char *close_msg = "CLOSE_NOTIFY";
    uint64_t msg_len = strlen(close_msg);
    int ret;

    size_t len_size = sizeof(msg_len);
    ret = virtcca_tls_transmit(*handle, (uint8_t*)&msg_len, &len_size);
    if (ret != TLS_ERR_OK) {
        printf("Failed to send close notification length: %#x\n", ret);
        return -1;
    }

    size_t msg_size = msg_len;
    ret = virtcca_tls_transmit(*handle, (uint8_t*)close_msg, &msg_size);
    if (ret != TLS_ERR_OK) {
        printf("Failed to send close notification: %#x\n", ret);
        return -1;
    }

    printf("Close notification sent successfully\n");
    return 0;
}

void* slave_io_thread(void* arg) {
    thread_args_t *args = (thread_args_t *)arg;
    virtcca_migvm_checksum_info_t checksum_info;
    uint64_t ret;

    printf("Thread %d started init\n", args->thread_id);

    set_affinity(args->cpu_start, args->cpu_end);

    while (!((io_thread_context_t *)args->parent)->should_exit) {
        uint64_t ret_val = TSI_INCOMPLETE;

        sem_wait(&args->wake_sem);
        checksum_info.guest_rd = args->guest_rd;
        checksum_info.thread_id = args->thread_id;
        while (ret != TSI_SUCCESS) {
            tmi_ctx virtcca_client_ctx = {0};
            virtcca_client_ctx.fd = args->tmi_fd;
            ret = virtcca_tmi_ioctl(&virtcca_client_ctx, VIRTCCA_GET_MIGVM_MEM_CHECKSUM, 0, &checksum_info, &ret_val);
            if (ret != 0) {
                printf("Failed to call tmi ioctl: %ld\n", ret);
                return NULL;
            }

            if (ret_val == TSI_ERROR_INPUT || ret_val == TSI_ERROR_FAILED) {
                printf("Thread %d tsi call end, ret: %ld\n", args->thread_id, ret);
                ((io_thread_context_t *)args->parent)->should_exit = true;
                break;
            }
        }
    }

    printf("slave %d thread with exit\n", args->thread_id);
    return NULL;
}

static int create_slave_thread(io_thread_context_t *ctx, integrity_socket_t *params, int tmi_fd)
{
    if (!ctx || !params) {
        return -1;
    }

    ctx->should_exit = false;
    for (int i = 0; i < SLAVE_THREAD_NUM; i++) {
        ctx->slave_args[i].thread_id = i + 1;
        ctx->slave_args[i].guest_rd = params->guest_rd;
        ctx->slave_args[i].tmi_fd = tmi_fd;
        ctx->slave_args[i].thread_created = false;
        ctx->slave_args[i].cpu_start = params->cpu_start + i + 1;
        ctx->slave_args[i].cpu_end = params->cpu_start + i + 1;
        sem_init(&ctx->slave_args[i].wake_sem, 0, 0);
        ctx->slave_args[i].parent = ctx;
        if (pthread_create(&ctx->slave_args[i].thread, NULL, slave_io_thread, &ctx->slave_args[i]) != 0) {
            printf("Failed to create slave io thread %d\n", i);
            ctx->should_exit = true;
            for (int j = 0; j < i; j++) {
                sem_post(&ctx->slave_args[j].wake_sem);
                pthread_join(ctx->slave_args[j].thread, NULL);
                sem_destroy(&ctx->slave_args[j].wake_sem);
                ctx->slave_args[j].thread_created = false;
            }
            return -1;
        }
        ctx->slave_args[i].thread_created = true;
    }

    usleep(100000);
    return 0;
}

static int stop_all_slave_threads(io_thread_context_t *ctx, int count)
{
    if (!ctx) {
        return -1;
    }

    printf("Stopping all slave threads...\n");
    ctx->should_exit = true;
    for (int i = 0; i < count; i++) {
        if (ctx->slave_args[i].thread_created) {
            sem_post(&ctx->slave_args[i].wake_sem);
        }
    }

    struct timespec timeout;
    clock_gettime(CLOCK_REALTIME, &timeout);
    timeout.tv_sec += 2;

    for (int i = 0; i < count; i++) {
        if (ctx->slave_args[i].thread_created) {
            int join_result = pthread_timedjoin_np(ctx->slave_args[i].thread, NULL, &timeout);
            if (join_result != 0) {
                printf("Thread %d join failed, forcing cancel\n", i);
                pthread_cancel(ctx->slave_args[i].thread);
            }
        }
    }

    for (int i = 0; i < count; i++) {
        if (ctx->slave_args[i].thread_created) {
            sem_destroy(&ctx->slave_args[i].wake_sem);
            ctx->slave_args[i].thread_created = false;
        }
    }
    printf("All slave threads stopped\n");
    return 0;
}

static int notify_all_slave_thread(io_thread_context_t *ctx)
{
    if (!ctx) {
        return -1;
    }

    for (int i = 0; i < SLAVE_THREAD_NUM; i++) {
        if (ctx->slave_args[i].thread_created && sem_post(&ctx->slave_args[i].wake_sem) != 0) {
            printf("Failed to wakeup slave io thread %d\n", ctx->slave_args[i].thread_id);
            return -1;
        }
    }
    return 0;
}

static void cleanup_server(integrity_socket_t *params, int epoll_fd)
{
    if (epoll_fd >= 0) {
        epoll_ctl(epoll_fd, EPOLL_CTL_DEL, params->connd_fd, NULL);
        close(epoll_fd);
    }

    if (params->connd_fd >= 0) {
        close(params->connd_fd);
        params->connd_fd = -1;
    }
}

static void cleanup_client(integrity_socket_t *params, int epoll_fd)
{
    if (epoll_fd >= 0) {
        epoll_ctl(epoll_fd, EPOLL_CTL_DEL, params->socket_fd, NULL);
        close(epoll_fd);
    }

    if (params->connd_fd >= 0) {
        close(params->connd_fd);
        params->connd_fd = -1;
    }

    if (params->socket_fd >= 0) {
        shutdown(params->socket_fd, SHUT_RDWR);
        close(params->socket_fd);
        params->socket_fd = -1;
    }
}

static void cleanup_resources(integrity_socket_t *params, 
                             mig_integrity_share_queue_s *queue,
                             int dev_fd, tmi_ctx *virtcca_client_ctx, int epoll_fd)
{
    if (queue->send_len) {
        munmap(queue->send_len, _64K_SIZE);
        queue->send_len = NULL;
        queue->send_buf = NULL;
    }

    if (queue->recv_buf) {
        munmap(queue->recv_buf, _64K_SIZE);
        queue->recv_buf = NULL;
    }

    if (dev_fd >= 0) {
        ioctl(dev_fd, MIGVM_DESTROY_QUEUE);
        close(dev_fd);
    }

    tmi_free_ctx(virtcca_client_ctx);

    if (params) {
        if (params->is_server) {
            cleanup_server(params, epoll_fd);
        } else {
            cleanup_client(params, epoll_fd);
        }
    }
}

void* io_thread(void* arg)
{
    struct epoll_event events[MAX_EVENTS];
    virtcca_migvm_checksum_info_t checksum_info;
    int socket_fd = -1;
    int dev_fd = -1;
    int epoll_fd = -1;
    int ret = TSI_SUCCESS;
    io_thread_context_t ctx = { 0 };
    mig_integrity_share_queue_s share_queue = {0};
    int master_thread_id = 0;
    integrity_socket_t *params = (integrity_socket_t*)arg;

    if (!params) {
        printf("Params is NULL\n");
        return NULL;
    }

    set_affinity(params->cpu_start, params->cpu_start);
    // open device
    dev_fd = open(DEVICE_PATH, O_RDWR);
    if (dev_fd < 0) {
        printf("Failed to open device\n");
        goto cleanup;
    }

    // create share mem queue
    printf("params->guest_rd:0x%lx\n", params->guest_rd);
    if (ioctl(dev_fd, MIGVM_CREATE_QUEUE, &params->guest_rd) < 0) {
        printf("Failed to create first queue\n");
        goto cleanup;
    }

    // mmap share memory
    share_queue.send_buf = mmap(NULL, _64K_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, dev_fd, 0);
    if (share_queue.send_buf == MAP_FAILED) {
        printf("Failed to map send_buf\n");
        goto cleanup;
    }
    memset(share_queue.send_buf, 0, PAGE_SIZE);
    share_queue.send_len = (uint64_t *)share_queue.send_buf;
    share_queue.send_buf += sizeof(uint64_t);

    share_queue.recv_buf = mmap(NULL, _64K_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, dev_fd, 1 * PAGE_SIZE);
    if (share_queue.recv_buf == MAP_FAILED) {
        printf("Failed to map recv_buf\n");
        goto cleanup;
    }
    memset(share_queue.recv_buf, 0, PAGE_SIZE);

    share_queue.send_offset = (uint64_t *)(share_queue.send_buf + QUEUE_SIZE);
    share_queue.recv_offset = (uint64_t *)(share_queue.recv_buf + QUEUE_SIZE);

    *(share_queue.send_offset) = 0;
    *(share_queue.recv_offset) = 0;

    tmi_ctx *virtcca_client_ctx = tmi_new_ctx();
    if (!virtcca_client_ctx) {
        printf("Failed to open tmi dev\n");
        goto cleanup;
    }

    // create epoll
    epoll_fd = epoll_create1(0);
    if (epoll_fd < 0) {
        printf("Failed to create epoll\n");
        goto cleanup;
    }

    // set socket fd
    struct epoll_event ev;
    ev.events = EPOLLIN | EPOLLERR | EPOLLHUP;
    if (params->is_server) {
        socket_fd = params->connd_fd;
    } else {
        socket_fd = params->socket_fd;
    }

    if (socket_fd < 0) {
        printf("Invalid socket fd\n");
        goto cleanup;
    }

    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, socket_fd, &ev) < 0) {
        printf("Failed to add epoll_ctl\n");
        goto cleanup;
    }

    // create slave thread
    if (create_slave_thread(&ctx, params, virtcca_client_ctx->fd)) {
        printf("Failed to create slave threads\n");
        goto cleanup;
    }

    printf("IO thread started successfully\n");
    int cpu_cores = sysconf(_SC_NPROCESSORS_ONLN);
    if (cpu_cores > TOTAL_CPU_COUNT) {
        master_thread_id = MASTER_THREAD_ID;

        cpu_set_t cpuset;
        CPU_ZERO(&cpuset);
        CPU_SET(master_thread_id, &cpuset);
         if (pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset)) {
            perror("pthread_setaffinity_np");
            goto cleanup;
        }
        printf("cpu core is more than %d\n", TOTAL_CPU_COUNT);
    }

    checksum_info.guest_rd = params->guest_rd;
    checksum_info.thread_id = master_thread_id;
    printf("guest_rd = 0x%lx thread_id = %d\n", params->guest_rd, master_thread_id);
    while (1) {
        uint64_t ret_val = 0;
        ret = virtcca_tmi_ioctl(virtcca_client_ctx, VIRTCCA_GET_MIGVM_MEM_CHECKSUM, 0, &checksum_info, &ret_val);
        if (ret != 0) {
            printf("Failed to call tmi ioctl: %d\n", ret);
            return NULL;
        }
        if ((params->is_server == 0 && ret_val == TSI_ERROR_FAILED) ||
            (params->is_server == 0 && ret_val == TSI_SUCCESS) || 
            ret_val == TSI_ERROR_INPUT) {
            send_close_notification(params->handle);
            usleep(WAIT_TIME_OUT);
            printf("tsi call end, ret_val = 0x%lx...\n", ret_val);
            break;
        } else if (ret_val == TSI_NOTIFY) {
            if (notify_all_slave_thread(&ctx)) {
                printf("Failed to notify slave threads\n");
                break;
            }
        }

        if (*(share_queue.send_offset) > 0) {
            if (handle_send_event(params->handle, epoll_fd, socket_fd, &share_queue) < 0) {
                printf("Failed to send data\n");
                break;
            }
        }

        int n = epoll_wait(epoll_fd, events, MAX_EVENTS, 0);
        if (n < 0) {
            if (errno != EINTR) {
                printf("epoll_wait error: %s\n", strerror(errno));
                goto cleanup;
            }
            continue;
        }

        for (int i = 0; i < n; i++) {
            if (events[i].events & (EPOLLERR | EPOLLHUP)) {
                printf("Socket error or hang up\n");
                goto cleanup;
            }

            if (events[i].events & EPOLLIN) {
                uint64_t start = get_timestamp_ns();
                ret = handle_recv_event(epoll_fd, socket_fd, virtcca_client_ctx, params, &share_queue, master_thread_id);
                if (ret < 0 || 
                    (params->is_server == 0 && ret == TSI_ERROR_FAILED) ||
                    (params->is_server == 0 && ret == TSI_SUCCESS) || 
                    ret == TSI_ERROR_INPUT) {
                    if (ret != RECV_CLOSE_REQ) {
                        send_close_notification(params->handle);
                        usleep(WAIT_TIME_OUT);
                    }
                    printf("Receive close notification or event end...\n");
                    goto cleanup;
                } else if (ret == TSI_NOTIFY) {
                    if (notify_all_slave_thread(&ctx)) {
                        printf("Failed to notify slave threads\n");
                        goto cleanup;
                    }
                }
                record_tsi_time(&ctx, start, get_timestamp_ns() - start, 1);
            }
        }
    }

cleanup:
    show_tsi_time(&ctx);
    stop_all_slave_threads(&ctx, SLAVE_THREAD_NUM);
    cleanup_resources(params, &share_queue, dev_fd, virtcca_client_ctx, epoll_fd);
    if (params) {
        free(params);
    }
    printf("IO thread cleanup completed\n");
    return NULL;
}









