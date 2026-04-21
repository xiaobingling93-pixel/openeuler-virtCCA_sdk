# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
DAO interfaces for NetworkConfig and VmInstance models
Defines abstract interfaces for database operations
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from virtcca_deploy.services.db_service import NetworkConfig, VmInstance


class NetworkConfigDAOInterface(ABC):
    """Interface for NetworkConfig database operations"""

    @abstractmethod
    def create(self, network_config: NetworkConfig) -> NetworkConfig:
        """Create a new network config record"""
        pass

    @abstractmethod
    def create_batch(self, configs: List[NetworkConfig]) -> List[NetworkConfig]:
        """Create multiple network config records in batch"""
        pass

    @abstractmethod
    def get_by_id(self, config_id: int) -> Optional[NetworkConfig]:
        """Get network config by ID"""
        pass

    @abstractmethod
    def get_by_node_name(self, node_name: str) -> List[NetworkConfig]:
        """Get all network configs for a specific node"""
        pass

    @abstractmethod
    def get_by_mac_address(self, mac_address: str) -> Optional[NetworkConfig]:
        """Get network config by MAC address"""
        pass

    @abstractmethod
    def get_unused_by_node(self, node_name: str) -> List[NetworkConfig]:
        """Get unused network configs for a specific node"""
        pass

    @abstractmethod
    def get_by_status(self, status: str) -> List[NetworkConfig]:
        """Get network configs by status"""
        pass

    @abstractmethod
    def update_status(self, config_id: int, status: str) -> bool:
        """Update the status of a network config"""
        pass

    @abstractmethod
    def update_status_batch(self, configs: List[NetworkConfig], status: str) -> bool:
        """Update the status of multiple network configs"""
        pass

    @abstractmethod
    def delete_all(self) -> bool:
        """Delete all network configs"""
        pass

    @abstractmethod
    def count_by_status(self, status: str) -> int:
        """Count network configs by status"""
        pass

    @abstractmethod
    def mark_as_used(self, configs: List[NetworkConfig]) -> bool:
        """Mark network configs as used"""
        pass

    @abstractmethod
    def mark_as_unused_by_mac(self, mac_addresses: List[str]) -> bool:
        """Mark network configs as unused by MAC addresses"""
        pass


class VmInstanceDAOInterface(ABC):
    """Interface for VmInstance database operations"""

    @abstractmethod
    def create(self, vm_instance: VmInstance) -> VmInstance:
        """Create a new VM instance record"""
        pass

    @abstractmethod
    def get_by_id(self, instance_id: int) -> Optional[VmInstance]:
        """Get VM instance by ID"""
        pass

    @abstractmethod
    def get_by_vm_id(self, vm_id: str) -> Optional[VmInstance]:
        """Get VM instance by vm_id"""
        pass

    @abstractmethod
    def get_by_vm_ids(self, vm_id_list: List[str]) -> List[VmInstance]:
        """Get VM instances by list of vm_ids"""
        pass

    @abstractmethod
    def get_by_host_ip(self, host_ip: str) -> List[VmInstance]:
        """Get all VM instances on a specific host"""
        pass

    @abstractmethod
    def get_by_vm_id_and_host(self, vm_id: str, host_ip: str) -> Optional[VmInstance]:
        """Get VM instance by vm_id and host_ip"""
        pass

    @abstractmethod
    def update(self, vm_instance: VmInstance) -> bool:
        """Update an existing VM instance record"""
        pass

    @abstractmethod
    def delete_by_vm_id(self, vm_id: str) -> bool:
        """Delete VM instance by vm_id"""
        pass

    @abstractmethod
    def delete_by_vm_ids(self, vm_id_list: List[str]) -> bool:
        """Delete VM instances by list of vm_ids"""
        pass

    @abstractmethod
    def exists_by_vm_id(self, vm_id: str) -> bool:
        """Check if a VM instance exists by vm_id"""
        pass

    @abstractmethod
    def count_by_host_ip(self, host_ip: str) -> int:
        """Count VM instances on a specific host"""
        pass

    @abstractmethod
    def query_with_filters(self, host_ips: Optional[List[str]] = None, 
                          vm_ids: Optional[List[str]] = None,
                          page: int = 1, page_size: int = 10) -> tuple:
        """Query VM instances with filters and pagination
        Returns: (total_count, vm_instances)
        """
        pass
