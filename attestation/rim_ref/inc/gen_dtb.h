/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * virtCCA_sdk is licensed under the Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan PSL v2.
 * You may obtain a copy of Mulan PSL v2 at:
 *     http://license.coscl.org.cn/MulanPSL2
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
 * PURPOSE.
 * See the Mulan PSL v2 for more details.
 */
#ifndef QEMU_MODIFIER_H
#define QEMU_MODIFIER_H

#ifdef __cplusplus
extern "C" {
#endif

// Set the configuration file path and the dest dtb file path
#define MACHINE_PARAM "-machine"
#define DEFAULT_MACHINE " -machine virt,dumpdtb=/tmp/dump.dtb"
#define MAX_CMD_LENGTH 8192
#define MAX_OPTION_LENGTH 2048
#define MAX_INPUT_LENGTH 256

#define DEFAULT_DUMPDTB_PATH "./dump.dtb"
#define DUMPDTB_LOG_PATH "./dumpdtb.log"

typedef struct {
    char config_file[MAX_INPUT_LENGTH];
    char dtb_dump_path[MAX_INPUT_LENGTH];
    char qemu_bin_path[MAX_INPUT_LENGTH];
    char kata_cfg_path[MAX_INPUT_LENGTH];
    char kbs_cfg_path[MAX_INPUT_LENGTH];
    char initramfs_path[MAX_INPUT_LENGTH];
    long tec_num;
    char kernel_path[MAX_INPUT_LENGTH];
    char qemu_instr[MAX_CMD_LENGTH];
} ModifierConfig;

typedef struct {
    const char *device_name;
} DeviceFilter;

typedef struct {
    char removed_devices[10][MAX_OPTION_LENGTH];
    int count;
} RemovedDevices;

typedef struct {
    const char *flag;
    int has_value;
} QemuFlag;

void modify_machine_param(char *cmd, const char *dtb_dump_param);
void modify_append_arguments(char *cmd);
void remove_flags_from_command(char *cmd);
void remove_specific_devices(char *cmd, RemovedDevices *removed_devices);
void modify_socket_path(char *cmd);
int execute_command(const char *command, const char *qemu_bin_path, const char *log_path);
void generate_dtb_with_kata_config(char *qemu_bin_path, char *cmd);

#ifdef __cplusplus
}
#endif

#endif // QEMU_MODIFIER_H
