#ifndef TOKEN_VALIDATE_H
#define TOKEN_VALIDATE_H

#include <openssl/x509.h>
#include "t_cose/q_useful_buf.h"
#include "token_parse.h"

/* Store the virtCCA certs downloaded from HUAWEI PKI */
#define DEFAULT_ROOT_CERT_URL "\"https://download.huawei.com/dl/download.do?actionFlag=download&nid=PKI1000000002&partNo=3001&mid=SUP_PKI\""
#define DEFAULT_SUB_CERT_URL "\"https://download.huawei.com/dl/download.do?actionFlag=download&nid=PKI1000000040&partNo=3001&mid=SUP_PKI\""

#define DEFAULT_CERT_PEM_PREFIX "."
#define DEFAULT_ROOT_CERT_PEM_FILENAME "root_cert.pem"
#define DEFAULT_SUB_CERT_PEM_FILENAME "sub_cert.pem"
#define DEFAULT_AIK_CERT_PEM_FILENAME "aik_cert.pem"
#define MAX_FILE_NAME_SIZE 100
#define MAX_FILE_PATH_SIZE 1000
#define MAX_URL_SIZE 1000

typedef struct {
    char cert_path_prefix[MAX_FILE_PATH_SIZE];
    char root_cert_filename[MAX_FILE_NAME_SIZE];
    char sub_cert_filename[MAX_FILE_NAME_SIZE];
    char aik_cert_filename[MAX_FILE_NAME_SIZE];
    char root_cert_url[MAX_URL_SIZE];
    char sub_cert_url[MAX_URL_SIZE];
} cert_info_t;

bool validate_aik_cert_chain(X509 *x509_aik, X509 *x509_sub, X509 *x509_root);

bool verify_cvm_cose_sign(qbuf_t signed_cose, qbuf_t pub_key);

/*
/* Platform token validation functions
*/
bool verify_pubkhash_challenge(qbuf_t pub_key, qbuf_t challenge, qbuf_t algorithm);

bool verify_plat_cose_sign(qbuf_t signed_cose, X509 *x509_aik);

/*
/* Complete CCA token signature verification
*/
bool verify_cca_token_signatures(cert_info_t *cert_info,
                                 qbuf_t plat_cose,
                                 qbuf_t cvm_cose,
                                 qbuf_t cvm_pub_key,
                                 qbuf_t plat_challenge,
                                 qbuf_t cvm_pub_key_algo);

#endif /* TOKEN_VALIDATE_H */
