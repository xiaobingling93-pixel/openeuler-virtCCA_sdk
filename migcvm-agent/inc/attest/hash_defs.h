/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#ifndef HASH_DEFS_H
#define HASH_DEFS_H

#include <openssl/sha.h>

/* Use OpenSSL definitions, but add our own if they don't exist */
#ifndef SHA1_DIGEST_LENGTH
#define SHA1_DIGEST_LENGTH   20
#endif
#ifndef SHA256_DIGEST_LENGTH
#define SHA256_DIGEST_LENGTH 32
#endif
#ifndef SHA512_DIGEST_LENGTH
#define SHA512_DIGEST_LENGTH 64
#endif

#endif /* HASH_DEFS_H */