#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from typing import List
import os
import subprocess
import time
import threading
import signal

import virtcca_deploy.common.hardware as hardware
import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants

g_logger = config.g_logger

def timeout(seconds: int):
    def decorator(func):
        def _handle_timeout(signum, frame):
            raise Exception("Function call timed out")
        
        def wrapper(*args, **kwargs):
            # 
            signal.signal(signal.SIGALRM, _handle_timeout)
            signal.alarm(seconds)  # 
            try:
                return func(*args, **kwargs)
            finally:
                signal.alarm(0)  # 
        return wrapper
    return decorator

class UtilService:

    @staticmethod
    def get_node_info():
        hardware_info = hardware.get_hardware_info()
        virtcca_info = hardware.get_virtcca_info()
        numa_info = hardware.get_numa_cpu_topology()

        secure_memory = 0
        secure_memory_free = 0
        secure_numa_topology = {}
        if virtcca_info:
            for node_id, info in virtcca_info.items():
                size = info["size"]
                free = info["free"]

                secure_memory += size
                secure_memory_free += free

                secure_numa_topology[node_id] = {
                    "size": size,
                    "free": free
                }

        hardware_info["secure_memory"] = secure_memory
        hardware_info["secure_memory_free"] = secure_memory_free
        hardware_info["secure_numa_topology"] = secure_numa_topology

        return hardware_info

@timeout(60)
def qcow2_mount(qcow2_image_path):
    os.makedirs(constants.MOUNT_PATH, exist_ok=True)
    env = os.environ.copy()
    env["LIBGUESTFS_BACKEND"] = "direct"
    mount_cmd = [
        "guestmount", 
        "-a", qcow2_image_path, 
        "-i", constants.MOUNT_PATH, 
    ]
    try:
        subprocess.run(mount_cmd, check=True, env=env)
    except subprocess.CalledProcessError as e:
        g_logger.error("Error mounting file: %s", e)
        raise Exception("Failed to mount qcow2 image.")

def qcow2_unmount():
    unmount_cmd = ["guestunmount",  constants.MOUNT_PATH]
    try:
        subprocess.run(unmount_cmd, check=True)
    except subprocess.CalledProcessError as e:
        g_logger.error("Error unmounting file: %s", e)
        raise Exception("Failed to unmount qcow2 image.")