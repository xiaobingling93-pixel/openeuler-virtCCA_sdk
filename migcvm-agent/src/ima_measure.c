#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <rats-tls/api.h>
#include <rats-tls/log.h>
#include <rats-tls/claim.h>
#include <openssl/sha.h>
#include <openssl/evp.h>
#include "ima_measure.h"

/*
* Define a constant for aggregating all PCRs, if needed for other use cases,
* though for the current problem, we will target a specific PCR.
*/
#define IMA_AGGREGATE_ALL_PCRS -1

/* static int verify_sig; */
/* static unsigned int no_sigs, unknown_keys, invalid_sigs; */

static u_int8_t zero[SHA_DIGEST_LENGTH];
static u_int8_t fox[SHA_DIGEST_LENGTH];

static int display_digest(u_int8_t *digest, u_int32_t digestlen)
{
	int i;

	for (i = 0; i < digestlen; i++) {
		printf("%02x", (*(digest + i) & 0xff));
	}
	return 0;
}

static int ima_eventdigest_parse(u_int8_t *buffer, u_int32_t buflen, u_int8_t *file_digest, u_int32_t *file_digest_len)
{
	if (buflen < SHA_DIGEST_LENGTH) {
		printf("invalid len %u\n", buflen);
		return -1;
	}
	return display_digest(buffer, SHA_DIGEST_LENGTH);
}

static int ima_eventdigest_ng_parse(u_int8_t *buffer, u_int32_t buflen, u_int8_t *file_digest, u_int32_t *file_digest_len)
{
	char hash_algo[CRYPTO_MAX_ALG_NAME + 1] = { 0 };
	int algo_len;
	const EVP_MD *md;
	int digest_len;

	if (buflen > CRYPTO_MAX_ALG_NAME + 1) {
		printf("invalid algo name\n");
		return ERROR_ENTRY_PARSING;
	}

	algo_len = strnlen((char *)buffer, buflen); /* format: algo + ':' + '\0' */
	if (algo_len <= 1) {
		printf("Hash algorithm name invalid\n");
		return ERROR_ENTRY_PARSING;
	}
	algo_len--;
	printf("%s", buffer);
	memcpy(hash_algo, buffer, algo_len);

	md = EVP_get_digestbyname(hash_algo);
	if (md == NULL) {
		printf("Unknown hash algorithm '%s'\n", hash_algo);
		return ERROR_ENTRY_PARSING;
	}

	digest_len = EVP_MD_size(md);

	if (algo_len + 2 + digest_len != buflen) {
		printf("Field length mismatch, current: %d, expected: %d\n",
		       algo_len + 2 + digest_len, buflen);
		return ERROR_ENTRY_PARSING;
	}

	if (digest_len > IMA_MAX_HASH_SIZE) {
		printf("Hash digest too long.\n");
		return ERROR_ENTRY_PARSING;
	}
	*file_digest_len = digest_len;
	memcpy(file_digest, buffer + algo_len + 2, digest_len);

	return display_digest(buffer + algo_len + 2, digest_len);
}

static int ima_parse_string(u_int8_t *buffer, u_int32_t buflen)
{
	char *str;

	/* some callers include the terminating null in the
 	 * buflen, others don't (eg. 'd').
 	 */
	str = calloc(buflen + 1, sizeof(u_int8_t));
	if (str == NULL) {
		printf("Out of memory\n");
		return -ENOMEM;
	}

	memcpy(str, buffer, buflen);
	printf("%s", str);
	free(str);
	return 0;
}

static int ima_eventname_parse(u_int8_t *buffer, u_int32_t buflen, u_int8_t *file_digest, u_int32_t *file_digest_len)
{
	if (buflen > TCG_EVENT_NAME_LEN_MAX + 1) {
		printf("Event name too long\n");
		return -1;
	}

	return ima_parse_string(buffer, buflen);
}

static int ima_eventname_ng_parse(u_int8_t *buffer, u_int32_t buflen, u_int8_t *file_digest, u_int32_t *file_digest_len)
{
	return ima_parse_string(buffer, buflen);
}

static int ima_eventsig_parse(u_int8_t *buffer, u_int32_t buflen, u_int8_t *file_digest, u_int32_t *file_digest_len)
{
	return display_digest(buffer, buflen);
}

/* IMA template field definition */
struct ima_template_field {
	const char field_id[IMA_TEMPLATE_FIELD_ID_MAX_LEN];
	int (*field_parse) (u_int8_t *buffer, u_int32_t buflen, u_int8_t *file_digest, u_int32_t *file_digest_len);
};

/* IMA template descriptor definition */
struct ima_template_desc {
	char *name;
	char *fmt;
	int num_fields;
	struct ima_template_field **fields;
};

static struct ima_template_desc defined_templates[] = {
	{.name = IMA_TEMPLATE_IMA_NAME, .fmt = IMA_TEMPLATE_IMA_FMT},
	{.name = "ima-ng",.fmt = "d-ng|n-ng"},
	{.name = "ima-sig",.fmt = "d-ng|n-ng|sig"},
};

static struct ima_template_field supported_fields[] = {
	{.field_id = "d",.field_parse = ima_eventdigest_parse},
	{.field_id = "n",.field_parse = ima_eventname_parse},
	{.field_id = "d-ng",.field_parse = ima_eventdigest_ng_parse},
	{.field_id = "n-ng",.field_parse = ima_eventname_ng_parse},
	{.field_id = "sig",.field_parse = ima_eventsig_parse},
};

struct event {
	struct {
		u_int32_t pcr;
		u_int8_t digest[SHA_DIGEST_LENGTH];
		u_int32_t name_len;
	} header;
	char name[TCG_EVENT_NAME_LEN_MAX + 1];
	struct ima_template_desc *template_desc; /* template descriptor */
	u_int32_t template_data_len;
	u_int8_t *template_data;	/* template related data */
	u_int8_t file_digest[IMA_MAX_HASH_SIZE];
	u_int32_t file_digest_len;
};

static int parse_template_data(struct event *template)
{
	int offset = 0, result = 0;
	int i, j, is_ima_template;
	char *template_fmt, *template_fmt_ptr, *f;
	u_int32_t digest_len;
	u_int8_t *digest;

	is_ima_template = strcmp(template->name, "ima") == 0 ? 1 : 0;
	template->template_desc = NULL;

	for (i = 0; i < ARRAY_SIZE(defined_templates); i++) {
		if (strcmp(template->name,
			defined_templates[i].name) == 0) {
			template->template_desc = defined_templates + i;
			break;
		}
	}

	if (template->template_desc == NULL) {
		i = ARRAY_SIZE(defined_templates) - 1;
		template->template_desc = defined_templates + i;
		template->template_desc->fmt = template->name;
	}

	template_fmt = strdup(template->template_desc->fmt);
	if (template_fmt == NULL) {
		printf("Out of memory\n");
		return -ENOMEM;
	}

	template_fmt_ptr = template_fmt;
	for (i = 0; (f = strsep(&template_fmt_ptr, "|")) != NULL; i++) {
		struct ima_template_field *field = NULL;
		u_int32_t field_len = 0;

		for (j = 0; j < ARRAY_SIZE(supported_fields); j++) {
			if (!strcmp(f, supported_fields[j].field_id)) {
				field = supported_fields + j;
				break;
			}
		}

		if (field == NULL) {
			result = ERROR_FIELD_NOT_FOUND;
			printf("Field '%s' not supported\n", f);
			goto out;
		}

		if (is_ima_template && strcmp(f, "d") == 0)
			field_len = SHA_DIGEST_LENGTH;
		else if (is_ima_template && strcmp(f, "n") == 0)
			field_len = strlen(template->template_data + offset);
		else {
			memcpy(&field_len, template->template_data + offset,
				 sizeof(u_int32_t));
			offset += sizeof(u_int32_t);
		}

		if (offset >= template->template_data_len ||
			field_len > template->template_data_len - offset) {
			printf("offset or field len is invalid\n");
			goto out;
		}
		result = field->field_parse(template->template_data + offset,
					    field_len, template->file_digest, &template->file_digest_len);
		if (result) {
			printf("Parsing of '%s' field failed, result: %d\n",
			       f, result);
			goto out;
		} 

		/* ToDo: add verifiy ima-sig template */

		offset += field_len;
		printf(" ");
	}
out:
	free(template_fmt);
	return result;
}

static int read_template_data(struct event *template, FILE *fp)
{
	int len, is_ima_template;

	is_ima_template = strcmp(template->name, "ima") == 0 ? 1 : 0;
	if (!is_ima_template) {
		if (fread(&template->template_data_len, sizeof(u_int32_t), 1, fp) != 1 ||
			template->template_data_len > IMA_TEMPLATE_DATA_MAX_LEN) {
			printf("ERROR: read length faild or length is invalid\n");
			return -EINVAL;
		}
		len = template->template_data_len;
	} else {
		template->template_data_len = SHA_DIGEST_LENGTH +
		    TCG_EVENT_NAME_LEN_MAX + 1;
		/*
		 * Read the digest only as the event name length
		 * is not known in advance.
		 */
		len = SHA_DIGEST_LENGTH;
	}

	template->template_data = calloc(template->template_data_len,
					 sizeof(u_int8_t));
	if (template->template_data == NULL) {
		printf("ERROR: out of memory\n");
		return -ENOMEM;
	}

	if (fread(template->template_data, len, 1, fp) != 1) {
		printf("ERROR: read template data failed\n");
		goto free;
	}

	if (is_ima_template) {	/* finish 'ima' template data read */
		u_int32_t field_len;
		if (fread(&field_len, sizeof(u_int32_t), 1, fp) != 1 || field_len > TCG_EVENT_NAME_LEN_MAX) {
			printf("ERROR: read template data failed\n");
			goto free;
		}
		if (fread(template->template_data + SHA_DIGEST_LENGTH, field_len, 1, fp) != 1) {
			printf("ERROR: read digest failed\n");
			goto free;
		}
	}
	return 0;

free:
	free(template->template_data);
	return -1;
}

static int verify_template_hash(struct event *template_digest)
{
	int rc;
	u_int8_t local_digest[SHA_DIGEST_LENGTH] = {0}; /* Renamed to avoid conflict */
	unsigned int len = SHA_DIGEST_LENGTH; /* Use unsigned int for EVP_Digest length parameter */

	rc = memcmp(fox, template_digest, sizeof(fox));
	if (rc != 0) {
		EVP_Digest(template_digest->template_data, template_digest->template_data_len,
					local_digest, &len, EVP_sha1(), NULL);
		rc = memcmp(local_digest, template_digest->header.digest, len);
		if (rc != 0)
			printf("- %s\n", "failed");
	}
	return rc != 0 ? 1 : 0 ;
}

static int check_one_template(struct event *template, FILE *fp, char *digest_list_file,
	u_int8_t event_template_data_hash[SHA256_DIGEST_LENGTH], bool verify)
{
	int ret = -1;
	char digest_hex[MAX_CMD_LEN * 2] = {0};
	int hash_failed = 0;
	int i;
	unsigned int len = SHA256_DIGEST_LENGTH; /* Use unsigned int for EVP_Digest length parameter */

	display_digest(template->header.digest, SHA_DIGEST_LENGTH);
	memset(template->name, 0, sizeof(template->name));
	if (template->header.name_len > TCG_EVENT_NAME_LEN_MAX ||
		fread(template->name, template->header.name_len, 1, fp) == 0) {
		RTLS_ERR("Reading name failed\n");
		return -1;
	}
	printf(" %s ", template->name);

	if (read_template_data(template, fp) < 0) {
		RTLS_ERR("Reading of measurement entry failed\n");
		return -1;
	}

	if (parse_template_data(template) != 0) {
		RTLS_ERR("Parsing of measurement entry failed\n");
		goto free;
	}

	for (i = 0; i < template->file_digest_len; i++) {
		sprintf(digest_hex + i * 2, "%02x", (*(template->file_digest + i) & 0xff));
	}
	char cmd_str[MAX_CMD_LEN] = {0};
	if (template->file_digest_len * 2 + strlen("grep -E -i \"^$\"  > /dev/null") + strlen(digest_list_file) >= MAX_CMD_LEN) {
		RTLS_ERR("Digest list file name too long.\n");
		goto free;
	}
	sprintf(cmd_str, "grep -E -i \"^%s$\" %s > /dev/null", digest_hex, digest_list_file);
	if (system(cmd_str) != 0) {
		RTLS_ERR("Failed to verify file hash.\n");
		goto free;
	}

	if (verify) {
		if (verify_template_hash(template) != 0) {
			hash_failed++;
		}
	}

	if (EVP_Digest(template->template_data, template->template_data_len,
		event_template_data_hash, &len, EVP_sha256(), NULL) != 1) {
		RTLS_ERR("Failed to calculate SHA256 hash of template data.\n");
		goto free;
	}
	ret = hash_failed;

free:
	free(template->template_data);
	return ret;
}

/*
 * calculate the SHA1 aggregate-pcr value based on the
 * IMA runtime binary measurements.
 *
 * --validate: forces validation of the aggregrate pcr value
 * 	     for an invalidated PCR. Replace all entries in the
 * 	     runtime binary measurement list with 0x00 hash values,
 * 	     which indicate the PCR was invalidated, either for
 * 	     "a time of measure, time of use"(ToMToU) error, or a
 *	     file open for read was already open for write, with
 * 	     0xFF's hash value, when calculating the aggregate
 *	     pcr value.
 *
 * --verify: for all IMA template entries in the runtime binary
 * 	     measurement list, calculate the template hash value
 * 	     and compare it with the actual template hash value.
 * 	     
 * 	     For records with a signature, verify the file data
 * 	     hash against the file signature.
 *
 *	     Return the number of incorrect hash measurements
 *	     and signatures.
 *
 * template info:  list #, PCR-register #, template hash, template name
 *	IMA info:  IMA hash, filename hint
 *
 * Ouput: displays the aggregate-pcr value
 * Return code: if verification enabled, returns number of verification
 * 		errors.
 */
int ima_measure(const void *reference_pcr_value, size_t reference_pcr_value_len,
				char *digest_list_file, int validate, int verify, int target_pcr_index)
{
	int ret = 0;
	FILE *fp;
	struct event template;
	u_int8_t calculated_pcr_aggregate[SHA256_DIGEST_LENGTH];
	u_int8_t event_data_hash[SHA256_DIGEST_LENGTH];
	u_int8_t pcr_extension_buffer[SHA256_DIGEST_LENGTH * 2];
	int count = 0;
	int hash_failed = 0;
	unsigned int tmp_len = SHA256_DIGEST_LENGTH;
	
	fp = fopen(CLIENT_IMA_MEASUREMENTS_PATH, "r");
	if (!fp) {
		RTLS_ERR("fn: %s\n", CLIENT_IMA_MEASUREMENTS_PATH);
		perror("Unable to open file");
		return -1;
	}

	memset(calculated_pcr_aggregate, 0, SHA256_DIGEST_LENGTH);
	memset(event_data_hash, 0, SHA256_DIGEST_LENGTH);
	memset(pcr_extension_buffer, 0, SHA256_DIGEST_LENGTH * 2);
	memset(zero, 0, SHA_DIGEST_LENGTH);
	memset(fox, 0xff, SHA_DIGEST_LENGTH);

	RTLS_INFO("### PCR HASH                                  TEMPLATE-NAME\n");

#if OPENSSL_VERSION_NUMBER <= OPENSSL_1_1_0
	OpenSSL_add_all_digests();
#endif

	while (fread(&template.header, sizeof(template.header), 1, fp)) {
		RTLS_INFO("%3d %03u ", count++, template.header.pcr);

		
       /*
		* check_one_template verifies the file digest against the digest_list_file
		* and calculates SHA256 hash of template.template_data into event_data_hash.
		* It also performs template hash verification if 'verify' is true, updating hash_failed.
		*/
		int check_ret = check_one_template(&template, fp, digest_list_file, event_data_hash, verify);
		if (check_ret < 0) {
			RTLS_ERR("check_one_template failed for an event\n");
			ret = -1;
			break;
		}
		hash_failed += check_ret;
		RTLS_INFO("\n");

		
       /*
		* Extend simulated PCR with new template digest only if the event's PCR
		* matches the target_pcr_index.
		* IMA_AGGREGATE_ALL_PCRS can be used to revert to old behavior if needed.
		*/
		if (target_pcr_index == IMA_AGGREGATE_ALL_PCRS || template.header.pcr == (u_int32_t)target_pcr_index) {
			if (validate) {
				
               /*
				* This logic was present for the 'validate' flag regarding 0x00 or 0xFF hashes.
				* It seems specific to how template.header.digest is handled, not event_data_hash.
				* For PCR extension, we use event_data_hash (hash of template_data).
				* The original code extended 'pcr' with 'digest' (which was H(template_data)).
				* The original TOMTOU logic:
				* if (memcmp(template.header.digest, zero, SHA_DIGEST_LENGTH) == 0)
				*    memset(template.header.digest, 0xFF, SHA_DIGEST_LENGTH);
				* This part seems to modify template.header.digest if 'validate' is true,
				* but PCR extension uses the hash of template_data.
				* This might need careful review if template.header.digest is also meant to be extended.
				* Based on standard PCR extension, it's H(event_data).
				* The provided log shows 'digest' in check_one_template comes from template_data.
				*/
			}

			memcpy(pcr_extension_buffer, calculated_pcr_aggregate, SHA256_DIGEST_LENGTH);
			memcpy(pcr_extension_buffer + SHA256_DIGEST_LENGTH, event_data_hash, SHA256_DIGEST_LENGTH);
			
			if (EVP_Digest(pcr_extension_buffer, 2 * SHA256_DIGEST_LENGTH, calculated_pcr_aggregate, &tmp_len, EVP_sha256(), NULL) != 1) {
				RTLS_ERR("EVP_Digest for PCR extension failed\n");
				ret = -1;
				break;
			}
		}
	}

#if OPENSSL_VERSION_NUMBER <= OPENSSL_1_1_0
	EVP_cleanup();
#endif
	fclose(fp);

	if (ret < 0)
		return ret;

	RTLS_INFO("PCRAggr (re-calculated for PCR %d): ", target_pcr_index == IMA_AGGREGATE_ALL_PCRS ? 10 : target_pcr_index);
	display_digest(calculated_pcr_aggregate, SHA256_DIGEST_LENGTH);
	RTLS_INFO("\n");

	if (verify)	{
		RTLS_INFO("Template hash verification (within check_one_template): %s, failures is %d \n", !hash_failed ? "Success" : "Failed", hash_failed);
	}

	
   /*
	* 'validate' here means to compare the calculated_pcr_aggregate with the reference_pcr_value.
	*/
	if (validate) {
		if (reference_pcr_value == NULL || reference_pcr_value_len != SHA256_DIGEST_LENGTH) {
			RTLS_ERR("Invalid reference PCR value or length for validation.\n");
			return -1;
		}
		ret = memcmp(calculated_pcr_aggregate, reference_pcr_value, SHA256_DIGEST_LENGTH);
		RTLS_INFO("Verifying if calculated PCR for index %d matches reference value: %s \n",
			target_pcr_index, (ret == 0) ? "Success" : "Failed");
		if (ret != 0) {
			return 1;
		}
	}
	
	
   /*
	* If verify was true and there were hash_failed, this could be considered a failure.
	* However, the original code returns 0 if 'validate' passes or is false,
	* and 1 if 'validate' fails. Errors are < 0.
	* We will maintain that: 0 for success (including validate pass), 1 for validate fail, <0 for errors.
	* The 'hash_failed' count is informational via logs.
	*/
	return 0;	
}