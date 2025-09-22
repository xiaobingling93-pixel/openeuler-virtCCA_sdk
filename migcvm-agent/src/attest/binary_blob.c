/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdbool.h>
#include <stdint.h>
#include "binary_blob.h"
#include "utils.h"

bool binary_blob_init(binary_blob_t* blob, uint8_t* data, size_t length, size_t base)
{
    if (!blob || !data || length == 0) {
        return false;
    }

    blob->data = data;
    blob->length = length;
    blob->base_address = base;

    return true;
}

static bool check_boundary(const binary_blob_t* blob, size_t* pos, size_t size)
{
    if (!blob || !pos || *pos + size > blob->length) {
        printf("DEBUG: Boundary check failed: pos=%zu, size=%zu, blob_length=%zu\n",
               *pos, size, blob ? blob->length : 0);
        return false;
    }
    return true;
}

uint16_t binary_blob_get_uint16(const binary_blob_t* blob, size_t* pos)
{
    uint16_t value = 0;
    
    if (!check_boundary(blob, pos, sizeof(uint16_t))) {
        return 0;
    }

    /* Little-endian read */
    value = (uint16_t)blob->data[*pos] |
            ((uint16_t)blob->data[*pos + 1] << 8);
    
    *pos += sizeof(uint16_t);
    return value;
}

uint8_t binary_blob_get_uint8(const binary_blob_t* blob, size_t* pos)
{
    if (!check_boundary(blob, pos, sizeof(uint8_t))) {
        return 0;
    }

    uint8_t value = blob->data[*pos];
    *pos += sizeof(uint8_t);
    return value;
}

uint32_t binary_blob_get_uint32(const binary_blob_t* blob, size_t* pos)
{
    uint32_t value = 0;
    if (!check_boundary(blob, pos, sizeof(uint32_t))) {
        return 0;
    }

    memcpy(&value, &blob->data[*pos], sizeof(uint32_t));
    *pos += sizeof(uint32_t);
    return value;
}

uint64_t binary_blob_get_uint64(const binary_blob_t* blob, size_t* pos)
{
    uint64_t value = 0;
    
    if (!check_boundary(blob, pos, sizeof(uint64_t))) {
        return 0;
    }

    /* Little-endian read */
    for (int i = 0; i < 8; i++) {
        value |= ((uint64_t)blob->data[*pos + i] << (i * 8));
    }
    
    *pos += sizeof(uint64_t);
    return value;
}

void binary_blob_get_bytes(const binary_blob_t* blob, size_t* pos, size_t count, uint8_t* out)
{
    if (!check_boundary(blob, pos, count) || !out) {
        memset(out, 0, count);
        return;
    }

    memcpy(out, &blob->data[*pos], count);
    *pos += count;
}

void binary_blob_dump(const binary_blob_t* blob)
{
    if (!blob || !blob->data) {
        return;
    }

    printf("Binary Data:\n");
    printf("Base Address: 0x%zX\n", blob->base_address);
    printf("Length: %zu bytes\n\n", blob->length);

    char ascii_buf[17] = {0};
    size_t i;

    for (i = 0; i < blob->length; i++) {
        /* Check if encountered consecutive 0xFF */
        if (blob->data[i] == 0xFF) {
            size_t j;
            for (j = i + 1; j < blob->length && j < i + 32; j++) {
                if (blob->data[j] != 0xFF) break;
            }
            if (j == i + 32) {
                /* Print ASCII part of the last line */
                if (i % 16 != 0) {
                    for (size_t k = i % 16; k < 16; k++) {
                        printf("   ");
                    }
                    printf("  %s\n", ascii_buf);
                }
                printf("\n[Remaining data omitted - all 0xFF]\n");
                return;
            }
        }

        if (i % 16 == 0) {
            if (i > 0) {
                printf("  %s\n", ascii_buf);
            }
            printf("%08zX  ", blob->base_address + i);
            memset(ascii_buf, 0, sizeof(ascii_buf));
        }

        printf("%02X ", blob->data[i]);
        ascii_buf[i % 16] = isprint(blob->data[i]) ? blob->data[i] : '.';
    }

    /* Print last line */
    if (i % 16 != 0) {
        for (size_t j = i % 16; j < 16; j++) {
            printf("   ");
        }
    }
    printf("  %s\n", ascii_buf);
}