/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
 */

#ifndef HOST_SERVER_IP_H
#define HOST_SERVER_IP_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <sys/socket.h>
#include <netdb.h>
#include <ifaddrs.h>
#include <arpa/inet.h>
#include <net/if.h>
#include <unistd.h>
#include <errno.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Retrieve the first nonloopback IPv4 address.
 * @return On success, a dynamically allocated string containing the address;
 *         on failure, NULL.
 * @note The caller is responsible for freeing the returned string.
 */
char* get_local_ipv4(void);

/**
 * @brief Get the IP address associated with a specific network interface.
 * @param ifname Interface name (e.g., "eth0").
 * @return On success, a dynamically allocated string containing the address;
 *         on failure, NULL.
 * @note The caller is responsible for freeing the returned string.
 */
char* get_interface_ip(const char* ifname);

/**
 * @brief Read the IP address from a configuration file.
 * @param ifname Interface name.
 * @return On success, a dynamically allocated string containing the address;
 *         on failure, NULL.
 */
char* get_ip_from_config(const char* ifname);

/**
 * @brief Obtain the IP address using ioctl.
 * @param ifname Interface name.
 * @return On success, a dynamically allocated string containing the address;
 *         on failure, NULL.
 */
char* get_ip_by_ioctl(const char* ifname);

#ifdef __cplusplus
}
#endif

#endif /* HOST_SERVER_IP_H */