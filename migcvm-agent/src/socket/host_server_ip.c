/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
 */

#include "host_server_ip.h"
#include <sys/ioctl.h>
#include <net/if.h>

/**
 * @brief Retrieve the first nonloopback IPv4 address.
 *
 * The function scans all network interfaces, skips loopback and
 * typical virtualcontainer interfaces, and returns the first address
 * that is up. If no suitable address is found, it falls back to the
 * address of the interface named "eth0".
 *
 * @return Dynamically allocated string containing the IPv4 address,
 *         or NULL on failure.  Caller must free the returned string.
 */
char* get_local_ipv4(void)
{
    struct ifaddrs *ifaddr;
    struct ifaddrs *ifa;
    char *ip = NULL;

    if (getifaddrs(&ifaddr) == -1) {
        perror("getifaddrs");
        return NULL;
    }

    for (ifa = ifaddr; ifa != NULL; ifa = ifa->ifa_next) {
        if (ifa->ifa_addr == NULL)
            continue;

        /* Look only at IPv4 addresses */
        if (ifa->ifa_addr->sa_family == AF_INET) {
            struct sockaddr_in *addr = (struct sockaddr_in *)ifa->ifa_addr;
            char ip_str[INET_ADDRSTRLEN];
            inet_ntop(AF_INET, &addr->sin_addr, ip_str, sizeof(ip_str));

            /* Skip the loopback address */
            if (strcmp(ip_str, "127.0.0.1") == 0)
                continue;

            /* Interface must be up */
            if (ifa->ifa_flags & IFF_UP) {
                /* Skip common virtual or container interfaces */
                if (strstr(ifa->ifa_name, "lo")     == ifa->ifa_name ||
                    strstr(ifa->ifa_name, "docker") == ifa->ifa_name ||
                    strstr(ifa->ifa_name, "virbr")  == ifa->ifa_name ||
                    strstr(ifa->ifa_name, "veth")   == ifa->ifa_name) {
                    continue;
                }

                ip = strdup(ip_str);
                printf("Found interface %s with IP: %s\n", ifa->ifa_name, ip);
                break;
            }
        }
    }

    freeifaddrs(ifaddr);

    /* Fallback to eth0 if nothing was found */
    if (ip == NULL) {
        ip = get_interface_ip("eth0");
    }

    return ip;
}

/**
 * @brief Get the IPv4 address of a specific network interface.
 *
 * @param ifname Name of the interface (e.g., "eth0").
 * @return Dynamically allocated string containing the address,
 *         or NULL if the interface does not have an IPv4 address
 *         (or on error).  Caller must free the returned string.
 */
char* get_interface_ip(const char* ifname)
{
    struct ifaddrs *ifaddr;
    struct ifaddrs *ifa;
    char *ip = NULL;

    if (getifaddrs(&ifaddr) == -1) {
        perror("getifaddrs");
        return NULL;
    }

    for (ifa = ifaddr; ifa != NULL; ifa = ifa->ifa_next) {
        if (ifa->ifa_addr == NULL)
            continue;

        if (ifa->ifa_addr->sa_family == AF_INET &&
            strcmp(ifa->ifa_name, ifname) == 0) {
            struct sockaddr_in *addr = (struct sockaddr_in *)ifa->ifa_addr;
            char ip_str[INET_ADDRSTRLEN];
            inet_ntop(AF_INET, &addr->sin_addr, ip_str, sizeof(ip_str));
            /* Exclude loopback */
            if (strcmp(ip_str, "127.0.0.1") != 0) {
                ip = strdup(ip_str);
            }
            break;
        }
    }

    freeifaddrs(ifaddr);
    return ip;
}

/**
 * @brief Retrieve the IP address of an interface using ioctl().
 *
 * This method opens a temporary AF_INET SOCK_DGRAM socket,
 * issues the SIOCGIFADDR request and extracts the IPv4 address.
 *
 * @param ifname Name of the interface.
 * @return Dynamically allocated string with the IPv4 address,
 *         or NULL on failure.  Caller must free the returned string.
 */
char* get_ip_by_ioctl(const char* ifname)
{
    int fd;
    struct ifreq ifr;
    char *ip = NULL;

    fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        perror("socket");
        return NULL;
    }

    memset(&ifr, 0, sizeof(ifr));
    strncpy(ifr.ifr_name, ifname, IFNAMSIZ - 1);

    if (ioctl(fd, SIOCGIFADDR, &ifr) == 0) {
        struct sockaddr_in *addr = (struct sockaddr_in *)&ifr.ifr_addr;
        char ip_str[INET_ADDRSTRLEN];

        if (inet_ntop(AF_INET, &addr->sin_addr, ip_str, sizeof(ip_str))) {
            if (strcmp(ip_str, "127.0.0.1") != 0) {
                ip = strdup(ip_str);
            }
        }
    }

    close(fd);
    return ip;
}

/**
 * @brief Read the IPv4 address from a networkinterface configuration file.
 *
 * The function first attempts to open the traditional RHEL/CentOS
 * /etc/sysconfig/network-scripts/ifcfg<ifname> file.  If that fails,
 * it falls back to NetworkManagers /etc/NetworkManager/system-connections/.
 * It looks for a line starting with IPADDR and returns the value.
 *
 * @param ifname Interface name (e.g., "eth0").
 * @return Dynamically allocated string with the IPv4 address,
 *         or NULL if the file cannot be read or no address is found.
 *         Caller must free the returned string.
 */
char* get_ip_from_config(const char* ifname)
{
    char filename[256];
    char *ip = NULL;
    FILE *fp;
    char line[256];

    /* Try the classic ifcfg file first */
    if (snprintf(filename, sizeof(filename),
             "/etc/sysconfig/network-scripts/ifcfg-%s", ifname) < 0) {
                printf("error of input filename of ifcfg-%s", ifname);
        }
    fp = fopen(filename, "r");
    if (!fp) {
        /* If that fails, try NetworkManagers .nmconnection file */
        if (snprintf(filename, sizeof(filename),
                 "/etc/NetworkManager/system-connections/%s.nmconnection",
                 ifname) < 0) {
                    printf("error of input filename of %s.nmconnection", ifname);
            }
        fp = fopen(filename, "r");
        if (!fp) {
            return NULL;
        }
    }

    while (fgets(line, sizeof(line), fp)) {
        char *key   = strtok(line, "=");
        char *value = strtok(NULL, "=");

        if (key && value) {
            /* Trim leading whitespace from the key */
            while (*key && isspace((unsigned char)*key)) {
                key++;
            }
            if (*key == '\0') {
                continue;
            }

            /* Look for a key that begins with "IPADDR" */
            if (strncmp(key, "IPADDR", strlen("IPADDR")) == 0) {
                /* Trim leading/trailing whitespace from the value */
                while (*value && isspace((unsigned char)*value)) {
                    value++;
                }

                char *end = value + strlen(value) - 1;
                while (end > value && isspace((unsigned char)*end)) {
                    *end = '\0';
                    end--;
                }

                ip = strdup(value);
                break;
            }
        }
    }

    if (fclose(fp) == EOF) {
        printf("fclose error!\n");
    }
    return ip;
}