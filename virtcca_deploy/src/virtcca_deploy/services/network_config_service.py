# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
Network configuration service for managing YAML-based network configs
Handles upload, validation, storage, and IP allocation from database
"""

import logging
from typing import Dict, List, Tuple

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
        Allocate IPs for VM deployment from database

        :param node_name: Target node name
        :param pf_num: Number of PF interfaces per VM
        :param vm_id_list: List of VM IDs to allocate IPs for
        :return: (success, vm_ip_map, vm_iface_map, error_message)
        """
        with self._lock:
            vm_ip_map = {}
            vm_iface_map = {}

            try:
                unused_configs = self._get_unused_configs_by_node(node_name)

                if not unused_configs:
                    return False, vm_ip_map, vm_iface_map, (
                        f"No network configuration found for node '{node_name}'"
                    )

                total_required = len(vm_id_list) * pf_num

                if len(unused_configs) < total_required:
                    return False, vm_ip_map, vm_iface_map, (
                        f"Insufficient interfaces: required {total_required}, "
                        f"available {len(unused_configs)}"
                    )

                allocated_configs = []
                for i, vm_id in enumerate(vm_id_list):
                    vm_start = i * pf_num
                    vm_end = vm_start + pf_num
                    vm_configs = unused_configs[vm_start:vm_end]

                    vm_ips = []
                    vm_ifaces = []

                    for config in vm_configs:
                        vm_ips.append(config.ip_address)
                        vm_ifaces.append({
                            "mac_address": config.mac_address,
                            "vlan_id": config.vlan_id,
                            "ip_address": config.ip_address,
                            "subnet_mask": config.subnet_mask,
                            "gateway": config.gateway
                        })
                        allocated_configs.append(config)

                    vm_ip_map[vm_id] = vm_ips
                    vm_iface_map[vm_id] = vm_ifaces

                self._mark_configs_as_used(allocated_configs)

                logger.info(
                    f"Allocated {len(allocated_configs)} interface(s) for "
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

    def release_ips_for_vms(self, vm_id_list: List[str]) -> Tuple[bool, str]:
        """
        Release IPs for VMs (mark configs as unused)

        :param vm_id_list: List of VM IDs to release
        :return: (success, error_message)
        """
        with self._lock:
            try:
                from virtcca_deploy.services.db_service import VmInstance
                from virtcca_deploy.services.dao import get_dao_registry
                vm_instance_dao = get_dao_registry().vm_instance_dao
                import json

                mac_addresses_to_release = []
                for vm_id in vm_id_list:
                    vm_instance = vm_instance_dao.get_by_vm_id(vm_id)
                    if not vm_instance:
                        logger.warning(f"VM {vm_id} not found, skipping IP release")
                        continue

                    if not vm_instance.iface_list:
                        logger.warning(f"VM {vm_id} has no iface_list, skipping IP release")
                        continue

                    try:
                        iface_list = json.loads(vm_instance.iface_list)
                        for iface_info in iface_list:
                            mac = iface_info.get("mac_address")
                            if mac:
                                mac_addresses_to_release.append(mac)
                                logger.info(
                                    f"Queued IP release for MAC {mac} from VM {vm_id}"
                                )
                    except json.JSONDecodeError as e:
                        logger.error(
                            f"Failed to parse iface_list for VM {vm_id}: {e}"
                        )
                        continue

                if mac_addresses_to_release:
                    self._network_config_dao.mark_as_unused_by_mac(mac_addresses_to_release)
                
                logger.info(f"Released IPs for {len(vm_id_list)} VM(s)")
                return True, ""

            except Exception as e:
                db.session.rollback()
                error_msg = f"Failed to release IPs: {str(e)}"
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

    def _mark_configs_as_used(self, configs: List[NetworkConfig]):
        """
        Mark network configs as used

        :param configs: List of NetworkConfig objects to mark
        """
        self._network_config_dao.mark_as_used(configs)


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
