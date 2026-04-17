#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import os
import subprocess
from typing import Dict, Any, Tuple, List

from gevent import Timeout

import virtcca_deploy.common.hardware as hardware
import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants

g_logger = config.g_logger

MAX_PAGE_SIZE = 100

def timeout(seconds: int):
    def decorator(func):
        def wrapper(*args, **kwargs):
            with Timeout(seconds, exception=Exception(f"Function call timed out after {seconds}s")):
                return func(*args, **kwargs)
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

        pf_num_total, pf_num_free = UtilService._get_hi1822_device_stats()
        hardware_info["pf_num_total"] = pf_num_total
        hardware_info["pf_num_free"] = pf_num_free

        hardware_info["disks"] = UtilService._get_disk_info_by_df()
        hardware_info["os"] = UtilService._get_os_info()

        return hardware_info

    @staticmethod
    def _get_disk_info_by_df():
        disks = []
        try:
            result = subprocess.run(
                ["df", "-h", "--output=source,fstype,size,avail,target"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                g_logger.warning("df command failed: %s", result.stderr)
                return disks

            lines = result.stdout.strip().splitlines()
            for line in lines[1:]:
                parts = line.split()
                if len(parts) < 5:
                    continue
                device, fstype, size, avail, mount_point = parts[0], parts[1], parts[2], parts[3], parts[4]
                if not device.startswith("/dev/"):
                    continue
                disks.append({
                    "device": device,
                    "filesystem": fstype,
                    "total": size,
                    "available": avail,
                    "mount_point": mount_point
                })
        except FileNotFoundError:
            g_logger.warning("df command not found")
        except subprocess.TimeoutExpired:
            g_logger.warning("df command timed out")
        except Exception as e:
            g_logger.warning("Failed to get disk info via df: %s", e)
        return disks

    @staticmethod
    def _get_os_info():
        try:
            with open("/etc/os-release", "r") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.strip().split("=", 1)[1].strip('"')
        except FileNotFoundError:
            g_logger.warning("/etc/os-release not found")
        except Exception as e:
            g_logger.warning("Failed to read /etc/os-release: %s", e)
        return "Unknown"

    @staticmethod
    def _get_hi1822_device_stats():
        """
        统计 Hi1822 PF 设备总数和可用数

        优先从数据库查询已持久化的设备分配状态；
        若数据库不可用，则回退到 lspci 实时发现。

        :return: (pf_num_total, pf_num_free) 元组
        """
        try:
            from virtcca_deploy.services.db_service import DeviceAllocation
            total = DeviceAllocation.query.filter_by(
                device_type=constants.DeviceTypeConfig.DEVICE_TYPE_NET_PF
            ).count()
            free = DeviceAllocation.query.filter_by(
                device_type=constants.DeviceTypeConfig.DEVICE_TYPE_NET_PF,
                status=DeviceAllocation.DEVICE_STATUS_AVAILABLE
            ).count()
            return total, free
        except Exception:
            g_logger.debug("Database unavailable, falling back to lspci for device stats")

        try:
            from virtcca_deploy.services.resource_allocator import DeviceManagerAllocator
            allocator = DeviceManagerAllocator()
            discovered = allocator.discover_hi1822_devices()
            total = len(discovered)
            free = total
            return total, free
        except Exception as e:
            g_logger.warning("Failed to get Hi1822 device stats: %s", e)
            return 0, 0


def validate_and_extract_pagination(data: Dict[str, Any], 
                                  default_page: int = 1, 
                                  default_page_size: int = 10) -> Tuple[bool, str, int, int]:
    pagination = data.get('pagination', {})
    page = pagination.get('page', default_page)
    page_size = pagination.get('page_size', default_page_size)

    try:
        page = int(page)
        page_size = int(page_size)
    except (ValueError, TypeError):
        return False, "Pagination parameters must be integers.", default_page, default_page_size

    if page < 1:
        return False, "Page must be >= 1.", default_page, default_page_size

    if page_size < 1:
        return False, "Page size must be >= 1.", default_page, default_page_size

    if page_size > MAX_PAGE_SIZE:
        return False, f"Page size cannot exceed {MAX_PAGE_SIZE}.", default_page, default_page_size

    return True, "", page, page_size


def paginate_list(items: List[Any], page: int, page_size: int) -> Tuple[List[Any], int]:
    total = len(items)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    return items[start_idx:end_idx], total


def build_pagination_response(page: int, page_size: int, total: int) -> Dict[str, int]:
    return {
        "page": page,
        "page_size": page_size,
        "entry_num": total
    }

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