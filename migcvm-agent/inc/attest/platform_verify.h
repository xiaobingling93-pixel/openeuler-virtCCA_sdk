#ifndef PLATFORM_VERIFY_H
#define PLATFORM_VERIFY_H

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "token_parse.h"

/*
 * Reference value structure corresponding to measure_value in JSON file
 */
typedef struct {
    char firmware_name[64];      /* Firmware name, e.g. "ipu", "imu" */
    char measurement[128];       /* Measurement value in hex string */
    char firmware_version[32];   /* Firmware version, e.g. "21.21.0" */
    char hash_algorithm[16];     /* Hash algorithm, e.g. "sha256" */
} sw_component_ref_t;

typedef struct {
    sw_component_ref_t *sw_components;  /* Software component reference values array */
    size_t sw_comp_count;              /* Number of software components */
} platform_ref_values_t;

/*
 * Load platform reference values from JSON file
 *
 * @param json_file_path JSON file path
 * @param ref_values Output reference values structure
 * @return true on success, false on failure
 */
bool load_platform_ref_values(const char *json_file_path, platform_ref_values_t *ref_values);

/*
 * Verify sw-components in platform token
 *
 * @param platform_claims Platform claims parsed from token
 * @param ref_values Reference values
 * @return true on verification success, false on verification failure
 */
bool verify_platform_sw_components(const platform_claims_t *platform_claims,
                                   const platform_ref_values_t *ref_values);
void free_platform_ref_values(platform_ref_values_t *ref_values);
#endif /* PLATFORM_VERIFY_H */ 