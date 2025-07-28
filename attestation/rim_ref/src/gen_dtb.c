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

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "gen_rim_ref.h"
#include "gen_dtb.h"

// device list
DeviceFilter removable_devices[] = {
    {"vhost-user-fs-pci"},
    {"vhost-vsock-pci"}
};
const int removable_device_count = sizeof(removable_devices) / sizeof(removable_devices[0]);

// flag list
QemuFlag removable_flags[] = {
    {"-name", 1},
    {"-uuid", 1},
    {"-pidfile", 1},
    {"-qmp", 1},
    {"-netdev", 1}
};

const int removable_flag_count = sizeof(removable_flags) / sizeof(removable_flags[0]);

void skip_spaces(char **ptr)
{
    while (**ptr && isspace(**ptr)) {
        (*ptr)++;
    }
}

void skip_no_spaces(char **ptr)
{
    while (**ptr && !isspace(**ptr)) {
        (*ptr)++;
    }
}

// modify -machine, inject dumpdtb
void modify_machine_param(char *cmd, const char *dtb_dump_param)
{
    char *machine_pos = strstr(cmd, MACHINE_PARAM);
    char modified_cmd[MAX_CMD_LENGTH] = {0};

    if (machine_pos) {
        char *machine_start = strchr(machine_pos, ' ');
        if (!machine_start) {
            return; // invalid -machine param
        }
        machine_start++;

        char *machine_end = strchr(machine_start, ' ');
        char machine_value[MAX_CMD_LENGTH] = {0};
        int len;

        if (!machine_end) {
            len = snprintf(machine_value, sizeof(machine_value), "%s", machine_start);
            if (len < 0 || (size_t)len >= sizeof(machine_value)) {
                return;
            }
        } else {
            len = snprintf(machine_value, sizeof(machine_value), "%.*s",
                           (int)(machine_end - machine_start), machine_start);
            if (len < 0 || (size_t)len >= sizeof(machine_value)) {
                return;
            }
        }

        if (!strstr(machine_value, "dumpdtb=")) {
            size_t current_len = strlen(machine_value);
            size_t remaining = sizeof(machine_value) - current_len;

            len = snprintf(machine_value + current_len, remaining, ",dumpdtb=%s", dtb_dump_param);
            if (len < 0 || (size_t)len >= remaining) {
                return;
            }

            size_t prefix_len = machine_start - cmd;
            if (prefix_len >= sizeof(modified_cmd)) {
                return;
            }

            strncpy(modified_cmd, cmd, prefix_len);
            modified_cmd[prefix_len] = '\0';

            strcat(modified_cmd, machine_value);
            if (machine_end) {
                strcat(modified_cmd, machine_end);
            }
            (void)snprintf(cmd, MAX_CMD_LENGTH, "%s", modified_cmd);
        }
    } else {
        char *first_space = strchr(cmd, ' ');
        if (first_space) {
            size_t prefix_len = first_space - cmd + 1;
            strncpy(modified_cmd, cmd, prefix_len);
            strcat(modified_cmd, DEFAULT_MACHINE);
            strcat(modified_cmd, first_space + 1);
            strcpy(cmd, modified_cmd);
        } else {
            strcat(cmd, " ");
            strcat(cmd, DEFAULT_MACHINE);
        }
    }
}

// modify -append param, add " " into -append param
void modify_append_arguments(char *cmd)
{
    char *append_pos = strstr(cmd, "-append");
    if (!append_pos) {
        return;
    }

    char *value_start = strchr(append_pos, ' ');
    if (!value_start || *++value_start == '"') {
        return;
    }

    char *current = value_start;
    char *next_flag = NULL;
    while (*current) {
        if (*current == '-' && (current == value_start || isspace(*(current - 1)))) {
            next_flag = current;
            break;
        }
        current++;
    }

    if (!next_flag) {
        next_flag = cmd + strlen(cmd);
    }

    size_t value_length = next_flag - value_start;
    char append_value[MAX_CMD_LENGTH/2] = {0};
    if (value_length >= sizeof(append_value)) {
        return; // value length is too long
    }
    (void)snprintf(append_value, sizeof(append_value), "%.*s", (int)value_length, value_start);

    while (value_length > 0 && isspace(append_value[value_length - 1])) {
        append_value[--value_length] = '\0';
    }

    char modified_cmd[MAX_CMD_LENGTH] = {0};
    size_t prefix_len = value_start - cmd;
    (void)snprintf(modified_cmd, sizeof(modified_cmd), "%.*s\"%s\" %s",
             (int)prefix_len, cmd, append_value, next_flag);
    (void)snprintf(cmd, MAX_CMD_LENGTH, "%s", modified_cmd);
}

void match_remove_target_flags(char **current, int *flag_found)
{
    for (int i = 0; i < removable_flag_count; i++) {
        size_t flag_len = strlen(removable_flags[i].flag);
        if (strncmp(*current, removable_flags[i].flag, flag_len) == 0 && isspace((*current)[flag_len])) {
            *flag_found = 1;
            *current += flag_len;
            skip_spaces(current);
            if (removable_flags[i].has_value) {
                skip_no_spaces(current);
                skip_spaces(current);
            }
            break;
        }
    }
}

// delete aimed flags and its value
void remove_flags_from_command(char *cmd)
{
    char modified_cmd[MAX_CMD_LENGTH] = {0};
    char *current = cmd;
    while (*current) {
        int flag_found = 0;
        match_remove_target_flags(&current, &flag_found);

        if (!flag_found) {
            char *next = current;
            skip_no_spaces(&next);
            strncat(modified_cmd, current, next - current);
            strcat(modified_cmd, " ");
            current = next;
            skip_spaces(&current);
        }
    }

    (void)snprintf(cmd, MAX_CMD_LENGTH, "%s", modified_cmd);
}

void remove_netdev_option(char *device_start)
{
    char *netdev_pos = strstr(device_start, ",netdev=");
    // delete the netdev= and the param following it
    if (netdev_pos) {
        *netdev_pos = '\0';
    }
}

void match_remove_target_devices(char *device_value, char *device_start, size_t device_len, int *dev_found)
{
    strncpy(device_value, device_start, device_len);
    device_value[device_len] = '\0';
    for (int i = 0; i < removable_device_count; i++) {
        if (strstr(device_value, removable_devices[i].device_name)) {
            *dev_found = 1;
            break;
        }
    }
}

// delete aimed device param
void remove_specific_devices(char *cmd, RemovedDevices *removed_devices)
{
    char modified_cmd[MAX_CMD_LENGTH] = {0};
    char *current = cmd;
    const char *device_param = "-device";
    size_t device_lens = strlen(device_param);

    while (*current) {
        int device_found = 0;
        if (strncmp(current, device_param, device_lens) == 0 && isspace(current[device_lens])) {
            char *next = current + device_lens;
            skip_spaces(&next);

            char device_value[MAX_OPTION_LENGTH] = {0};
            char *device_start = next;
            skip_no_spaces(&next);
            size_t device_length = next - device_start;

            if (device_length < sizeof(device_value)) {
                match_remove_target_devices(device_value, device_start, device_length, &device_found);
            }

            if (device_found) {
                current = next;
                skip_spaces(&current);
                continue;
            }

            // delete netdev= and its value, the param afte netdev= is not needed for dtb generation
            char *netdev_pos = strstr(device_value, ",netdev=");
            if (netdev_pos) {
                *netdev_pos = '\0';
            }

            // modified cmd into the modified_cmd
            strncat(modified_cmd, "-device ", sizeof(modified_cmd) - strlen(modified_cmd) - 1);
            strncat(modified_cmd, device_value, sizeof(modified_cmd) - strlen(modified_cmd) - 1);
            strcat(modified_cmd, " ");

            current = next;
            skip_spaces(&current);
            continue;
        }

        char *next = current;
        skip_no_spaces(&next);
        strncat(modified_cmd, current, next - current);
        strcat(modified_cmd, " ");
        current = next;
        skip_spaces(&current);
    }
    (void)snprintf(cmd, MAX_CMD_LENGTH, "%s", modified_cmd);
}

// change the path of chardev and monitor to /tmp/  it should consider the appendtbility of this function,
// e.g. add another param whose path= should be changed
void modify_socket_path(char *cmd)
{
    char modified_cmd[MAX_CMD_LENGTH] = {0};
    char *current = cmd;
    const char *chardev_param = "-chardev";
    size_t chardev_lens = strlen(chardev_param);

    while (*current) {
        int chardev_flag = 0;
        int monitor_flag = 0;
        if ((strncmp(current, chardev_param, chardev_lens) == 0 ||
             strncmp(current, "-monitor", chardev_lens) == 0) &&
             isspace(current[chardev_lens])) {
            if (strncmp(current, chardev_param, chardev_lens) == 0) {
                chardev_flag = 1;
            } else {
                monitor_flag = 1;
            }
            char *next = current + chardev_lens;
            skip_spaces(&next);

            char socket_value[MAX_OPTION_LENGTH] = {0};
            char *param_start = next;
            skip_no_spaces(&next);
            size_t param_length = next - param_start;

            strncpy(socket_value, param_start, param_length);
            socket_value[param_length] = '\0';

            char *path_start = strstr(socket_value, "path=") + strlen("path=");
            char *path_end = strchr(path_start, ',');
            char original_path[MAX_OPTION_LENGTH] = {0};

            if (path_end) {
                strncpy(original_path, path_start, path_end - path_start);
                original_path[path_end - path_start] = '\0';
            } else {
                strncpy(original_path, path_start, sizeof(original_path) - 1);
            }

            char *filename = strrchr(original_path, '/');
            filename = filename ? filename + 1 : original_path;

            char new_socket_value[MAX_OPTION_LENGTH] = {0};
            strncpy(new_socket_value, socket_value, path_start - socket_value);
            (void)snprintf(new_socket_value + (path_start - socket_value),
                           sizeof(new_socket_value) - (path_start - socket_value),
                           "/tmp/%s", filename);

            if (path_end) {
                strncat(new_socket_value, path_end, sizeof(new_socket_value) - strlen(new_socket_value) - 1);
            }
            // if there are not the two flags, the cmd will be invalid
            if (!strstr(new_socket_value, "server=on")) {
                strncat(new_socket_value, ",server=on", sizeof(new_socket_value) - strlen(new_socket_value) - 1);
            }
            if (!strstr(new_socket_value, "wait=off")) {
                strncat(new_socket_value, ",wait=off", sizeof(new_socket_value) - strlen(new_socket_value) - 1);
            }
            if (chardev_flag) {
                strncat(modified_cmd, "-chardev ", sizeof(modified_cmd) - strlen(modified_cmd) - 1);
            } else {
                strncat(modified_cmd, "-monitor ", sizeof(modified_cmd) - strlen(modified_cmd) - 1);
            }
            strncat(modified_cmd, new_socket_value, sizeof(modified_cmd) - strlen(modified_cmd) - 1);
            strncat(modified_cmd, " ", sizeof(modified_cmd) - strlen(modified_cmd) - 1);

            current = next;
            skip_spaces(&current);
            continue;
        }

        char *next = current;
        skip_no_spaces(&next);
        strncat(modified_cmd, current, next - current);
        strcat(modified_cmd, " ");
        current = next;
        skip_spaces(&current);
    }
    (void)snprintf(cmd, MAX_CMD_LENGTH, "%s", modified_cmd);
}

void modify_fs_path(char *cmd, const char *initramfs_path)
{
    char modified_cmd[MAX_CMD_LENGTH] = {0};

    // Find the start of the -drive option
    const char *drive_param = "-drive";
    size_t drive_param_len = strlen(drive_param);
    char *drive_start = strstr(cmd, drive_param);
    if (!drive_start) {
        return;
    }
    // Move past "-drive" and any spaces
    char *drive_params = drive_start + drive_param_len;
    skip_spaces(&drive_params);

    // Find the end of the -drive parameters (next option or end of string)
    char *drive_end = drive_params;
    while (*drive_end && *drive_end != ' ' && *drive_end != '\0') {
        drive_end++;
    }

    // Temporarily null-terminate the -drive parameters for easier parsing
    char temp = *drive_end;
    *drive_end = '\0';

    // Find the "file=" parameter within the -drive parameters
    const char *file_param = "file=";
    size_t file_param_lens = strlen(file_param);
    char *file_path_start = strstr(drive_params, file_param);
    if (!file_path_start) {
        *drive_end = temp;
        return;
    }

    // Move to the start of the file path
    file_path_start += file_param_lens;
    // Find the end of the file path (comma, space, or end of string)
    char *file_path_end = file_path_start;
    while (*file_path_end && *file_path_end != ',' && *file_path_end != ' ' && *file_path_end != '\0') {
        file_path_end++;
    }

    // Calculate the lengths of the parts of the command and ensure the modified command will fit in the buffer
    size_t prefix_len = file_path_start - cmd;
    size_t suffix_len = strlen(drive_end);
    size_t new_cmd_len = prefix_len + strlen(initramfs_path) + suffix_len;
    if (new_cmd_len >= sizeof(modified_cmd)) {
        *drive_end = temp;
        return;
    }

    (void)snprintf(modified_cmd, sizeof(modified_cmd), "%.*s%s%s",
             (int)prefix_len, cmd, initramfs_path, file_path_end);
    *drive_end = temp;
    // Append the rest of the command (after the -drive option)
    if (*drive_end) {
        strncat(modified_cmd, drive_end, sizeof(modified_cmd) - strlen(modified_cmd) - 1);
    }

    // Replace the original command with the modified one
    (void)snprintf(cmd, MAX_CMD_LENGTH, "%s", modified_cmd);
}

void modify_kernel_path(char *cmd, const char *kernel_path)
{
    // find the pos of -kernel
    const char *kernel_keyword = "-kernel";
    const char *kernel_pos = strstr(cmd, kernel_keyword);
    if (kernel_pos == NULL) {
        return;
    }

    // the path of kernel region in string
    const char *kernel_path_start = kernel_pos + strlen(kernel_keyword);
    while (*kernel_path_start == ' ') {
        kernel_path_start++;
    }
    const char *kernel_path_end = kernel_path_start;
    while (*kernel_path_end != ' ' && *kernel_path_end != '\0') {
        kernel_path_end++;
    }

    // cal the length of stitched string
    size_t kernel_prefix_len = kernel_path_start - cmd;
    size_t kernel_suffix_len = strlen(kernel_path_end);
    size_t kernel_new_len = kernel_prefix_len + strlen(kernel_path) + kernel_suffix_len;

    char *kernel_new_cmd = (char *)malloc(kernel_new_len + 1);
    if (kernel_new_cmd == NULL) {
        return;
    }
    (void)snprintf(kernel_new_cmd, kernel_new_len + 1, "%.*s%s%s",
                   (int)kernel_prefix_len, cmd, kernel_path, kernel_path_end);
    (void)snprintf(cmd, kernel_new_len + 1, "%s", kernel_new_cmd);
    free(kernel_new_cmd);
}

int execute_command(const char *command, const char *qemu_bin_path, const char *log_path)
{
    char cmd[MAX_CMD_LENGTH + 16];
    printf("Executing QEMU Command: %s %s\n", qemu_bin_path, command);
    (void)snprintf(cmd, sizeof(cmd), "%s %s  > %s 2>&1", qemu_bin_path, command, log_path);
    int ret = system(cmd);
    if (ret == -1) {
        perror("Failed to execute command");
        return -1;
    }
    return WEXITSTATUS(ret);
}

void generate_dtb_with_kata_config(char *qemu_bin_path, char *cmd)
{
    char *command = (char *)malloc(MAX_CMD_LENGTH * sizeof(char));
    char *log_path = DUMPDTB_LOG_PATH;
    int generate_dtb = 0;

    if (command == NULL) {
        return;
    }
    (void)snprintf(command, MAX_CMD_LENGTH, "%s", cmd);

    RemovedDevices removed_devices = {.count = 0};

    printf("Executing logic based on user's configuration....\n");

    #if LOG_PRINT
    printf("The original qemu instr is :%s\n", command);
    #endif
    modify_machine_param(command, DEFAULT_DUMPDTB_PATH);
    #if LOG_PRINT
    printf("After adding or modifying dtb generation path, the qemu instr is :%s\n", command);
    #endif
    modify_append_arguments(command);
    #if LOG_PRINT
    printf("After modifying append arguments (add\"), the qemu instr is :%s\n", command);
    #endif
    remove_flags_from_command(command);
    #if LOG_PRINT
    printf("After modifying the specific flags which are not relevant to dtb, the qemu instr is :%s\n", command);
    #endif
    remove_specific_devices(command, &removed_devices);
    #if LOG_PRINT
    printf("After modifying the specific devices which are not relevant to dtb, the qemu instr is :%s\n", command);
    #endif
    modify_socket_path(command);
    #if LOG_PRINT
    printf("After modifying the socket path of (-chardev and -monitor) \
           which are not relevant to dtb, the qemu instr is :%s\n", command);
    #endif

    generate_dtb = execute_command(command, qemu_bin_path, log_path);
    if (generate_dtb != 0) {
        fprintf(stderr, "QEMU command execution failed with code: %d\n", generate_dtb);
        return;
    }

    free(command);
    command = NULL;
    printf("DTB is Updated: %s\n", DEFAULT_DUMPDTB_PATH);
}