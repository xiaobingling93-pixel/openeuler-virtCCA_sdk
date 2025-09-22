/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */

#include "platform_verify.h"
#include <errno.h>
#include <ctype.h>

static char* extract_json_string_value(const char* json, const char* key)
{
    char* value = NULL;
    char search_key[128];
    snprintf(search_key, sizeof(search_key), "\"%s\":", key);
    
    char* pos = strstr(json, search_key);
    if (pos) {
        pos = strchr(pos + strlen(search_key), '"');
        if (pos) {
            pos++;
            char* end = strchr(pos, '"');
            if (end) {
                size_t len = end - pos;
                value = (char*)malloc(len + 1);
                if (value) {
                    strncpy(value, pos, len);
                    value[len] = '\0';
                }
            }
        }
    }
    return value;
}

static char* read_file_content(const char* file_path)
{
    FILE* file = fopen(file_path, "r");
    if (!file) {
        printf("Failed to open file: %s\n", file_path);
        return NULL;
    }
    
    fseek(file, 0, SEEK_END);
    long file_size = ftell(file);
    fseek(file, 0, SEEK_SET);
    
    if (file_size <= 0) {
        printf("Invalid file size: %ld\n", file_size);
        fclose(file);
        return NULL;
    }
    
    char* content = (char*)malloc(file_size + 1);
    if (!content) {
        printf("Failed to allocate memory for file content\n");
        fclose(file);
        return NULL;
    }
    
    size_t read_size = fread(content, 1, file_size, file);
    content[read_size] = '\0';
    fclose(file);
    
    return content;
}

static bool parse_measure_values(const char* json_content, platform_ref_values_t* ref_values)
{
    char* measure_start = strstr(json_content, "\"measure_value\"");
    if (!measure_start) {
        printf("measure_value not found in JSON\n");
        return false;
    }
    
    char* array_start = strchr(measure_start, '[');
    if (!array_start) {
        printf("measure_value array start '[' not found\n");
        return false;
    }
    
    char* array_end = strchr(array_start, ']');
    if (!array_end) {
        printf("measure_value array end ']' not found\n");
        return false;
    }
    
    size_t object_count = 0;
    char* pos = array_start;
    while (pos < array_end && (pos = strchr(pos, '{')) != NULL) {
        object_count++;
        pos++;
    }
    
    if (object_count == 0) {
        printf("No objects found in measure_value array\n");
        return false;
    }
    
    ref_values->sw_components = (sw_component_ref_t*)malloc(object_count * sizeof(sw_component_ref_t));
    if (!ref_values->sw_components) {
        printf("Failed to allocate memory for sw_components\n");
        return false;
    }
    ref_values->sw_comp_count = object_count;
    
    pos = array_start;
    size_t index = 0;
    while (pos < array_end && index < object_count) {
        char* obj_start = strchr(pos, '{');
        if (!obj_start) {
            break;
        }
        
        char* obj_end = strchr(obj_start, '}');
        if (!obj_end) {
            break;
        }
        
        size_t obj_len = obj_end - obj_start + 1;
        char* obj_content = (char*)malloc(obj_len + 1);
        if (!obj_content) {
            printf("Failed to allocate memory for object content\n");
            break;
        }
        
        strncpy(obj_content, obj_start, obj_len);
        obj_content[obj_len] = '\0';
        
        char* firmware_name = extract_json_string_value(obj_content, "firware_name");
        char* measurement = extract_json_string_value(obj_content, "measurement");
        char* firmware_version = extract_json_string_value(obj_content, "firware_version");
        char* hash_algorithm = extract_json_string_value(obj_content, "hash_algorithm");
        
        if (firmware_name && measurement && firmware_version && hash_algorithm) {
            strncpy(ref_values->sw_components[index].firmware_name, firmware_name,
                    sizeof(ref_values->sw_components[index].firmware_name) - 1);
            strncpy(ref_values->sw_components[index].measurement, measurement,
                    sizeof(ref_values->sw_components[index].measurement) - 1);
            strncpy(ref_values->sw_components[index].firmware_version, firmware_version,
                    sizeof(ref_values->sw_components[index].firmware_version) - 1);
            strncpy(ref_values->sw_components[index].hash_algorithm, hash_algorithm,
                    sizeof(ref_values->sw_components[index].hash_algorithm) - 1);
            
            index++;
        } else {
            printf("Failed to parse component %zu - missing required fields\n", index);
        }
        
        if (firmware_name) {
            free(firmware_name);
        }
        if (measurement) {
            free(measurement);
        }
        if (firmware_version) {
            free(firmware_version);
        }
        if (hash_algorithm) {
            free(hash_algorithm);
        }
        free(obj_content);
        
        pos = obj_end + 1;
    }
    
    ref_values->sw_comp_count = index;
    return index > 0;
}

bool load_platform_ref_values(const char *json_file_path, platform_ref_values_t *ref_values)
{
    if (!json_file_path || !ref_values) {
        printf("Invalid parameters\n");
        return false;
    }
    
    memset(ref_values, 0, sizeof(platform_ref_values_t));
    
    char* json_content = read_file_content(json_file_path);
    if (!json_content) {
        return false;
    }
    
    bool result = parse_measure_values(json_content, ref_values);
    
    free(json_content);
    return result;
}

static bool compare_hex_strings(const char* hex1, const char* hex2)
{
    if (!hex1 || !hex2) {
        return false;
    }
    
    size_t len1 = strlen(hex1);
    size_t len2 = strlen(hex2);
    if (len1 != len2) {
        return false;
    }
    
    for (size_t i = 0; i < len1; i++) {
        if (tolower(hex1[i]) != tolower(hex2[i])) {
            return false;
        }
    }
    
    return true;
}

static char* qbuf_to_hex_string(const qbuf_t* buf)
{
    if (!buf || !buf->ptr || buf->len == 0) {
        return NULL;
    }
    
    char* hex_str = (char*)malloc(buf->len * 2 + 1);
    if (!hex_str) {
        return NULL;
    }
    
    for (size_t i = 0; i < buf->len; i++) {
        sprintf(hex_str + (i * 2), "%02x", ((unsigned char*)buf->ptr)[i]);
    }
    hex_str[buf->len * 2] = '\0';
    
    return hex_str;
}

static char* qbuf_to_string(const qbuf_t* buf)
{
    if (!buf || !buf->ptr || buf->len == 0) {
        return NULL;
    }
    
    char* str = (char*)malloc(buf->len + 1);
    if (!str) {
        return NULL;
    }
    
    memcpy(str, buf->ptr, buf->len);
    str[buf->len] = '\0';
    
    return str;
}

static bool verify_single_sw_component(const sw_comp_claims_t* token_comp,
                                       const sw_component_ref_t* ref_comp,
                                       const char* component_name,
                                       uint64_t component_index)
{
    bool match = true;
    bool has_mismatch = false;
    
    char* token_type = qbuf_to_string(&token_comp->component_type);
    if (!token_type) {
        printf("Component %lu (%s): Failed to extract component type from token\n",
               component_index, component_name);
        return false;
    }
    
    if (strcmp(token_type, ref_comp->firmware_name) != 0) {
        if (!has_mismatch) {
            printf("Component %lu (%s) verification FAILED:\n", component_index, component_name);
            has_mismatch = true;
        }
        printf("  Component Type: MISMATCH (token: %s, ref: %s)\n",
               token_type, ref_comp->firmware_name);
        match = false;
    }
    free(token_type);
    
    char* token_measurement = qbuf_to_hex_string(&token_comp->measurement);
    if (!token_measurement) {
        printf("Component %lu (%s): Failed to extract measurement from token\n",
               component_index, component_name);
        return false;
    }
    
    if (!compare_hex_strings(token_measurement, ref_comp->measurement)) {
        if (!has_mismatch) {
            printf("Component %lu (%s) verification FAILED:\n", component_index, component_name);
            has_mismatch = true;
        }
        printf("  Measurement: MISMATCH\n");
        printf("    Token:     %s\n", token_measurement);
        printf("    Reference: %s\n", ref_comp->measurement);
        match = false;
    }
    free(token_measurement);
    
    char* token_version = qbuf_to_string(&token_comp->version);
    if (!token_version) {
        printf("Component %lu (%s): Failed to extract version from token\n",
               component_index, component_name);
        return false;
    }
    
    if (strcmp(token_version, ref_comp->firmware_version) != 0) {
        if (!has_mismatch) {
            printf("Component %lu (%s) verification FAILED:\n", component_index, component_name);
            has_mismatch = true;
        }
        printf("  Version: MISMATCH (token: %s, ref: %s)\n",
               token_version, ref_comp->firmware_version);
        match = false;
    }
    free(token_version);
    
    return match;
}

bool verify_platform_sw_components(const platform_claims_t *platform_claims,
                                   const platform_ref_values_t *ref_values)
{
    if (!platform_claims || !ref_values) {
        printf("Invalid parameters for sw-components verification\n");
        return false;
    }
    
    if (!platform_claims->sw_components || platform_claims->sw_comp_cnts == 0) {
        printf("No software components found in platform token\n");
        return false;
    }
    
    if (!ref_values->sw_components || ref_values->sw_comp_count == 0) {
        printf("No reference values loaded\n");
        return false;
    }
    
    bool overall_result = true;
    size_t matched_count = 0;
    
    /*
     * iterate through each component in token,
     * find matching component in reference values
     */
    for (uint64_t i = 0; i < platform_claims->sw_comp_cnts; i++) {
        const sw_comp_claims_t* token_comp = &platform_claims->sw_components[i];
        
        char* token_type = qbuf_to_string(&token_comp->component_type);
        if (!token_type) {
            printf("Failed to extract component type from token component %lu\n", i);
            overall_result = false;
            continue;
        }
        
        bool found_match = false;
        for (size_t j = 0; j < ref_values->sw_comp_count; j++) {
            const sw_component_ref_t* ref_comp = &ref_values->sw_components[j];
            
            if (strcmp(token_type, ref_comp->firmware_name) == 0) {
                if (verify_single_sw_component(token_comp, ref_comp, token_type, i)) {
                    matched_count++;
                    found_match = true;
                } else {
                    overall_result = false;
                }
                break;
            }
        }
        
        if (!found_match) {
            printf("Component %lu (%s) verification FAILED:\n", i, token_type);
            printf("  No matching reference component found for: %s\n", token_type);
            overall_result = false;
        }
        
        free(token_type);
    }
    
    return overall_result;
}

void free_platform_ref_values(platform_ref_values_t *ref_values)
{
    if (ref_values && ref_values->sw_components) {
        free(ref_values->sw_components);
        ref_values->sw_components = NULL;
        ref_values->sw_comp_count = 0;
    }
} 