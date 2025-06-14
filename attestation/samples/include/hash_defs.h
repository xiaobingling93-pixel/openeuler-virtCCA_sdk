#ifndef HASH_DEFS_H
#define HASH_DEFS_H

/* Check if OpenSSL headers are already included */
#ifndef SHA384_DIGEST_LENGTH
/* Define hash digest lengths if not already defined by OpenSSL */
#define SHA1_DIGEST_LENGTH   20
#define SHA256_DIGEST_LENGTH 32
#define SHA384_DIGEST_LENGTH 48
#define SHA512_DIGEST_LENGTH 64
#endif

#endif /* HASH_DEFS_H */