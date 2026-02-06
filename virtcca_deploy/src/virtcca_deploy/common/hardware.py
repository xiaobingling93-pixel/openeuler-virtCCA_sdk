#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import re
import os
import platform

import psutil
import subprocess

import virtcca_deploy.common.config as config

g_logger = config.g_logger

VIRTCCA_MEMORY_FILE_PATH = "/sys/kernel/tmm/memory_info"


def get_hardware_info():
    memory_info = psutil.virtual_memory()
    memory_mb = int(memory_info.total / (1024 ** 2))
    available_memory_mb = int(memory_info.available / (1024 ** 2))

    info = {
        'hostname': platform.node(),
        'physical_cpu': psutil.cpu_count(logical=False),
        'logical_cpu': psutil.cpu_count(logical=True),
        'memory': memory_mb,
        'memory_free': available_memory_mb,
    }
    return info

def get_numa_cpu_topology():
        try:
            result = subprocess.run(['numactl', '-H'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output = result.stdout.decode('utf-8')
            numa_info = {}
            for line in output.splitlines():
                if "node" in line and "cpus" in line:
                    parts = line.split("cpus:")
                    node_info = parts[0].strip()
                    cpus = parts[1].strip().split()
                    node_id = int(node_info.split()[1])
                    numa_info[node_id] = [int(cpu) for cpu in cpus]
            return numa_info

        except FileNotFoundError:
            g_logger.error("Error: 'numactrl' command not found. Make sure it's installed and available in your PATH.")
        except Exception as e:
            g_logger.error(f"An error occurred: {e}")

def get_virtcca_info():
    if os.path.exists(VIRTCCA_MEMORY_FILE_PATH):
        with open(VIRTCCA_MEMORY_FILE_PATH, "r") as f:
            lines = f.readlines()
    else:
        g_logger.warning("%s not found, unable to get secure memory info!", VIRTCCA_MEMORY_FILE_PATH)
        return {}

    memory_info = {}

    node_info_pattern = re.compile(
        r"numa node (\d+) size:\s+(\d+)Mi\n"
        r"numa node \1 free:\s+(\d+)Mi\n"
        r"numa node \1 cvm used:\s+(\d+)Mi\n"
        r"numa node \1 meta_data used:\s+(\d+)Mi"
    )

    for match in node_info_pattern.finditer("".join(lines)):
        node_id = int(match.group(1))
        size = int(match.group(2))
        free = int(match.group(3))
        cvm_used = int(match.group(4))
        meta_data_used = int(match.group(5))
        memory_info[node_id] = {
            "size": size,
            "free": free,
            "cvm_used": cvm_used,
            "meta_data_used": meta_data_used
        }

    return memory_info