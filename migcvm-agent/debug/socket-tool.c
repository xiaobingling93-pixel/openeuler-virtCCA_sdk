/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */
 
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <errno.h>
#include <getopt.h>
#include <linux/vm_sockets.h>

#define INT_MAX        ((int)(~0U >> 1))
#define INT_MIN        (-INT_MAX - 1)

#define DEFAULT_TARGET_PORT 9000
#define MAX_PAYLOAD_SIZE 256
#define PAYLOAD_TYPE_CHAR     0

#pragma pack(push, 1)
struct socket_msg {
    char            cmd[16];
    unsigned int    payload_type;
    unsigned int    payload_len;
    union {
        char            char_payload[MAX_PAYLOAD_SIZE];
        unsigned long long ull_payload;
    } payload;
};
#pragma pack(pop)

typedef struct {
    unsigned int    target_cid;
    unsigned int    target_port;
    int             tool_type;
    int             action;
    char            *mig_ip;
} socket_tool_args;

static void payload_encode_char(struct socket_msg *msg, const char *in)
{
    msg->payload_type = PAYLOAD_TYPE_CHAR;
    strncpy(msg->payload.char_payload, in, MAX_PAYLOAD_SIZE);
    msg->payload_len = strlen(in) + 1;
}

static void payload_encode(struct socket_msg *msg, const char *in)
{
    payload_encode_char(msg, in);
}

static void payload_decode(const struct socket_msg *msg, char *out)
{
    if (msg->payload_type == PAYLOAD_TYPE_CHAR) {
        strncpy(out, msg->payload.char_payload, msg->payload_len);
    }
}

static int parse_int(const char *str)
{
    char *endptr;
    errno = 0;
    if (str == NULL) {
        fprintf(stderr, "str is null\n");
    }
    long val = strtol(str, &endptr, 10);
    if (errno == ERANGE || val > INT_MAX || val < INT_MIN) {
        fprintf(stderr, "Value out of range\n");
        return -1;
    }
    if (*endptr != '\0') {
        fprintf(stderr, "Invalid input: non-numeric character detected\n");
        return -1;
    }
    return (int) val;
}

static int parse_input_socket_tool_args(int argc, char **argv, socket_tool_args *args)
{
    int opt;
    char *rim = NULL;
    char *const short_options = "c:p:t:i:";
    struct option long_options[] = {
        { "cid", required_argument, NULL, 'c' },
        { "port", required_argument, NULL, 'p' },
        { "type", required_argument, NULL, 't' },
        { "mig-ip", required_argument, NULL, 'i' },
        { 0, 0, 0, 0 }
    };

    args->target_cid = 0;
    args->target_port = DEFAULT_TARGET_PORT;
    args->tool_type = 0;

    do {
        opt = getopt_long(argc, argv, short_options, long_options, NULL);
        switch (opt) {
        case 'c':
            args->target_cid = (unsigned int)parse_int(optarg);
            break;
        case 'p':
            args->target_port = (unsigned int)parse_int(optarg);
            break;
        case 't':
            args->action = parse_int(optarg);
            break;
        case 'i':
            args->mig_ip = optarg;
            break;
        case -1:
            break;
        default:
            puts("This is a socket-tool");
            puts("    Usage:\n\n"
                 "        socket-tool <options> [arguments]\n\n"
                 "    Options:\n\n"
                 "        --cid/-c value   set the cid of socket\n"
                 "        --port/-p value   set the port of socket\n"
                 "        --type/-t value  set the type of target mig agent, server 1/agent 2\n"
                 "        --mig-ip/-i value  set the target migcvm ip\n");
            return -1;
        }
    } while (opt != -1);

    return 0;
}

#define SERVER_RATS_TLS 1
#define CLIENT_RATS_TLS 2
static int vsock_send(socket_tool_args *args)
{
    int sockfd;
    struct socket_msg msg;
    struct sockaddr_vm sa = {
        .svm_family = AF_VSOCK,
        .svm_cid = args->target_cid,
        .svm_port = args->target_port
    };

    /* setup socket */
    sockfd = socket(AF_VSOCK, SOCK_STREAM, 0);
    if (sockfd < 0) {
        perror("socket creation failed");
        exit(EXIT_FAILURE);
    }
    printf("Connected to VSOCK service at CID=%d, Port=%d\n", sa.svm_cid, sa.svm_port);
    /* connect server */
    if (connect(sockfd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        perror("connect failed");
        char error_message[256] = {0};
        strerror_r(errno, error_message, sizeof(error_message));
        printf("failed: %s (errno=%d)\n", error_message, errno);
        close(sockfd);
        exit(EXIT_FAILURE);
    }
    memset(&msg, 0, sizeof(msg));
    /* send msg */
    switch (args->action) {
        case SERVER_RATS_TLS:
            strncpy(msg.cmd, "s", sizeof(msg.cmd));
            payload_encode(&msg, args->mig_ip);
            break;
        case CLIENT_RATS_TLS:
            strncpy(msg.cmd, "c", sizeof(msg.cmd));
            payload_encode(&msg, args->mig_ip);
            break;
        default:
            printf("Unknown action: %d\n", args->action);
            close(sockfd);
            return -1;
    }

    printf("Message sent: cmd = %s payload = %s\n", msg.cmd, msg.payload);
    if (send(sockfd, &msg, sizeof(msg), 0) < 0) {
        perror("send failed");
        close(sockfd);
        exit(EXIT_FAILURE);
    }

    close(sockfd);
    return 0;
}

int main(int argc, char **argv)
{
    socket_tool_args input_args = {0};
    if (parse_input_socket_tool_args(argc, argv, &input_args)) {
        printf("Error parsing input args.\n");
        return 1;
    }

    printf("cid: %u port:%u tool_type:%d\n", input_args.target_cid, input_args.target_port, input_args.tool_type);
    return vsock_send(&input_args);
}

