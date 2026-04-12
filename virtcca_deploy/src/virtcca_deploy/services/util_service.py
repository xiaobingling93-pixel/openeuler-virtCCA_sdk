#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import os
import subprocess
import signal
from typing import Dict, Any, Tuple

import virtcca_deploy.common.hardware as hardware
import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants

g_logger = config.g_logger

MAX_PAGE_SIZE = 100

def timeout(seconds: int):
    def decorator(func):
        def _handle_timeout(signum, frame):
            raise Exception("Function call timed out")
        
        def wrapper(*args, **kwargs):
            signal.signal(signal.SIGALRM, _handle_timeout)
            signal.alarm(seconds)
            try:
                return func(*args, **kwargs)
            finally:
                signal.alarm(0)
        return wrapper
    return decorator

class UtilService:

    @staticmethod
    def get_node_info():
        hardware_info = hardware.get_hardware_info()
        virtcca_info = hardware.get_virtcca_info()

        secure_memory = 0
        secure_memory_free = 0
        secure_numa_topology = []

        if virtcca_info:
            for node_id, info in virtcca_info.items():
                size = info["size"]
                free = info["free"]

                secure_memory += size
                secure_memory_free += free

                secure_numa_topology.append({
                    "numa_id": int(node_id),
                    "free": free,
                    "size": size
                })

        hardware_info["secure_memory"] = secure_memory
        hardware_info["secure_memory_free"] = secure_memory_free
        hardware_info["secure_numa_topology"] = secure_numa_topology

        return hardware_info


def validate_and_extract_pagination(data: Dict[str, Any], 
                                  default_page: int = 1, 
                                  default_page_size: int = 10) -> Tuple[bool, str, int, int]:
    """
    校验和提取分页参数
    
    Args:
        data: 请求的JSON数据
        default_page: 默认页码
        default_page_size: 默认每页大小
    
    Returns:
        Tuple: (是否成功, 错误消息, 页码, 每页大小)
        如果校验成功，返回 (True, "", page, page_size)
        如果校验失败，返回 (False, 错误消息, default_page, default_page_size)
    """
    pagination = data.get('pagination', {})
    page = pagination.get('page', default_page)
    page_size = pagination.get('page_size', default_page_size)

    if not isinstance(page, int) or not isinstance(page_size, int):
        return False, "Pagination parameters must be integers.", default_page, default_page_size

    if page <= 0 or page_size <= 0:
        return False, "Pagination parameters must be positive integers.", default_page, default_page_size

    if page_size > MAX_PAGE_SIZE:
        return False, f"Page size cannot exceed {MAX_PAGE_SIZE}.", default_page, default_page_size

    return True, "", page, page_size

@timeout(60)
def qcow2_mount(qcow2_image_path):
    os.makedirs(constants.MOUNT_PATH, exist_ok=True)
    mount_cmd = [
        "guestmount", 
        "-a", qcow2_image_path, 
        "-i", constants.MOUNT_PATH, 
    ]
    try:
        subprocess.run(mount_cmd, check=True)
    except subprocess.CalledProcessError as e:
        g_logger.error("Error mounting file: %s", e)
        raise Exception("Failed to mount qcow2 image.")

def qcow2_unmount():
    if not os.path.ismount(constants.MOUNT_PATH):
        g_logger.info("Directory %s is not mounted. No need to unmount.", constants.MOUNT_PATH)
        return
    unmount_cmd = ["guestunmount",  constants.MOUNT_PATH]
    try:
        subprocess.run(unmount_cmd, check=True)
    except subprocess.CalledProcessError as e:
        g_logger.error("Error unmounting file: %s", e)
        raise Exception("Failed to unmount qcow2 image.")