#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import re
import os
import platform

import psutil

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