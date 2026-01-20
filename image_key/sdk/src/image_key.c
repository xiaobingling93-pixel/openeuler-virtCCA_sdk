/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024. All rights reserved.
 * virtCCA_sdk is licensed under the Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan PSL v2.
 * You may obtain a copy of Mulan PSL v2 at:
 *     http://license.coscl.org.cn/MulanPSL2
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
 * PURPOSE.
 * See the Mulan PSL v2 for more details.
 */

#include <stdio.h>
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include "image_key.h"

#define IMAGE_KEY_DEV_NAME "/dev/imagekey"

struct image_key_params {
    uint32_t alg;
    uint8_t user_param[USER_PARAM_LEN];
    uint32_t user_param_len;
    uint8_t image_key[IMAGE_KEY_LEN];
};

#define IMAGE_KEY_IOC_MAGIC 'd'
#define IOCTL_IMAGE_KEY _IOWR(IMAGE_KEY_IOC_MAGIC, 0, struct image_key_params)

int get_image_key(IMAGE_KEY_ALG alg, uint8_t* user_param, uint32_t user_param_len, uint8_t* image_key,
                  uint32_t key_len)
{
    int rc = 0;
    int fd = -1;
    struct image_key_params args = { 0 };

    if (user_param && user_param_len != USER_PARAM_LEN) {
        printf("invalid user param len %u, should be equal %u\n", user_param_len, USER_PARAM_LEN);
        return -1;
    }

    if (image_key == NULL || key_len < IMAGE_KEY_LEN) {
        printf("invalid image key param, buf %p, len %u\n", image_key, key_len);
        return -1;
    }

    switch (alg) {
        case HMAC_SHA256:
            break;
        default:
            printf("current version not support this mode, alg: %d\n", alg);
            return -1;
    }

    args.alg = alg;
    if (user_param) {
        (void)memcpy(args.user_param, user_param, user_param_len);
        args.user_param_len = user_param_len;
    }

    fd = open(IMAGE_KEY_DEV_NAME, O_RDWR);
    if (fd < 0) {
        printf("open dev %s failed, err: %s\n", IMAGE_KEY_DEV_NAME, strerror(errno));
        return -1;
    }

    rc = ioctl(fd, IOCTL_IMAGE_KEY, &args);
    if (rc) {
        if (errno) {
            printf("ioctl failed, err: %s\n", strerror(errno));
        } else {
            printf("driver got image key failed\n");
        }
        (void)close(fd);
        return -1;
    }

    (void)memcpy(image_key, args.image_key, IMAGE_KEY_LEN);
    (void)memset(args.image_key, 0, IMAGE_KEY_LEN);
    (void)close(fd);
    return 0;
}