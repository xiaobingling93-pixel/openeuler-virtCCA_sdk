# Copyright (c) Huawei Technologies Co., Ltd., 2026. All rights reserved.

"""
Network configuration parser and validator for YAML-based IP allocation
"""

import logging
import re
from typing import Dict, List, Optional

import yaml

from virtcca_deploy.common.constants import ValidationError


logger = logging.getLogger(__name__)


class NetworkConfig:
    """Represents a single network interface configuration"""

    def __init__(self, mac_address: str, vlan_id: int,
                 ip_address: str, subnet_mask: str, gateway: str):
        self.mac_address = mac_address
        self.vlan_id = vlan_id
        self.ip_address = ip_address
        self.subnet_mask = subnet_mask
        self.gateway = gateway

    def to_dict(self) -> Dict:
        return {
            "mac_address": self.mac_address,
            "vlan_id": self.vlan_id,
            "ip_address": self.ip_address,
            "subnet_mask": self.subnet_mask,
            "gateway": self.gateway
        }


class NodeConfig:
    """Represents a compute node with its network interfaces"""

    def __init__(self, node_name: str, node_ip: str,
                 interfaces: List[NetworkConfig]):
        self.node_name = node_name
        self.node_ip = node_ip
        self.interfaces = interfaces

    def to_dict(self) -> Dict:
        return {
            "node_name": self.node_name,
            "node_ip": self.node_ip,
            "interfaces": [iface.to_dict() for iface in self.interfaces]
        }


class YamlNetworkConfigParser:
    """
    Parses and validates YAML network configuration files
    """

    REQUIRED_NODE_FIELDS = ["node_name", "node_ip", "interfaces"]
    REQUIRED_INTERFACE_FIELDS = ["vlan_id",
                                 "ip_address", "subnet_mask", "gateway"]

    MAC_PATTERN = re.compile(
        r'^([0-9A-Fa-f]{2}[:]){5}([0-9A-Fa-f]{2})$'
    )
    IP_PATTERN = re.compile(
        r'^(\d{1,3}\.){3}\d{1,3}$'
    )

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._config: Dict[str, NodeConfig] = {}

    def load_from_file(self, file_path: str) -> Dict[str, NodeConfig]:
        """
        Load and validate network configuration from a YAML file

        :param file_path: Path to the YAML configuration file
        :return: Dictionary mapping node_name to NodeConfig
        :raises ValidationError: If the file cannot be read or parsed
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                raw_config = yaml.safe_load(f)
        except FileNotFoundError:
            raise ValidationError(
                f"Network configuration file not found: {file_path}"
            )
        except yaml.YAMLError as e:
            raise ValidationError(
                f"Invalid YAML format in {file_path}: {e}"
            )

        self._config = self._parse_and_validate(raw_config)
        self.logger.info(
            f"Loaded network configuration for {len(self._config)} node(s)"
        )
        return self._config

    def load_from_string(self, yaml_string: str) -> Dict[str, NodeConfig]:
        """
        Load and validate network configuration from a YAML string

        :param yaml_string: YAML configuration string
        :return: Dictionary mapping node_name to NodeConfig
        :raises ValidationError: If the string cannot be parsed
        """
        try:
            raw_config = yaml.safe_load(yaml_string)
        except yaml.YAMLError as e:
            raise ValidationError(f"Invalid YAML format: {e}")

        self._config = self._parse_and_validate(raw_config)
        self.logger.info(
            f"Loaded network configuration for {len(self._config)} node(s)"
        )
        return self._config

    def get_node_config(self, node_name: str) -> Optional[NodeConfig]:
        """
        Get configuration for a specific node

        :param node_name: Name of the node
        :return: NodeConfig if found, None otherwise
        """
        return self._config.get(node_name)

    def get_all_nodes(self) -> Dict[str, NodeConfig]:
        """
        Get all node configurations

        :return: Dictionary mapping node_name to NodeConfig
        """
        return self._config.copy()

    def _parse_and_validate(self, raw_config: Dict) -> Dict[str, NodeConfig]:
        """
        Parse and validate the raw YAML configuration

        :param raw_config: Raw YAML data
        :return: Validated configuration dictionary
        :raises ValidationError: If validation fails
        """
        if not isinstance(raw_config, dict):
            raise ValidationError(
                "YAML configuration must be a dictionary"
            )

        if "nodes" not in raw_config:
            raise ValidationError(
                "YAML configuration must contain 'nodes' key"
            )

        nodes_data = raw_config["nodes"]
        if not isinstance(nodes_data, list):
            raise ValidationError(
                "'nodes' must be a list"
            )

        if len(nodes_data) == 0:
            raise ValidationError(
                "'nodes' list cannot be empty"
            )

        config_dict = {}
        for idx, node_data in enumerate(nodes_data):
            node_config = self._validate_node(node_data, idx)
            if node_config.node_name in config_dict:
                raise ValidationError(
                    f"Duplicate node_name: {node_config.node_name}"
                )
            config_dict[node_config.node_name] = node_config

        self._check_ip_conflicts(config_dict)
        return config_dict

    def _validate_node(self, node_data: Dict, index: int) -> NodeConfig:
        if not isinstance(node_data, dict):
            raise ValidationError(
                f"Node at index {index} must be a dictionary"
            )

        for field in self.REQUIRED_NODE_FIELDS:
            if field not in node_data:
                raise ValidationError(
                    f"Node at index {index} missing required field: {field}"
                )

        node_name = str(node_data["node_name"]).strip()
        if not node_name:
            raise ValidationError(
                f"Node at index {index} has empty node_name"
            )

        node_ip = str(node_data["node_ip"]).strip()
        self._validate_ip_address(node_ip, f"Node '{node_name}' node_ip")

        interfaces_data = node_data["interfaces"]
        if not isinstance(interfaces_data, list):
            raise ValidationError(
                f"Node '{node_name}' interfaces must be a list"
            )

        if len(interfaces_data) == 0:
            raise ValidationError(
                f"Node '{node_name}' must have at least one interface"
            )

        interfaces = []
        for iface_data in interfaces_data:
            interface = self._validate_interface(
                iface_data, node_name
            )
            interfaces.append(interface)

        return NodeConfig(node_name, node_ip, interfaces)

    def _validate_interface(self, iface_data: Dict,
                           node_name: str) -> NetworkConfig:
        if not isinstance(iface_data, dict):
            raise ValidationError(
                f"Interface in node '{node_name}' must be a dictionary"
            )

        if "mac_address" not in iface_data:
            raise ValidationError(
                f"Interface in node '{node_name}' missing required field: mac_address"
            )

        for field in self.REQUIRED_INTERFACE_FIELDS:
            if field not in iface_data:
                raise ValidationError(
                    f"Interface in node '{node_name}' "
                    f"missing required field: {field}"
                )

        mac_address = str(iface_data["mac_address"]).strip()
        self._validate_mac_address(
            mac_address, f"Interface in node '{node_name}'"
        )

        vlan_id = iface_data["vlan_id"]
        self._validate_vlan_id(
            vlan_id, f"Interface in node '{node_name}'"
        )

        ip_address = str(iface_data["ip_address"]).strip()
        self._validate_ip_address(
            ip_address, f"Interface in node '{node_name}'"
        )

        subnet_mask = str(iface_data["subnet_mask"]).strip()
        self._validate_subnet_mask(
            subnet_mask, f"Interface in node '{node_name}'"
        )

        gateway = str(iface_data["gateway"]).strip()
        self._validate_ip_address(
            gateway, f"Gateway in interface in node '{node_name}'"
        )

        return NetworkConfig(
            mac_address=mac_address,
            vlan_id=int(vlan_id),
            ip_address=ip_address,
            subnet_mask=subnet_mask,
            gateway=gateway
        )

    def _validate_mac_address(self, mac: str, context: str):
        """Validate MAC address format"""
        if not self.MAC_PATTERN.match(mac):
            raise ValidationError(
                f"{context} has invalid MAC address format: {mac}. "
                f"Expected format: XX:XX:XX:XX:XX:XX"
            )

    def _validate_ip_address(self, ip: str, context: str):
        """Validate IPv4 address format and range"""
        if not self.IP_PATTERN.match(ip):
            raise ValidationError(
                f"{context} has invalid IP address format: {ip}"
            )

        octets = ip.split('.')
        for octet in octets:
            value = int(octet)
            if value < 0 or value > 255:
                raise ValidationError(
                    f"{context} has invalid IP address: {ip}. "
                    f"Each octet must be 0-255"
                )

    def _validate_subnet_mask(self, mask: str, context: str):
        """Validate subnet mask format and validity"""
        if not self.IP_PATTERN.match(mask):
            raise ValidationError(
                f"{context} has invalid subnet mask format: {mask}"
            )

        valid_masks = [
            "255.255.255.255", "255.255.255.254", "255.255.255.252",
            "255.255.255.248", "255.255.255.240", "255.255.255.224",
            "255.255.255.192", "255.255.255.128", "255.255.255.0",
            "255.255.254.0", "255.255.252.0", "255.255.248.0",
            "255.255.240.0", "255.255.224.0", "255.255.192.0",
            "255.255.128.0", "255.255.0.0", "255.254.0.0",
            "255.252.0.0", "255.248.0.0", "255.240.0.0",
            "255.224.0.0", "255.192.0.0", "255.128.0.0",
            "255.0.0.0"
        ]

        if mask not in valid_masks:
            raise ValidationError(
                f"{context} has invalid subnet mask: {mask}. "
                f"Must be a valid subnet mask (e.g., 255.255.255.0)"
            )

    def _validate_vlan_id(self, vlan_id, context: str):
        """Validate VLAN ID range"""
        if not isinstance(vlan_id, int):
            raise ValidationError(
                f"{context} vlan_id must be an integer, "
                f"got {type(vlan_id).__name__}"
            )

        if vlan_id < 0 or vlan_id > 4095:
            raise ValidationError(
                f"{context} has invalid VLAN ID: {vlan_id}. "
                f"Must be in range 0-4095"
            )

    def _check_ip_conflicts(self, config_dict: Dict[str, NodeConfig]):
        """
        Check for duplicate IP addresses across all nodes and interfaces

        :param config_dict: Validated configuration dictionary
        :raises ValidationError: If duplicate IPs are found
        """
        ip_usage = {}

        for node_name, node_config in config_dict.items():
            if node_config.node_ip in ip_usage:
                raise ValidationError(
                    f"Duplicate node_ip found: {node_config.node_ip} "
                    f"used by node '{ip_usage[node_config.node_ip]}' "
                    f"and node '{node_name}'"
                )
            ip_usage[node_config.node_ip] = node_name

            for interface in node_config.interfaces:
                if interface.ip_address in ip_usage:
                    raise ValidationError(
                        f"Duplicate IP address found: {interface.ip_address} "
                        f"used by '{ip_usage[interface.ip_address]}' "
                        f"and interface '{interface.mac_address}' in node '{node_name}'"
                    )
                ip_usage[interface.ip_address] = (
                    f"{node_name}/{interface.mac_address}"
                )

        self.logger.info("No IP conflicts detected in configuration")
