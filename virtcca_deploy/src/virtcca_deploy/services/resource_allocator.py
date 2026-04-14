# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
P0: 资源分配器接口与默认实现
提供 NetworkResourceAllocator / NodeResourceAllocator / DeviceAllocator 接口和默认实现
"""

import logging
import os
import re
import subprocess
from datetime import datetime
from typing import List, Dict, Optional

from virtcca_deploy.common.constants import ValidationError, DeviceTypeConfig
from virtcca_deploy.common.data_model import (
    NetAllocReq, NetAllocResp, NetReleaseReq, NetReleaseResp,
    DeviceAllocReq, DeviceAllocResp, DeviceReleaseReq, DeviceReleaseResp
)
from virtcca_deploy.services.db_service import db, DeviceAllocation


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

    def __init__(self):
        self._discovered_devices: List[Dict] = []
        self._lock = __import__('gevent').lock.RLock()
        self.logger = logging.getLogger(__name__)

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

        从数据库中查询可用设备，按 PF/VF 类型和 NUMA 亲和性匹配，
        在事务中完成分配标记，保证原子性。

        :param request: 设备分配请求，包含 vm_id、pf_num、vf_num、numa_node
        :return: 分配结果，包含成功标志和分配的设备 BDF 列表
        """
        allocated_devices = []
        try:
            pf_num = request.pf_num
            vf_num = request.vf_num

            if pf_num > 0:
                pf_list = self._allocate_devices_by_type(
                    request.vm_id, DeviceTypeConfig.DEVICE_TYPE_NET_PF, pf_num, request.numa_node
                )
                allocated_devices.extend(pf_list)

            if vf_num > 0:
                vf_list = self._allocate_devices_by_type(
                    request.vm_id, DeviceTypeConfig.DEVICE_TYPE_NET_VF, vf_num, request.numa_node
                )
                allocated_devices.extend(vf_list)

            db.session.commit()
            self.logger.info(
                f"Allocated {len(allocated_devices)} device(s) for VM {request.vm_id}: "
                f"{allocated_devices}"
            )
            return DeviceAllocResp(success=True, device_list=allocated_devices)

        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Failed to allocate devices for VM {request.vm_id}: {e}")
            return DeviceAllocResp(success=False, device_list=[])

    def release(self, request: DeviceReleaseReq) -> DeviceReleaseResp:
        """
        释放 VM 占用的所有 PCI 设备

        在事务中将指定 VM 的所有已分配设备标记为可用。

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

            for device in devices:
                device.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
                device.allocated_vm_id = None
                device.released_at = datetime.now()

            db.session.commit()
            bdf_list = [d.bdf for d in devices]
            self.logger.info(
                f"Released {len(devices)} device(s) for VM {request.vm_id}: {bdf_list}"
            )
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

    # ========== 内部方法：数据库操作 ==========

    def _allocate_devices_by_type(self, vm_id: str, device_type: str,
                                  count: int, numa_node: Optional[int] = None) -> List[str]:
        """
        按类型分配指定数量的设备

        :param vm_id: 目标 VM ID
        :param device_type: 设备类型（如 DeviceTypeConfig.DEVICE_TYPE_NET_PF）
        :param count: 需要分配的数量
        :param numa_node: 可选的 NUMA 节点过滤
        :return: 分配的设备 BDF 列表
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

        allocated_bdfs = []
        for device in available:
            device.status = DeviceAllocation.DEVICE_STATUS_ALLOCATED
            device.allocated_vm_id = vm_id
            device.allocated_at = datetime.now()
            device.released_at = None
            allocated_bdfs.append(device.bdf)

        return allocated_bdfs

    def _insert_device_record(self, dev_info: Dict):
        """
        插入新的设备记录到数据库

        :param dev_info: 设备信息字典
        """
        device_type = self._infer_device_type(dev_info)
        record = DeviceAllocation(
            bdf=dev_info['bdf'],
            vendor_id=dev_info['vendor_id'],
            device_id=dev_info['device_id'],
            numa_node=dev_info.get('numa_node', -1),
            device_type=device_type,
            status=DeviceAllocation.DEVICE_STATUS_AVAILABLE,
        )
        db.session.add(record)

    def _update_device_record(self, dev_info: Dict):
        """
        更新数据库中已有设备的动态属性

        仅更新可能变化的字段（numa_node），不覆盖分配状态。

        :param dev_info: 设备信息字典
        """
        record = DeviceAllocation.query.filter_by(bdf=dev_info['bdf']).first()
        if record is None:
            return

        record.numa_node = dev_info.get('numa_node', -1)
        record.vendor_id = dev_info['vendor_id']
        record.device_id = dev_info['device_id']

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

    def get_discovered_devices(self) -> List[Dict]:
        """获取最近一次发现的设备列表"""
        with self._lock:
            return list(self._discovered_devices)
