# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
Network configuration service for managing YAML-based network configs
Handles upload, validation, storage, and IP allocation from database
"""

import logging
import json
from typing import Dict, List, Tuple, Optional

from virtcca_deploy.common.constants import ValidationError
from virtcca_deploy.services.db_service import db, NetworkConfig
from virtcca_deploy.services.network_config_parser import (
    YamlNetworkConfigParser, NodeConfig
)
from virtcca_deploy.services.dao import get_dao_registry

logger = logging.getLogger(__name__)


class NetworkConfigService:
    """
    Service for managing network configurations
    Handles YAML upload validation, database storage, and IP allocation
    """

    def __init__(self):
        self._lock = __import__('gevent').lock.RLock()
        self._network_config_dao = get_dao_registry().network_config_dao

    def validate_and_store_yaml(self, yaml_file_path: str) -> Tuple[bool, str]:
        """
        Validate YAML file and store to database

        :param yaml_file_path: Path to YAML configuration file
        :return: (success, error_message)
        """
        with self._lock:
            try:
                if self._has_used_configs():
                    return False, "Failed to update network configuration: active network resources are in use"

                parser = YamlNetworkConfigParser()
                config_dict = parser.load_from_file(yaml_file_path)

                self._validate_yaml_completeness(config_dict)

                self._clear_all_configs()

                self._store_configs(config_dict)

                logger.info(
                    f"Network configuration stored successfully, "
                    f"{len(config_dict)} node(s)"
                )
                return True, ""

            except ValidationError as e:
                error_msg = f"Network configuration validation failed: {str(e)}"
                logger.error(error_msg)
                return False, error_msg
            except Exception as e:
                error_msg = f"Failed to store network configuration: {str(e)}"
                logger.error(error_msg)
                return False, error_msg

    def allocate_ips_for_deployment(
        self, node_name: str, pf_num: int, vm_id_list: List[str]
    ) -> Tuple[bool, Dict, Dict, str]:
        """
        Allocate IPs for VM deployment from database with VLAN ID grouping

        This method implements a VLAN-aware allocation strategy that ensures
        all VMs deployed on the same node receive network interfaces with
        identical VLAN ID sets. This is critical for maintaining consistent
        network topology across VMs in a deployment group.

        Allocation Strategy:
        1. Group available interfaces by VLAN ID
        2. Validate that each VLAN group has sufficient interfaces for all VMs
        3. Allocate interfaces ensuring each VM gets the same VLAN ID distribution
        4. Mark allocated interfaces as used in database with associated vm_id

        :param node_name: Target node name for interface allocation
        :param pf_num: Number of PF interfaces per VM (determines total interfaces needed)
        :param vm_id_list: List of VM IDs to allocate IPs for
        :return: Tuple of (success, vm_ip_map, vm_iface_map, error_message)
                 - success: Boolean indicating allocation success
                 - vm_ip_map: Dict mapping VM ID to list of allocated IP addresses
                 - vm_iface_map: Dict mapping VM ID to list of interface config dicts
                 - error_message: Error description if allocation failed, empty string otherwise
        """
        with self._lock:
            vm_ip_map = {}
            vm_iface_map = {}

            try:
                # 步骤 1：获取目标节点的所有未使用网络配置
                unused_configs = self._get_unused_configs_by_node(node_name)

                if not unused_configs:
                    return False, vm_ip_map, vm_iface_map, (
                        f"No network configuration found for node '{node_name}'"
                    )

                # 步骤 2：计算总接口需求
                total_required = len(vm_id_list) * pf_num

                if len(unused_configs) < total_required:
                    return False, vm_ip_map, vm_iface_map, (
                        f"Insufficient interfaces: required {total_required}, "
                        f"available {len(unused_configs)}"
                    )

                # 步骤 3：委托给 VLAN 感知分配逻辑
                success, vm_ip_map, vm_iface_map, vm_configs_map, error_msg = (
                    self._allocate_single_node_with_vlan_grouping(
                        unused_configs=unused_configs,
                        node_name=node_name,
                        pf_num=pf_num,
                        vm_id_list=vm_id_list
                    )
                )

                if not success:
                    return False, vm_ip_map, vm_iface_map, error_msg

                # 步骤 4：在数据库中将已分配的配置标记为已使用，并关联 vm_id
                for vm_id, configs in vm_configs_map.items():
                    self._mark_configs_as_used(configs, vm_id)

                total_allocated = sum(len(configs) for configs in vm_configs_map.values())
                logger.info(
                    f"Allocated {total_allocated} interface(s) for "
                    f"{len(vm_id_list)} VM(s) on node {node_name}"
                )
                return True, vm_ip_map, vm_iface_map, ""

            except ValidationError as e:
                error_msg = f"IP allocation validation failed: {str(e)}"
                logger.error(error_msg)
                return False, vm_ip_map, vm_iface_map, error_msg
            except Exception as e:
                db.session.rollback()
                error_msg = f"Failed to allocate IPs: {str(e)}"
                logger.error(error_msg)
                return False, vm_ip_map, vm_iface_map, error_msg

    def _group_configs_by_vlan(
        self, configs: List[NetworkConfig]
    ) -> Dict[int, List[NetworkConfig]]:
        """
        按 VLAN ID 分组网络配置

        此方法将可用的网络接口按 VLAN 分组，这是 VLAN 感知分配的基础。
        每个分组包含所有共享相同 VLAN ID 的接口。

        设计原理：
        - VLAN 分组支持在不同 VLAN 之间均衡分配
        - 确保每台虚拟机从相同的 VLAN ID 集合获得接口
        - 在虚拟机部署之间保持网络拓扑一致性

        :param configs: 需要分组的 NetworkConfig 对象列表
        :return: 映射 VLAN ID 到 NetworkConfig 对象列表的字典
                 示例：{100: [config1, config2], 200: [config3, config4]}
        """
        vlan_groups = {}

        for config in configs:
            vlan_id = config.vlan_id
            if vlan_id not in vlan_groups:
                vlan_groups[vlan_id] = []
            vlan_groups[vlan_id].append(config)

        logger.debug(
            f"Grouped {len(configs)} configs into {len(vlan_groups)} VLAN groups: "
            f"{ {vlan_id: len(cfgs) for vlan_id, cfgs in vlan_groups.items()} }"
        )

        return vlan_groups

    def _allocate_single_node_with_vlan_grouping(
        self,
        unused_configs: List[NetworkConfig],
        node_name: str,
        pf_num: int,
        vm_id_list: List[str]
    ) -> Tuple[bool, Dict, Dict, List[NetworkConfig], str]:
        """
        基于 VLAN ID 分组为单节点上的虚拟机分配网络接口

        核心分配策略：
        - 每台虚拟机分配 pf_num 个接口，每个接口来自不同的 VLAN ID
        - 所有虚拟机获得相同的 VLAN ID 集合，确保网络拓扑一致性
        - 如果可用 VLAN ID 数量少于 pf_num，则分配失败

        分配算法：
        1. 按 VLAN ID 分组可用接口
        2. 验证 VLAN ID 数量 >= pf_num（否则失败）
        3. 选择前 pf_num 个 VLAN ID（按 VLAN ID 排序）
        4. 验证每个选中的 VLAN 组有足够的接口（>= 虚拟机数量）
        5. 为每台虚拟机从每个 VLAN 组分配 1 个接口

        示例：
        - 2 台虚拟机，pf_num=2，VLAN 组：{100: [3 configs], 200: [3 configs], 300: [3 configs]}
        - 选择 VLAN ID：[100, 200]（前 2 个）
        - 每台虚拟机：从 VLAN 100 取 1 个接口，从 VLAN 200 取 1 个接口
        - 结果：两台虚拟机都有相同的 VLAN ID 集合 {100, 200}

        :param unused_configs: 可用于分配的 NetworkConfig 对象列表
        :param node_name: 目标节点名称（用于日志记录）
        :param pf_num: 每台虚拟机需要分配的 PF 接口数量
        :param vm_id_list: 需要分配接口的虚拟机 ID 列表
        :return: 元组 (success, vm_ip_map, vm_iface_map, vm_configs_map, error_message)
                 - vm_configs_map: Dict mapping VM ID to list of allocated NetworkConfig objects
        """
        num_vms = len(vm_id_list)
        vm_ip_map = {}
        vm_iface_map = {}
        vm_configs_map = {}

        # 步骤 1：按 VLAN ID 分组可用接口
        vlan_groups = self._group_configs_by_vlan(unused_configs)

        if not vlan_groups:
            return False, vm_ip_map, vm_iface_map, {}, (
                f"No valid VLAN groups found for node '{node_name}'"
            )

        # 步骤 2：验证 VLAN ID 数量是否满足要求
        # 每台虚拟机需要 pf_num 个不同 VLAN 的接口，因此至少需要 pf_num 个 VLAN ID
        vlan_ids = sorted(vlan_groups.keys())
        num_vlans = len(vlan_ids)

        if num_vlans < pf_num:
            return False, vm_ip_map, vm_iface_map, {}, (
                f"Insufficient VLAN IDs: need {pf_num} different VLAN IDs, "
                f"but node '{node_name}' only has {num_vlans} VLAN IDs "
                f"(available VLANs: {vlan_ids})"
            )

        # 步骤 3：选择前 pf_num 个 VLAN ID 用于分配
        # 按 VLAN ID 排序后选择，确保分配的可预测性和一致性
        selected_vlan_ids = vlan_ids[:pf_num]

        logger.debug(
            f"VLAN allocation plan for node '{node_name}': "
            f"{num_vms} VM(s), {pf_num} interface(s)/VM, "
            f"selecting {len(selected_vlan_ids)} VLAN(s) from {num_vlans} VLANs: {selected_vlan_ids}"
        )

        # 步骤 4：验证每个选中的 VLAN 组有足够的接口
        # 每个 VLAN 组需要至少 num_vms 个接口（每台虚拟机 1 个）
        for vlan_id in selected_vlan_ids:
            available_in_vlan = len(vlan_groups[vlan_id])
            if available_in_vlan < num_vms:
                return False, vm_ip_map, vm_iface_map, {}, (
                    f"Insufficient interfaces in VLAN {vlan_id}: "
                    f"need {num_vms} interface(s) (1 per VM), "
                    f"but only {available_in_vlan} available"
                )

        # 步骤 5：为每台虚拟机分配接口
        # 跟踪每个 VLAN 组的分配索引，避免重复分配
        vlan_allocation_index = {vlan_id: 0 for vlan_id in selected_vlan_ids}

        for vm_id in vm_id_list:
            vm_ips = []
            vm_ifaces = []
            vm_configs = []

            # 从每个选中的 VLAN 组为当前虚拟机分配 1 个接口
            for vlan_id in selected_vlan_ids:
                # 获取当前 VLAN 组中下一个可用的接口配置
                config_index = vlan_allocation_index[vlan_id]
                config = vlan_groups[vlan_id][config_index]

                # 记录分配的接口信息
                vm_ips.append(config.ip_address)
                vm_ifaces.append({
                    "mac_address": config.mac_address,
                    "vlan_id": config.vlan_id,
                    "ip_address": config.ip_address,
                    "subnet_mask": config.subnet_mask,
                    "gateway": config.gateway
                })
                vm_configs.append(config)

                # 更新分配索引，指向下一个可用接口
                vlan_allocation_index[vlan_id] = config_index + 1

            vm_ip_map[vm_id] = vm_ips
            vm_iface_map[vm_id] = vm_ifaces
            vm_configs_map[vm_id] = vm_configs

            logger.debug(
                f"Allocated {len(vm_ifaces)} interface(s) for VM '{vm_id}', "
                f"VLAN ID set: {[iface['vlan_id'] for iface in vm_ifaces]}"
            )

        return True, vm_ip_map, vm_iface_map, vm_configs_map, ""

    def release_ips_for_vms(self, vm_id_list: List[str]) -> Tuple[bool, str]:
        """
        释放虚拟机的 IP 地址（将配置标记为未使用）

        直接从 NetworkConfig 表中根据 vm_id 查找对应的网络配置，
        然后将配置标记为未使用，并清空 vm_id 字段。

        :param vm_id_list: 需要释放的虚拟机 ID 列表
        :return: (success, error_message) 元组
        """
        with self._lock:
            try:
                if not vm_id_list:
                    logger.warning("Empty VM ID list for release")
                    return True, ""

                total_released = 0
                for vm_id in vm_id_list:
                    configs = self._network_config_dao.get_by_vm_id(vm_id)
                    if not configs:
                        logger.warning(f"No network configs found for VM {vm_id}")
                        continue

                    success = self._network_config_dao.mark_as_unused_by_vm_id(vm_id)
                    if not success:
                        error_msg = f"Failed to release IPs for VM {vm_id}"
                        logger.error(error_msg)
                        return False, error_msg

                    total_released += len(configs)
                    logger.info(
                        f"Released {len(configs)} interface(s) for VM {vm_id}"
                    )

                logger.info(
                    f"Released {total_released} interface(s) for {len(vm_id_list)} VM(s)"
                )
                return True, ""

            except Exception as e:
                db.session.rollback()
                error_msg = f"Failed to release IPs: {str(e)}"
                logger.error(error_msg)
                return False, error_msg

    def _release_macs(self, mac_addresses: List[str]):
        """
        将指定的 MAC 地址对应的网络配置标记为未使用

        :param mac_addresses: MAC 地址列表
        """
        self._network_config_dao.mark_as_unused_by_mac(mac_addresses)
        logger.info(f"Marked {len(mac_addresses)} MAC addresses as unused")

    def release_interfaces_by_macs(self, mac_addresses: List[str]) -> Tuple[bool, str]:
        """
        释放指定的网络接口（用于虚机部署失败时回滚）

        当虚机部署失败时，已分配但未使用的网络接口需要释放回资源池。
        此方法直接将指定的 MAC 地址对应的网络配置标记为未使用。

        :param mac_addresses: 需要释放的 MAC 地址列表
        :return: (success, error_message) 元组
        """
        with self._lock:
            try:
                if not mac_addresses:
                    logger.warning("Empty MAC address list provided")
                    return True, ""

                self._release_macs(mac_addresses)

                logger.info(f"Released {len(mac_addresses)} interface(s) for failed deployment")
                return True, ""

            except Exception as e:
                db.session.rollback()
                error_msg = f"Failed to release interfaces: {str(e)}"
                logger.error(error_msg)
                return False, error_msg

    def has_used_configs(self) -> bool:
        """
        Check if any network config is in 'used' status

        :return: True if there are used configs, False otherwise
        """
        return self._has_used_configs()

    def _has_used_configs(self) -> bool:
        """Check if any network config is in 'used' status"""
        used_count = self._network_config_dao.count_by_status(NetworkConfig.STATUS_USED)
        return used_count > 0

    def _validate_yaml_completeness(self, config_dict: Dict[str, NodeConfig]):
        """
        Validate YAML contains necessary parameters

        :param config_dict: Parsed configuration dictionary
        :raises ValidationError: If validation fails
        """
        if not config_dict:
            raise ValidationError("Network configuration is empty")

        for node_name, node_config in config_dict.items():
            if not node_config.node_name:
                raise ValidationError(f"Node is missing node_name")

            if not node_config.node_ip:
                raise ValidationError(f"Node '{node_name}' is missing node_ip")

            if not node_config.interfaces:
                raise ValidationError(
                    f"Node '{node_name}' is missing interface configuration"
                )

            for idx, interface in enumerate(node_config.interfaces):
                if not interface.mac_address:
                    raise ValidationError(
                        f"Node '{node_name}' interface[{idx}] is missing mac_address"
                    )
                if not interface.ip_address:
                    raise ValidationError(
                        f"Node '{node_name}' interface[{idx}] is missing ip_address"
                    )
                if not interface.subnet_mask:
                    raise ValidationError(
                        f"Node '{node_name}' interface[{idx}] is missing subnet_mask"
                    )
                if not interface.gateway:
                    raise ValidationError(
                        f"Node '{node_name}' interface[{idx}] is missing gateway"
                    )

    def _clear_all_configs(self):
        """Clear all existing network configurations"""
        self._network_config_dao.delete_all()

    def _store_configs(self, config_dict: Dict[str, NodeConfig]):
        """
        Store parsed configurations to database

        :param config_dict: Parsed configuration dictionary
        """
        configs = []
        for node_name, node_config in config_dict.items():
            for interface in node_config.interfaces:
                config = NetworkConfig(
                    node_name=node_config.node_name,
                    mac_address=interface.mac_address,
                    vlan_id=interface.vlan_id,
                    ip_address=interface.ip_address,
                    subnet_mask=interface.subnet_mask,
                    gateway=interface.gateway,
                    status=NetworkConfig.STATUS_UNUSED
                )
                configs.append(config)
        
        self._network_config_dao.create_batch(configs)

    def _get_unused_configs_by_node(self, node_name: str) -> List[NetworkConfig]:
        """
        Get unused network configs for a specific node

        :param node_name: Target node name
        :return: List of unused NetworkConfig objects
        """
        return self._network_config_dao.get_unused_by_node(node_name)

    def _mark_configs_as_used(
        self, configs: List[NetworkConfig], vm_id: Optional[str] = None
    ):
        """
        Mark network configs as used and optionally associate with a VM ID

        :param configs: List of NetworkConfig objects to mark
        :param vm_id: Optional VM ID to associate with the configs
        """
        self._network_config_dao.mark_as_used(configs, vm_id)


g_network_config_service = None


def get_network_config_service() -> NetworkConfigService:
    """Get or create the global network config service instance"""
    global g_network_config_service
    if g_network_config_service is None:
        g_network_config_service = NetworkConfigService()
    return g_network_config_service


def init_network_config_service():
    """Initialize the network config service"""
    global g_network_config_service
    g_network_config_service = NetworkConfigService()
    logger.info("Network config service initialized")
