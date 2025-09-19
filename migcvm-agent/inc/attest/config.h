#ifndef CONFIG_H
#define CONFIG_H

#include <stddef.h>

typedef struct {
    const char* ccel_file;      /* CCEL file path */
    const char* event_log_file; /* Event log file path */
    const char* rem_file;       /* REM file path */
    const char* json_file;      /* JSON reference file path */
} config_t;

extern config_t g_config;

#endif /* CONFIG_H */