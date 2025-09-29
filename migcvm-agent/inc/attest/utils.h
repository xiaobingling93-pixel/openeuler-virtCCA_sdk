/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */
 
#ifndef UTILS_H
#define UTILS_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

int hex_to_bytes(unsigned char *in, size_t in_len, unsigned char *out, size_t *out_len);
int download_cert_pem(const char *prefix, const char *filename, const char *url);
int file_exists(const char *prefix, const char *filename);

/* File handling functions */
uint8_t* read_file_data(const char* filename, size_t* out_size);
char* read_text_file(const char* filename, size_t* out_size); 
bool save_file_data(const char *file_name, const unsigned char *data, size_t size);

#endif /* UTILS_H */
