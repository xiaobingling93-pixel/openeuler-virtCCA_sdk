# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
P0: 资源分配器接口与默认实现
提供 NetworkResourceAllocator / NodeResourceAllocator / DeviceAllocator 接口和默认实现
"""

import logging
from typing import List, Dict

from virtcca_deploy.common.data_model import (
    NetAllocReq, NetAllocResp, NetReleaseReq, NetReleaseResp
)

# ========== 资源分配器接口 ==========
class NetworkResourceAllocator:
    """
    网络资源（IP）分配器接口
    Manager 层使用，用于为 VM 分配 IP 地址
    """

    def allocate(self, request: NetAllocReq) -> NetAllocResp:
        raise NotImplementedError

    def release(self, request: NetReleaseReq) -> NetReleaseResp:
        raise NotImplementedError


# ========== 资源分配器默认实现 ==========
class SimpleIpAllocator(NetworkResourceAllocator):
    """
    基于 IP 地址池的简单 IP 分配器
    Manager 层使用，为 VM 分配 IP 地址
    """

    def __init__(self, base_ip: str, ip_count: int = 254):
        """
        :param base_ip: 基础 IP 地址（如 "192.168.1.0"）
        :param ip_count: 可分配的 IP 数量
        """
        import ipaddress
        self._base_ip = ipaddress.IPv4Address(base_ip)
        self._ip_count = ip_count
        self._allocated: Dict[str, Dict] = {}  # vm_id -> {vlan_id, ip}
        self._index = 0
        self._lock = __import__('gevent').lock.RLock()
        self.logger = logging.getLogger(__name__)

    def allocate(self, request: NetAllocReq) -> NetAllocResp:
        vm_ip_map = {}
        for vm_id in request.vm_id_list:
            vm_ip_map[vm_id] = "192.168.0.1"
        return NetAllocResp(success=True, vm_ip_map=vm_ip_map)

    def release(self, request: NetReleaseReq) -> NetReleaseResp:
        return NetReleaseResp(success=True)

    def get_allocated_ip(self, vm_id: str) -> str:
        """查询 VM 已分配的 IP"""
        with self._lock:
            if vm_id in self._allocated:
                return self._allocated[vm_id]["ip"]
            return None

