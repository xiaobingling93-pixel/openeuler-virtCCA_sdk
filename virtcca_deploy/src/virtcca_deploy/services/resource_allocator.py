# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
P0: 资源分配器接口与默认实现
提供 NetworkResourceAllocator / NodeResourceAllocator / DeviceAllocator 接口和默认实现
"""

import logging
import os
import re
import subprocess
import traceback
from datetime import datetime
from typing import List, Dict, Optional

from virtcca_deploy.common.constants import ValidationError, DeviceTypeConfig
from virtcca_deploy.common.data_model import (
    NetAllocReq, NetAllocResp, NetReleaseReq, NetReleaseResp,
    DeviceAllocReq, DeviceAllocResp, DeviceReleaseReq, DeviceReleaseResp,
    SriovVfSetupResp
)
from virtcca_deploy.services.db_service import db, DeviceAllocation
from virtcca_deploy.services.dao import get_dao_registry


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


class DeviceAllocator:
    """
    PCI设备资源分配器接口
    Compute 层使用，负责 PF/VF 网卡分配
    """

    def find_device(self, vendor_id: int, device_id: int, **kwargs) -> List[Dict]:
        """
        根据 VENDOR_ID 和 DEVICE_ID 精确查找 PCI 设备

        :param vendor_id: 厂商 ID（十六进制整数，如 0x19e5）
        :param device_id: 设备 ID（十六进制整数，如 0x1822）
        :param kwargs: 扩展过滤条件（如 class_id、bdf 等）
        :return: 匹配的设备信息列表
        """
        raise NotImplementedError

    def allocate(self, request: DeviceAllocReq) -> DeviceAllocResp:
        raise NotImplementedError

    def release(self, request: DeviceReleaseReq) -> DeviceReleaseResp:
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


class IpAllocator(NetworkResourceAllocator):
    """
    基于数据库的 IP 分配器
    Manager 层使用，为 VM 分配 IP 地址
    从数据库读取网络配置，根据节点和网络接口信息分配 IP
    """

    def __init__(self):
        """
        :raises ValidationError: 配置文件无效时
        """
        from virtcca_deploy.services.network_config_service import (
            get_network_config_service
        )

        self._lock = __import__('gevent').lock.RLock()
        self.logger = logging.getLogger(__name__)
        self._network_config_service = get_network_config_service()

    def allocate(self, request: NetAllocReq) -> NetAllocResp:
        """
        基于数据库配置为 VM 分配网络接口和 IP 地址

        从数据库读取状态为"unused"的网络配置，
        根据 node_name 精确匹配可用的网络interface配置，
        根据 pf_num 参数验证匹配到的interface数量是否满足需求。

        :param request: 网络分配请求，包含 vm_id_list、pf_num、node_ip
        :return: 分配结果，包含 vm_iface_map、failed_vms
        """
        vm_iface_map = {}
        failed_vms = {}

        with self._lock:
            from virtcca_deploy.services.db_service import ComputeNode

            node = ComputeNode.query.filter_by(ip=request.node_ip).first()

            if not node:
                self.logger.warning(
                    f"Node {request.node_ip} not found in database"
                )
                for vm_id in request.vm_id_list:
                    failed_vms[vm_id] = f"Node {request.node_ip} not found"
                return NetAllocResp(
                    success=False,
                    vm_iface_map=vm_iface_map,
                    failed_vms=failed_vms,
                    message=f"Node {request.node_ip} not found in database"
                )

            node_name = node.nodename

            if request.pf_num <= 0:
                self.logger.error(
                    f"Invalid pf_num: {request.pf_num}, must be > 0"
                )
                for vm_id in request.vm_id_list:
                    failed_vms[vm_id] = f"Invalid pf_num: {request.pf_num}"
                return NetAllocResp(
                    success=False,
                    vm_iface_map=vm_iface_map,
                    failed_vms=failed_vms,
                    message=f"pf_num must be greater than 0"
                )

            try:
                success, vm_ip_map, vm_iface_map, error_msg = (
                    self._network_config_service.allocate_ips_for_deployment(
                        node_name=node_name,
                        pf_num=request.pf_num,
                        vm_id_list=request.vm_id_list
                    )
                )
            except Exception as alloc_error:
                self.logger.error(
                    f"Unexpected error during allocation: {alloc_error}"
                )
                for vm_id in request.vm_id_list:
                    failed_vms[vm_id] = f"IP allocation error: {str(alloc_error)}"
                return NetAllocResp(
                    success=False,
                    vm_iface_map=vm_iface_map,
                    failed_vms=failed_vms,
                    message=f"IP allocation failed: {str(alloc_error)}"
                )

            if not success:
                self.logger.error(f"IP allocation failed: {error_msg}")
                for vm_id in request.vm_id_list:
                    if vm_id not in failed_vms:
                        failed_vms[vm_id] = error_msg
                return NetAllocResp(
                    success=False,
                    vm_iface_map=vm_iface_map,
                    failed_vms=failed_vms,
                    message=error_msg
                )

            for vm_id in request.vm_id_list:
                self.logger.info(
                    f"Allocated {request.pf_num} interface(s) to VM {vm_id} "
                    f"on node {node_name}"
                )

        return NetAllocResp(
            success=True,
            vm_iface_map=vm_iface_map,
            failed_vms=failed_vms,
            message=None
        )

    def release(self, request: NetReleaseReq) -> NetReleaseResp:
        """
        释放 VM 占用的 IP 地址

        支持部分释放成功：某些 VM 释放成功，某些失败。
        对于每个 VM，如果其 iface_list 解析失败，立即跳过该 VM 并记录错误。

        :param request: 网络释放请求，包含 vm_id_list
        :return: 释放结果，包含 released_vms、failed_vms
        """
        released_vms = []
        failed_vms = {}

        with self._lock:
            try:
                success, error_msg = self._network_config_service.release_ips_for_vms(
                    vm_id_list=request.vm_id_list
                )

                if success:
                    released_vms = request.vm_id_list
                    self.logger.info(
                        f"Released IPs for {len(released_vms)} VM(s)"
                    )
                else:
                    for vm_id in request.vm_id_list:
                        failed_vms[vm_id] = error_msg
                    self.logger.error(f"Failed to release IPs: {error_msg}")

            except Exception as release_error:
                self.logger.error(
                    f"Unexpected error during release: {release_error}"
                )
                for vm_id in request.vm_id_list:
                    failed_vms[vm_id] = f"IP release error: {str(release_error)}"

        return NetReleaseResp(
            success=len(failed_vms) == 0,
            released_vms=released_vms,
            failed_vms=failed_vms
        )


class DeviceManagerAllocator(DeviceAllocator):
    """
    基于 SQLite 持久化的设备分配器
    Compute 层使用，负责 PF/VF 网卡分配

    设备发现通过 lspci + sysfs 实现，分配状态通过 SQLAlchemy ORM
    持久化到 SQLite 数据库，保证原子性和进程重启后的状态恢复。
    """

    HUAWEI_VENDOR_ID = DeviceTypeConfig.HUAWEI_VENDOR_ID
    HI1822_DEVICE_IDS = DeviceTypeConfig.HI1822_DEVICE_IDS

    PCI_VENDOR_ID_MAX = DeviceTypeConfig.PCI_VENDOR_ID_MAX
    PCI_DEVICE_ID_MAX = DeviceTypeConfig.PCI_DEVICE_ID_MAX

    SYSFS_PCI_DEVICES = DeviceTypeConfig.SYSFS_PCI_DEVICES
    SYSFS_NET_CLASS = "/sys/class/net"
    SRIOV_NUMVFS_SUFFIX = "device/sriov_numvfs"
    SRIOV_TOTALVFS_SUFFIX = "device/sriov_totalvfs"

    def __init__(self):
        self._discovered_devices: List[Dict] = []
        self._lock = __import__('gevent').lock.RLock()
        self.logger = logging.getLogger(__name__)
        self._dao = get_dao_registry().device_allocation_dao

    # ========== 设备发现 ==========

    def find_device(self, vendor_id: int, device_id: int, **kwargs) -> List[Dict]:
        """
        根据 VENDOR_ID 和 DEVICE_ID 精确查找本地 PCI 设备

        通过 lspci 命令枚举系统所有 PCI 设备，使用 vendor_id 和 device_id
        进行精确匹配，返回包含 BDF 标识符的设备信息列表。
        支持通过 kwargs 传入额外的过滤条件以实现可扩展查找。

        :param vendor_id: 厂商 ID（十六进制整数，如 0x19e5），必填
        :param device_id: 设备 ID（十六进制整数，如 0x1822），必填
        :param kwargs: 扩展过滤条件，当前支持：
            - class_id (int): PCI 类别 ID 过滤
            - bdf (str): BDF 地址精确匹配
            - numa_node (int): NUMA 节点过滤
            - refresh (bool): 是否强制重新扫描，默认 False（优先使用缓存）
        :return: 匹配的设备信息列表，每项包含 bdf、vendor_id、device_id、numa_node
        :raises ValidationError: 当 vendor_id 或 device_id 参数无效时
        """
        self._validate_pci_ids(vendor_id, device_id)

        class_id = kwargs.get('class_id')
        target_bdf = kwargs.get('bdf')
        numa_node = kwargs.get('numa_node')
        refresh = kwargs.get('refresh', False)

        with self._lock:
            if not refresh and self._discovered_devices:
                cached = self._search_cached_devices(
                    vendor_id, device_id, class_id, target_bdf, numa_node
                )
                if cached:
                    self.logger.info(f"Found {len(cached)} device(s) from cache "
                                    f"[vendor=0x{vendor_id:04x}, device=0x{device_id:04x}]")
                    return cached

            all_devices = self._enumerate_pci_devices()
            if all_devices is None:
                return []

            matched_devices = self._match_devices(
                all_devices, vendor_id, device_id, class_id, target_bdf, numa_node
            )
            self._update_discovered_cache(all_devices)
            self.logger.info(f"Found {len(matched_devices)} device(s) "
                            f"[vendor=0x{vendor_id:04x}, device=0x{device_id:04x}]")
            return matched_devices

    def discover_hi1822_devices(self, vendor_id: Optional[int] = None,
                                device_ids: Optional[List[int]] = None) -> List[Dict]:
        """
        发现本地 Hi1822 系列 PCI 设备并获取其 BDF

        内部复用 find_device 方法，对 Hi1822 系列的每个 device_id
        分别执行精确查找并合并结果。

        :param vendor_id: 厂商 ID，默认为华为 0x19e5
        :param device_ids: 设备 ID 列表，默认为 Hi1822 系列 {0x1822}
        :return: 设备信息列表，每项包含 bdf、vendor_id、device_id
        """
        target_vendor = vendor_id if vendor_id is not None else self.HUAWEI_VENDOR_ID
        target_device_ids = device_ids if device_ids is not None else list(self.HI1822_DEVICE_IDS)

        all_matched = []
        for did in target_device_ids:
            try:
                results = self.find_device(target_vendor, did)
                all_matched.extend(results)
            except ValidationError as e:
                self.logger.error(f"Failed to find device [vendor=0x{target_vendor:04x}, "
                                 f"device=0x{did:04x}]: {e}")
                continue

        with self._lock:
            self._discovered_devices = all_matched

        self.logger.info(f"Discovered {len(all_matched)} Hi1822 device(s) in total")
        return all_matched

    # ========== 设备分配（数据库持久化） ==========

    def allocate(self, request: DeviceAllocReq) -> DeviceAllocResp:
        """
        为 VM 分配 PCI 设备

        支持两种分配模式：
        1. MAC 地址分配：当 request.iface 非空时，根据 MAC 地址列表分配设备
           - 从 iface 中提取 MAC 地址
           - 根据 MAC 地址查找对应设备
           - 返回 {MAC: BDF} 字典结构
        2. 传统分配：当 request.iface 为空时，按 PF/VF 数量分配
           - 从数据库中查询可用设备
           - 按 PF/VF 类型和 NUMA 亲和性匹配
           - 返回 BDF 列表（保持向后兼容）

        :param request: 设备分配请求，包含 vm_id、pf_num、vf_num、iface、numa_node
        :return: 分配结果，包含成功标志和分配的设备列表
        """
        try:
            if request.is_mac_based_allocation():
                return self._allocate_by_mac(request)
            else:
                return self._allocate_by_count(request)
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Failed to allocate devices for VM {request.vm_id}: {e}")
            return DeviceAllocResp(success=False, device_dict={})

    def _allocate_by_mac(self, request: DeviceAllocReq) -> DeviceAllocResp:
        """
        根据 MAC 地址列表分配设备

        通过 DAO 层执行批量分配操作，确保：
        1. 所有数据库操作通过 DAO 层抽象进行
        2. 检索所有可用设备
        3. 在更新前立即验证设备状态（防止并发竞争）
        4. 执行批量更新操作
        5. 完整的错误处理和事务管理

        :param request: 包含 MAC 地址的分配请求
        :return: 分配结果，device_dict 为 {MAC: BDF} 字典
        """
        mac_addresses = request.get_mac_addresses()

        try:
            allocated_devices = self._dao.allocate_devices_by_mac(
                mac_addresses=mac_addresses,
                vm_id=request.vm_id
            )

            if allocated_devices:
                return DeviceAllocResp(success=True, device_dict=allocated_devices)
            else:
                self.logger.warning(
                    f"No devices allocated for VM {request.vm_id} "
                    f"(all devices unavailable or excluded)"
                )
                return DeviceAllocResp(success=False, device_dict={})

        except Exception as e:
            self.logger.error(
                f"MAC-based allocation failed for VM {request.vm_id}: {e}"
            )
            return DeviceAllocResp(success=False, device_dict={})

    def _allocate_by_count(self, request: DeviceAllocReq) -> DeviceAllocResp:
        """
        按 PF/VF 数量分配设备（传统模式）

        :param request: 包含 pf_num、vf_num 的分配请求
        :return: 分配结果，device_dict 为 {MAC: BDF} 字典
        """
        allocated_devices = {}
        try:
            pf_num = request.pf_num
            vf_num = request.vf_num

            if pf_num > 0:
                pf_dict = self._allocate_devices_by_type(
                    request.vm_id, DeviceTypeConfig.DEVICE_TYPE_NET_PF, pf_num, request.numa_node
                )
                allocated_devices.update(pf_dict)

            if vf_num > 0:
                vf_dict = self._allocate_devices_by_type(
                    request.vm_id, DeviceTypeConfig.DEVICE_TYPE_NET_VF, vf_num, request.numa_node
                )
                allocated_devices.update(vf_dict)

            db.session.commit()
            self.logger.info(
                f"Allocated {len(allocated_devices)} device(s) for VM {request.vm_id}: "
                f"{allocated_devices}"
            )
            return DeviceAllocResp(success=True, device_dict=allocated_devices)

        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Failed to allocate devices for VM {request.vm_id}: {e}")
            return DeviceAllocResp(success=False, device_dict={})

    def release(self, request: DeviceReleaseReq) -> DeviceReleaseResp:
        """
        释放 VM 占用的所有 PCI 设备

        在事务中将指定 VM 的所有已分配设备标记为可用。
        释放 VF 后，检查对应 PF 下是否还有已分配的 VF，
        若全部释放则自动销毁 VF 并恢复 PF 为 available 状态。

        :param request: 设备释放请求，包含 vm_id
        :return: 释放结果
        """
        try:
            devices = DeviceAllocation.query.filter_by(
                allocated_vm_id=request.vm_id,
                status=DeviceAllocation.DEVICE_STATUS_ALLOCATED
            ).all()

            if not devices:
                self.logger.info(f"No allocated devices found for VM {request.vm_id}")
                return DeviceReleaseResp(success=True)

            released_vf_bdfs = []
            for device in devices:
                if device.device_type == DeviceTypeConfig.DEVICE_TYPE_NET_VF:
                    released_vf_bdfs.append(device.bdf)
                device.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
                device.allocated_vm_id = None
                device.released_at = datetime.now()

            db.session.commit()
            bdf_list = [d.bdf for d in devices]
            self.logger.info(
                f"Released {len(devices)} device(s) for VM {request.vm_id}: {bdf_list}"
            )

            if released_vf_bdfs:
                self._try_reclaim_sriov_pf(released_vf_bdfs)

            return DeviceReleaseResp(success=True)

        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Failed to release devices for VM {request.vm_id}: {e}")
            return DeviceReleaseResp(success=False)

    # ========== 数据库 CRUD 操作 ==========

    def sync_discovered_to_db(self, discovered_devices: Optional[List[Dict]] = None):
        """
        将发现的设备信息同步到数据库

        对比 lspci 发现的设备列表与数据库已有记录，执行增量同步：
        - 新发现的设备：插入数据库
        - 已不存在的设备：标记为不可用（不删除，保留审计记录）
        - 已存在的设备：更新 NUMA 等动态属性

        :param discovered_devices: 设备信息列表，为 None 时使用缓存
        """
        devices = discovered_devices if discovered_devices is not None else self._discovered_devices
        if not devices:
            self.logger.warning("No discovered devices to sync")
            return

        try:
            existing_bdfs = {
                row.bdf for row in DeviceAllocation.query.with_entities(DeviceAllocation.bdf).all()
            }

            current_bdfs = set()
            for dev_info in devices:
                current_bdfs.add(dev_info['bdf'])
                if dev_info['bdf'] in existing_bdfs:
                    self._update_device_record(dev_info)
                else:
                    self._insert_device_record(dev_info)

            for bdf in existing_bdfs - current_bdfs:
                self.logger.warning(f"Device {bdf} no longer present in system")

            db.session.commit()
            self.logger.info(
                f"Synced {len(current_bdfs)} device(s) to database "
                f"(new: {len(current_bdfs - existing_bdfs)}, "
                f"updated: {len(current_bdfs & existing_bdfs)})"
            )

        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Failed to sync devices to database: {e}")

    def get_available_devices(self, device_type: str,
                              numa_node: Optional[int] = None) -> List[Dict]:
        """
        查询数据库中可用的设备列表

        :param device_type: 设备类型（如 DeviceTypeConfig.DEVICE_TYPE_NET_PF）
        :param numa_node: 可选的 NUMA 节点过滤
        :return: 可用设备信息字典列表
        """
        query = DeviceAllocation.query.filter_by(
            device_type=device_type,
            status=DeviceAllocation.DEVICE_STATUS_AVAILABLE
        )
        if numa_node is not None:
            query = query.filter_by(numa_node=numa_node)

        return [device.to_dict() for device in query.all()]

    def get_allocated_devices(self, vm_id: Optional[str] = None) -> List[Dict]:
        """
        查询已分配的设备列表

        :param vm_id: 可选的 VM ID 过滤，为 None 时返回所有已分配设备
        :return: 已分配设备信息字典列表
        """
        query = DeviceAllocation.query.filter_by(
            status=DeviceAllocation.DEVICE_STATUS_ALLOCATED
        )
        if vm_id is not None:
            query = query.filter_by(allocated_vm_id=vm_id)

        return [device.to_dict() for device in query.all()]

    def get_all_devices(self) -> List[Dict]:
        """
        查询数据库中所有设备记录

        :return: 所有设备信息字典列表
        """
        return [device.to_dict() for device in DeviceAllocation.query.all()]

    def find_device_by_mac(self, mac_address: str) -> Optional[DeviceAllocation]:
        """
        根据 MAC 地址查找设备分配记录

        :param mac_address: MAC 地址（如 "00:11:22:33:44:55"）
        :return: DeviceAllocation 记录；未找到返回 None
        """
        return self._dao.get_by_mac_address(mac_address)

    # ========== 内部方法：数据库操作 ==========

    def _allocate_devices_by_type(self, vm_id: str, device_type: str,
                                  count: int, numa_node: Optional[int] = None) -> Dict[str, str]:
        """
        按类型分配指定数量的设备

        :param vm_id: 目标 VM ID
        :param device_type: 设备类型（如 DeviceTypeConfig.DEVICE_TYPE_NET_PF）
        :param count: 需要分配的数量
        :param numa_node: 可选的 NUMA 节点过滤
        :return: {MAC: BDF} 字典
        :raises RuntimeError: 可用设备不足时
        """
        query = DeviceAllocation.query.filter_by(
            device_type=device_type,
            status=DeviceAllocation.DEVICE_STATUS_AVAILABLE
        )
        if numa_node is not None:
            query = query.filter_by(numa_node=numa_node)

        available = query.with_for_update().limit(count).all()

        if len(available) < count:
            raise RuntimeError(
                f"Not enough {device_type} devices. "
                f"Need {count}, available: {len(available)}"
                f"{f' on NUMA node {numa_node}' if numa_node is not None else ''}"
            )

        allocated_dict = {}
        for device in available:
            device.status = DeviceAllocation.DEVICE_STATUS_ALLOCATED
            device.allocated_vm_id = vm_id
            device.allocated_at = datetime.now()
            device.released_at = None
            mac_addr = device.mac_address if device.mac_address else f"unknown_{device.bdf}"
            allocated_dict[mac_addr] = device.bdf

        return allocated_dict

    def _insert_device_record(self, dev_info: Dict):
        """
        插入新的设备记录到数据库

        :param dev_info: 设备信息字典
        """
        device_type = self._infer_device_type(dev_info)
        initial_status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
        if device_type == DeviceTypeConfig.DEVICE_TYPE_NET_PF:
            if self._has_vf_under_pf(dev_info['bdf']):
                initial_status = DeviceAllocation.DEVICE_STATUS_SRIOV_USED
                self.logger.info(
                    f"PF {dev_info['bdf']} has VF(s) in database, "
                    f"setting initial status to sriov_used"
                )
        record = DeviceAllocation(
            bdf=dev_info['bdf'],
            vendor_id=dev_info['vendor_id'],
            device_id=dev_info['device_id'],
            numa_node=dev_info.get('numa_node', -1),
            device_type=device_type,
            device_name=dev_info.get('device_name'),
            mac_address=dev_info.get('mac_address'),
            status=initial_status,
        )
        db.session.add(record)

    def _update_device_record(self, dev_info: Dict):
        """
        更新数据库中已有设备的动态属性

        仅更新可能变化的字段（numa_node），不覆盖分配状态。
        但对于 PF 设备，若其下已有 VF 记录，需确保状态为 sriov_used。

        :param dev_info: 设备信息字典
        """
        record = DeviceAllocation.query.filter_by(bdf=dev_info['bdf']).first()
        if record is None:
            return

        record.numa_node = dev_info.get('numa_node', -1)
        record.vendor_id = dev_info['vendor_id']
        record.device_id = dev_info['device_id']
        record.device_name = dev_info.get('device_name')
        record.mac_address = dev_info.get('mac_address')

        if (record.device_type == DeviceTypeConfig.DEVICE_TYPE_NET_PF
                and record.status == DeviceAllocation.DEVICE_STATUS_AVAILABLE):
            if self._has_vf_under_pf(record.bdf):
                record.status = DeviceAllocation.DEVICE_STATUS_SRIOV_USED
                self.logger.info(
                    f"PF {record.bdf} has VF(s) in database, "
                    f"correcting status from available to sriov_used"
                )

    @staticmethod
    def _infer_device_type(dev_info: Dict) -> str:
        """
        根据 vendor_id 和 device_id 推断设备类型

        VENDOR_ID=0x19e5, DEVICE_ID=0x1822 → NET_PF
        VENDOR_ID=0x19e5, DEVICE_ID=0x375e → NET_VF

        :param dev_info: 设备信息字典
        :return: 设备类型字符串
        """
        vendor_id = dev_info.get('vendor_id')
        device_id = dev_info.get('device_id')
        if vendor_id == DeviceTypeConfig.HUAWEI_VENDOR_ID:
            if device_id == DeviceTypeConfig.HI1822_PF_DEVICE_ID:
                return DeviceTypeConfig.DEVICE_TYPE_NET_PF
            if device_id == DeviceTypeConfig.HI1822_VF_DEVICE_ID:
                return DeviceTypeConfig.DEVICE_TYPE_NET_VF
        return DeviceTypeConfig.DEVICE_TYPE_PCI

    # ========== 内部方法：设备发现 ==========

    def _validate_pci_ids(self, vendor_id: int, device_id: int):
        """
        验证 VENDOR_ID 和 DEVICE_ID 参数的有效性

        :param vendor_id: 厂商 ID
        :param device_id: 设备 ID
        :raises ValidationError: 参数类型或范围不合法时抛出
        """
        if not isinstance(vendor_id, int):
            raise ValidationError(f"vendor_id must be int, got {type(vendor_id).__name__}")
        if not isinstance(device_id, int):
            raise ValidationError(f"device_id must be int, got {type(device_id).__name__}")

        if vendor_id < 0 or vendor_id > self.PCI_VENDOR_ID_MAX:
            raise ValidationError(
                f"vendor_id out of range [0x0000, 0x{self.PCI_VENDOR_ID_MAX:04x}], "
                f"got 0x{vendor_id:04x}"
            )
        if device_id < 0 or device_id > self.PCI_DEVICE_ID_MAX:
            raise ValidationError(
                f"device_id out of range [0x0000, 0x{self.PCI_DEVICE_ID_MAX:04x}], "
                f"got 0x{device_id:04x}"
            )

    def _search_cached_devices(self, vendor_id: int, device_id: int,
                               class_id: Optional[int] = None,
                               target_bdf: Optional[str] = None,
                               numa_node: Optional[int] = None) -> List[Dict]:
        """
        从已发现的设备缓存中搜索匹配设备

        :param vendor_id: 厂商 ID
        :param device_id: 设备 ID
        :param class_id: 可选的 PCI 类别 ID 过滤
        :param target_bdf: 可选的 BDF 精确匹配
        :param numa_node: 可选的 NUMA 节点过滤
        :return: 匹配的设备信息列表
        """
        results = []
        for dev_info in self._discovered_devices:
            if dev_info.get('vendor_id') != vendor_id:
                continue
            if dev_info.get('device_id') != device_id:
                continue
            if class_id is not None and dev_info.get('class_id') != class_id:
                continue
            if target_bdf is not None and dev_info.get('bdf') != target_bdf:
                continue
            if numa_node is not None and dev_info.get('numa_node') != numa_node:
                continue
            results.append(dev_info)
        return results

    def _enumerate_pci_devices(self) -> Optional[List[Dict]]:
        """
        通过 lspci 命令枚举系统所有 PCI 设备

        执行 lspci -D -n 命令获取设备列表，解析输出为标准字典格式。
        -D 参数显示完整域地址，-n 参数以数字形式显示 vendor/device ID。

        :return: 设备信息字典列表；失败返回 None
        """
        try:
            result = subprocess.run(
                ['lspci', '-D', '-n'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                self.logger.error(f"lspci command failed: {result.stderr}")
                return None
        except FileNotFoundError:
            self.logger.error("lspci command not found, unable to enumerate PCI devices")
            return None
        except subprocess.TimeoutExpired:
            self.logger.error("lspci command timed out")
            return None
        except Exception as e:
            self.logger.error(f"Failed to run lspci: {e}")
            return None

        bdf_pattern = re.compile(
            r'^([0-9a-fA-F:.]+)\s+[0-9a-fA-F]{4}:\s*([0-9a-fA-F]{4}):([0-9a-fA-F]{4})'
        )
        devices = []
        for line in result.stdout.splitlines():
            match = bdf_pattern.match(line.strip())
            if not match:
                continue

            device_id = int(match.group(3), 16)
            bdf = match.group(1)
            devices.append({
                "bdf": bdf,
                "vendor_id": int(match.group(2), 16),
                "device_id": device_id,
                "numa_node": self._read_numa_node(bdf),
                "device_name": self._read_device_name(bdf),
                "mac_address": self._read_mac_address(bdf),
            })

        self.logger.info(f"Enumerated {len(devices)} PCI device(s) via lspci")
        return devices

    def _match_devices(self, all_devices: List[Dict], vendor_id: int, device_id: int,
                       class_id: Optional[int] = None,
                       target_bdf: Optional[str] = None,
                       numa_node: Optional[int] = None) -> List[Dict]:
        """
        从设备列表中精确匹配目标设备

        :param all_devices: 设备信息字典列表（来自 _enumerate_pci_devices）
        :param vendor_id: 目标厂商 ID
        :param device_id: 目标设备 ID
        :param class_id: 可选的 PCI 类别 ID 过滤
        :param target_bdf: 可选的 BDF 精确匹配
        :param numa_node: 可选的 NUMA 节点过滤
        :return: 匹配的设备信息列表
        """
        matched_devices = []
        for dev_info in all_devices:
            if dev_info.get('vendor_id') != vendor_id or dev_info.get('device_id') != device_id:
                continue
            if class_id is not None and dev_info.get('class_id') != class_id:
                continue
            if target_bdf is not None and dev_info.get('bdf') != target_bdf:
                continue
            if numa_node is not None and dev_info.get('numa_node') != numa_node:
                continue

            matched_devices.append(dev_info)
            self.logger.info(
                f"Matched device: BDF={dev_info['bdf']}, "
                f"vendor=0x{dev_info['vendor_id']:04x}, "
                f"device=0x{dev_info['device_id']:04x}, "
            )

        return matched_devices

    def _update_discovered_cache(self, new_devices: List[Dict]):
        """
        更新已发现设备的缓存，合并新设备（按 BDF 去重）

        :param new_devices: 新发现的设备列表
        """
        existing_bdfs = {dev['bdf'] for dev in self._discovered_devices}
        for dev in new_devices:
            if dev['bdf'] not in existing_bdfs:
                self._discovered_devices.append(dev)
                existing_bdfs.add(dev['bdf'])

    def _read_numa_node(self, bdf: str) -> int:
        """
        从 sysfs 读取 PCI 设备的 NUMA 节点

        读取 /sys/bus/pci/devices/{BDF}/numa_node 文件。
        Linux 内核中 numa_node 的含义：
            - >= 0 : 设备所属的 NUMA 节点编号
            - -1   : 内核未为该设备分配 NUMA 亲和性（无 NUMA 或未绑定）

        :param bdf: PCI 设备的 BDF 地址（如 "0000:3b:00.0"）
        :return: NUMA 节点编号；读取失败返回 -1
        """
        numa_path = os.path.join(self.SYSFS_PCI_DEVICES, bdf, "numa_node")
        try:
            with open(numa_path, 'r') as f:
                return int(f.read().strip())
        except FileNotFoundError:
            self.logger.debug(f"numa_node sysfs entry not found for {bdf}")
        except ValueError:
            self.logger.warning(f"Invalid numa_node value for {bdf}")
        except OSError as e:
            self.logger.warning(f"Failed to read numa_node for {bdf}: {e}")
        return -1

    def _read_device_name(self, bdf: str) -> Optional[str]:
        """
        从 sysfs 读取 PCI 设备的接口名称

        对于网络设备，/sys/bus/pci/devices/{BDF}/net/ 目录下包含
        网络接口名称（如 enp59s0）。对于非网络设备，该目录不存在。

        :param bdf: PCI 设备的 BDF 地址（如 "0000:3b:00.0"）
        :return: 设备接口名称；非网络设备或读取失败返回 None
        """
        net_dir = os.path.join(self.SYSFS_PCI_DEVICES, bdf, "net")
        try:
            if os.path.isdir(net_dir):
                entries = os.listdir(net_dir)
                if entries:
                    return entries[0]
        except OSError as e:
            self.logger.warning(f"Failed to read device name for {bdf}: {e}")
        return None

    def _read_mac_address(self, bdf: str) -> Optional[str]:
        """
        从 sysfs 读取 PCI 网络设备的 MAC 地址

        对于网络设备，读取 /sys/bus/pci/devices/{BDF}/net/{iface}/address 文件
        获取 MAC 地址。对于非网络设备，该目录不存在。

        :param bdf: PCI 设备的 BDF 地址（如 "0000:3b:00.0"）
        :return: MAC 地址（如 "00:11:22:33:44:55"）；非网络设备或读取失败返回 None
        """
        net_dir = os.path.join(self.SYSFS_PCI_DEVICES, bdf, "net")
        try:
            if os.path.isdir(net_dir):
                entries = os.listdir(net_dir)
                if entries:
                    iface = entries[0]
                    mac_path = os.path.join(net_dir, iface, "address")
                    with open(mac_path, 'r') as f:
                        mac = f.read().strip()
                        if mac and mac != "00:00:00:00:00:00":
                            return mac
        except FileNotFoundError:
            self.logger.debug(f"MAC address sysfs entry not found for {bdf}")
        except OSError as e:
            self.logger.warning(f"Failed to read MAC address for {bdf}: {e}")
        return None

    # ========== SR-IOV VF 设置 ==========

    def setup_sriov_vf(self, net_device_name: str, vf_num: int) -> SriovVfSetupResp:
        """
        为 PF 网络设备设置 SR-IOV 虚拟功能数量

        通过写入 /sys/class/net/${net_device_name}/device/sriov_numvfs
        将 PF 设备使能指定数量的 VF。设置成功后，该 PF 设备在数据库中
        会被标记为 sriov_used 状态，不再作为 PF 设备分配。

        :param net_device_name: 网络接口名称（如 "enp59s0"）
        :param vf_num: 要创建的 VF 数量（非负整数）
        :return: SriovVfSetupResp 包含操作结果
        """
        self.logger.info(f"Setting up SR-IOV VF: net_device={net_device_name}, vf_num={vf_num}")

        validation_error = self._validate_sriov_prerequisites(net_device_name, vf_num)
        if validation_error is not None:
            return validation_error

        sriov_numvfs_path = os.path.join(
            self.SYSFS_NET_CLASS, net_device_name, self.SRIOV_NUMVFS_SUFFIX
        )

        try:
            with open(sriov_numvfs_path, 'w') as f:
                f.write(str(vf_num))
            self.logger.info(
                f"Wrote vf_num={vf_num} to {sriov_numvfs_path}"
            )
        except PermissionError:
            msg = f"Permission denied writing to {sriov_numvfs_path}"
            self.logger.error(msg)
            return SriovVfSetupResp(
                success=False, device_name=net_device_name, vf_num=vf_num, message=msg
            )
        except OSError as e:
            msg = f"Failed to write sriov_numvfs for {net_device_name}: {e}"
            self.logger.error(msg)
            return SriovVfSetupResp(
                success=False, device_name=net_device_name, vf_num=vf_num, message=msg
            )

        verify_result = self._verify_sriov_numvfs(net_device_name, vf_num)
        if not verify_result:
            msg = (
                f"SR-IOV VF count verification failed for {net_device_name}: "
                f"expected {vf_num}"
            )
            self.logger.error(msg)
            return SriovVfSetupResp(
                success=False, device_name=net_device_name, vf_num=vf_num, message=msg
            )

        self._update_pf_status_after_sriov(net_device_name)

        self.logger.info(
            f"SR-IOV VF setup succeeded: {net_device_name} now has {vf_num} VF(s)"
        )
        return SriovVfSetupResp(
            success=True, device_name=net_device_name, vf_num=vf_num
        )

    def _validate_sriov_prerequisites(self, net_device_name: str,
                                       vf_num: int) -> Optional[SriovVfSetupResp]:
        """
        验证 SR-IOV VF 设置的前置条件

        :param net_device_name: 网络接口名称
        :param vf_num: 要创建的 VF 数量
        :return: 验证失败时返回 SriovVfSetupResp，成功返回 None
        """
        if not isinstance(vf_num, int) or vf_num < 0:
            msg = f"Invalid vf_num: {vf_num}, must be a non-negative integer"
            self.logger.error(msg)
            return SriovVfSetupResp(
                success=False, device_name=net_device_name, vf_num=vf_num, message=msg
            )

        net_device_path = os.path.join(self.SYSFS_NET_CLASS, net_device_name)
        if not os.path.isdir(net_device_path):
            msg = f"Network device {net_device_name} does not exist at {net_device_path}"
            self.logger.error(msg)
            return SriovVfSetupResp(
                success=False, device_name=net_device_name, vf_num=vf_num, message=msg
            )

        sriov_numvfs_path = os.path.join(
            self.SYSFS_NET_CLASS, net_device_name, self.SRIOV_NUMVFS_SUFFIX
        )
        if not os.path.exists(sriov_numvfs_path):
            msg = f"Device {net_device_name} does not support SR-IOV (sriov_numvfs not found)"
            self.logger.error(msg)
            return SriovVfSetupResp(
                success=False, device_name=net_device_name, vf_num=vf_num, message=msg
            )

        pf_record = self._find_pf_record_by_net_device(net_device_name)
        if pf_record is None:
            msg = (
                f"Device {net_device_name} is not registered as a PF device in database, "
                f"or has already been used for SR-IOV"
            )
            self.logger.error(msg)
            return SriovVfSetupResp(
                success=False, device_name=net_device_name, vf_num=vf_num, message=msg
            )

        if pf_record.status == DeviceAllocation.DEVICE_STATUS_ALLOCATED:
            msg = (
                f"PF device {net_device_name} (BDF={pf_record.bdf}) is currently "
                f"allocated to VM {pf_record.allocated_vm_id}, cannot create new VFs"
            )
            self.logger.error(msg)
            return SriovVfSetupResp(
                success=False, device_name=net_device_name, vf_num=vf_num, message=msg
            )

        allocated_vf = self._find_allocated_vf_under_pf(pf_record.bdf)
        if allocated_vf is not None:
            msg = (
                f"PF device {net_device_name} (BDF={pf_record.bdf}) has allocated VF "
                f"(BDF={allocated_vf.bdf}, VM={allocated_vf.allocated_vm_id}), "
                f"cannot modify sriov_numvfs as it would affect in-use VFs"
            )
            self.logger.error(msg)
            return SriovVfSetupResp(
                success=False, device_name=net_device_name, vf_num=vf_num, message=msg
            )

        sriov_totalvfs_path = os.path.join(
            self.SYSFS_NET_CLASS, net_device_name, self.SRIOV_TOTALVFS_SUFFIX
        )
        if os.path.exists(sriov_totalvfs_path):
            try:
                with open(sriov_totalvfs_path, 'r') as f:
                    max_vfs = int(f.read().strip())
                if vf_num > max_vfs:
                    msg = (
                        f"Requested vf_num={vf_num} exceeds maximum supported "
                        f"VF count {max_vfs} for {net_device_name}"
                    )
                    self.logger.error(msg)
                    return SriovVfSetupResp(
                        success=False, device_name=net_device_name,
                        vf_num=vf_num, message=msg
                    )
            except (ValueError, OSError) as e:
                self.logger.warning(
                    f"Failed to read sriov_totalvfs for {net_device_name}: {e}, "
                    f"skipping max VF check"
                )

        return None

    def _verify_sriov_numvfs(self, net_device_name: str, expected_vf_num: int) -> bool:
        """
        验证 sriov_numvfs 文件的实际值是否与预期一致

        :param net_device_name: 网络接口名称
        :param expected_vf_num: 预期的 VF 数量
        :return: 验证是否通过
        """
        sriov_numvfs_path = os.path.join(
            self.SYSFS_NET_CLASS, net_device_name, self.SRIOV_NUMVFS_SUFFIX
        )
        try:
            with open(sriov_numvfs_path, 'r') as f:
                actual_vf_num = int(f.read().strip())
            if actual_vf_num != expected_vf_num:
                self.logger.error(
                    f"SR-IOV VF count mismatch for {net_device_name}: "
                    f"expected={expected_vf_num}, actual={actual_vf_num}"
                )
                return False
            self.logger.info(
                f"SR-IOV VF count verified for {net_device_name}: {actual_vf_num}"
            )
            return True
        except (ValueError, OSError) as e:
            self.logger.error(
                f"Failed to read sriov_numvfs for verification on {net_device_name}: {e}"
            )
            return False

    def _find_pf_record_by_net_device(self, net_device_name: str) -> Optional[DeviceAllocation]:
        """
        根据网络接口名称在数据库中查找对应的 PF 设备记录

        通过 device_name 字段直接查询数据库，匹配 device_type=NET_PF
        且 status 为 available 或 allocated 的记录。

        :param net_device_name: 网络接口名称
        :return: DeviceAllocation 记录；未找到返回 None
        """
        record = DeviceAllocation.query.filter(
            DeviceAllocation.device_name == net_device_name,
            DeviceAllocation.device_type == DeviceTypeConfig.DEVICE_TYPE_NET_PF,
            DeviceAllocation.status.in_([
                DeviceAllocation.DEVICE_STATUS_AVAILABLE,
                DeviceAllocation.DEVICE_STATUS_ALLOCATED,
            ]),
        ).first()

        return record

    def _find_allocated_vf_under_pf(self, pf_bdf: str) -> Optional[DeviceAllocation]:
        """
        查找指定 PF 设备下已被 VM 占用的 VF 设备

        VF 的 BDF 与 PF 的 BDF 共享相同的域和总线前缀，
        例如 PF=0000:3b:00.0 的 VF 为 0000:3b:00.{1,2,...} 或
        0000:3b:0x.{0,...}（取决于 SR-IOV 实现）。
        通过匹配 BDF 前缀（域:总线:）来查找同 PF 下的 VF。

        :param pf_bdf: PF 设备的 BDF 地址（如 "0000:3b:00.0"）
        :return: 已分配的 VF DeviceAllocation 记录；无则返回 None
        """
        bdf_prefix = pf_bdf.rsplit(":", 1)[0] + ":"
        allocated_vfs = DeviceAllocation.query.filter(
            DeviceAllocation.device_type == DeviceTypeConfig.DEVICE_TYPE_NET_VF,
            DeviceAllocation.status == DeviceAllocation.DEVICE_STATUS_ALLOCATED,
            DeviceAllocation.bdf.startswith(bdf_prefix),
        ).all()

        return allocated_vfs[0] if allocated_vfs else None

    def _has_vf_under_pf(self, pf_bdf: str) -> bool:
        """
        检查指定 PF 设备下是否存在 VF 记录

        通过匹配 BDF 前缀（域:总线:）来查找同 PF 下的 VF，
        不区分 VF 的分配状态（available/allocated/sriov_used 均计入）。

        :param pf_bdf: PF 设备的 BDF 地址（如 "0000:3b:00.0"）
        :return: 存在 VF 记录返回 True，否则返回 False
        """
        bdf_prefix = pf_bdf.rsplit(":", 1)[0] + ":"
        vf_count = DeviceAllocation.query.filter(
            DeviceAllocation.device_type == DeviceTypeConfig.DEVICE_TYPE_NET_VF,
            DeviceAllocation.bdf.startswith(bdf_prefix),
        ).count()
        return vf_count > 0

    def _try_reclaim_sriov_pf(self, released_vf_bdfs: List[str]):
        """
        释放 VF 后尝试回收 SR-IOV PF 资源

        对每个被释放的 VF，根据其 BDF 前缀找到对应的 sriov_used PF，
        检查该 PF 下是否还有已分配的 VF。若全部释放，则：
        1. echo 0 到 sriov_numvfs 销毁所有 VF
        2. 将 PF 状态从 sriov_used 恢复为 available
        3. 从数据库中删除已销毁的 VF 记录

        :param released_vf_bdfs: 本次释放的 VF 的 BDF 列表
        """
        checked_pf_bdfs = set()
        for vf_bdf in released_vf_bdfs:
            bdf_prefix = vf_bdf.rsplit(":", 1)[0] + ":"

            pf_record = DeviceAllocation.query.filter(
                DeviceAllocation.device_type == DeviceTypeConfig.DEVICE_TYPE_NET_PF,
                DeviceAllocation.status == DeviceAllocation.DEVICE_STATUS_SRIOV_USED,
                DeviceAllocation.bdf.startswith(bdf_prefix),
            ).first()

            if pf_record is None or pf_record.bdf in checked_pf_bdfs:
                continue
            checked_pf_bdfs.add(pf_record.bdf)

            remaining_allocated = self._find_allocated_vf_under_pf(pf_record.bdf)
            if remaining_allocated is not None:
                self.logger.info(
                    f"PF {pf_record.bdf} still has allocated VF(s), "
                    f"skipping VF destroy"
                )
                continue

            self.logger.info(
                f"All VFs under PF {pf_record.bdf} are free, "
                f"destroying VFs and restoring PF"
            )
            self._destroy_vfs_and_restore_pf(pf_record)

    def _destroy_vfs_and_restore_pf(self, pf_record: DeviceAllocation):
        """
        销毁 PF 下的所有 VF 并恢复 PF 为 available 状态

        :param pf_record: PF 设备的数据库记录（status=sriov_used）
        """
        net_device_name = pf_record.device_name
        if not net_device_name:
            self.logger.warning(
                f"PF {pf_record.bdf} has no device_name, cannot destroy VFs"
            )
            return

        sriov_numvfs_path = os.path.join(
            self.SYSFS_NET_CLASS, net_device_name, self.SRIOV_NUMVFS_SUFFIX
        )

        try:
            with open(sriov_numvfs_path, 'w') as f:
                f.write("0")
            self.logger.info(
                f"Wrote vf_num=0 to {sriov_numvfs_path} to destroy VFs"
            )
        except PermissionError:
            self.logger.error(
                f"Permission denied writing to {sriov_numvfs_path}, "
                f"cannot destroy VFs for PF {pf_record.bdf}"
            )
            return
        except OSError as e:
            self.logger.error(
                f"Failed to write sriov_numvfs for {net_device_name}: {e}, "
                f"cannot destroy VFs for PF {pf_record.bdf}"
            )
            return

        if not self._verify_sriov_numvfs(net_device_name, 0):
            self.logger.error(
                f"VF destroy verification failed for {net_device_name}, "
                f"PF {pf_record.bdf} will not be restored"
            )
            return

        self._restore_pf_after_vf_destroy(pf_record)

    def _restore_pf_after_vf_destroy(self, pf_record: DeviceAllocation):
        """
        VF 销毁后恢复 PF 状态为 available，并清理数据库中的 VF 记录

        :param pf_record: PF 设备的数据库记录
        """
        bdf_prefix = pf_record.bdf.rsplit(":", 1)[0] + ":"

        try:
            vf_records = DeviceAllocation.query.filter(
                DeviceAllocation.device_type == DeviceTypeConfig.DEVICE_TYPE_NET_VF,
                DeviceAllocation.bdf.startswith(bdf_prefix),
            ).all()

            for vf in vf_records:
                db.session.delete(vf)

            pf_record.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
            db.session.commit()

            self.logger.info(
                f"Restored PF {pf_record.bdf} to available, "
                f"deleted {len(vf_records)} VF record(s)"
            )
        except Exception as e:
            db.session.rollback()
            self.logger.error(
                f"Failed to restore PF {pf_record.bdf} after VF destroy: {e}"
            )

    def _update_pf_status_after_sriov(self, net_device_name: str):
        """
        SR-IOV VF 设置成功后，更新数据库中 PF 设备的状态

        将 PF 设备状态标记为 sriov_used，并记录其网络接口名称，
        确保该设备不再作为 PF 设备分配。

        :param net_device_name: 网络接口名称
        """
        record = self._find_pf_record_by_net_device(net_device_name)
        if record is None:
            self.logger.warning(
                f"PF record for {net_device_name} not found during status update"
            )
            return

        record.status = DeviceAllocation.DEVICE_STATUS_SRIOV_USED
        record.device_name = net_device_name
        try:
            db.session.commit()
            self.logger.info(
                f"Updated PF device {record.bdf} status to sriov_used "
                f"(net_device={net_device_name})"
            )
        except Exception as e:
            db.session.rollback()
            self.logger.error(
                f"Failed to update PF status for {net_device_name}: {e}"
            )

    def get_discovered_devices(self) -> List[Dict]:
        """获取最近一次发现的设备列表"""
        with self._lock:
            return list(self._discovered_devices)
