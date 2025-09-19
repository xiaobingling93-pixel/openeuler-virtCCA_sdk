#ifndef BINARY_BLOB_H
#define BINARY_BLOB_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#define BYTES_PER_LINE 16

typedef struct {
    uint8_t* data;
    size_t length;
    size_t base_address;
} binary_blob_t;

/* binary data manipulation function */
bool binary_blob_init(binary_blob_t* blob, uint8_t* data, size_t length, size_t base);
uint16_t binary_blob_get_uint16(const binary_blob_t* blob, size_t* pos);
uint8_t binary_blob_get_uint8(const binary_blob_t* blob, size_t* pos);
uint32_t binary_blob_get_uint32(const binary_blob_t* blob, size_t* pos);
uint64_t binary_blob_get_uint64(const binary_blob_t* blob, size_t* pos);
void binary_blob_get_bytes(const binary_blob_t* blob, size_t* pos, size_t count, uint8_t* out);
void binary_blob_dump(const binary_blob_t* blob);


#endif /* BINARY_BLOB_H */