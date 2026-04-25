# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
DAO interfaces for NetworkConfig and VmInstance models
Defines abstract interfaces for database operations
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from virtcca_deploy.services.db_service import NetworkConfig, VmInstance, VmSoftware, DeviceAllocation


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
    def mark_as_used(self, configs: List[NetworkConfig], vm_id: Optional[str] = None) -> bool:
        """Mark network configs as used
        
        :param configs: List of NetworkConfig objects to mark as used
        :param vm_id: Optional VM ID to associate with the configs
        """
        pass

    @abstractmethod
    def mark_as_unused_by_mac(self, mac_addresses: List[str]) -> bool:
        """Mark network configs as unused by MAC addresses"""
        pass

    @abstractmethod
    def get_by_vm_id(self, vm_id: str) -> List[NetworkConfig]:
        """Get network configs associated with a specific VM ID"""
        pass

    @abstractmethod
    def mark_as_unused_by_vm_id(self, vm_id: str) -> bool:
        """Mark network configs as unused by VM ID and clear vm_id field"""
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


class VmSoftwareDAOInterface(ABC):
    """Interface for VmSoftware database operations"""

    @abstractmethod
    def create(self, vm_software: VmSoftware) -> VmSoftware:
        """Create a new software record"""
        pass

    @abstractmethod
    def get_by_id(self, software_id: int) -> Optional[VmSoftware]:
        """Get software by ID"""
        pass

    @abstractmethod
    def get_by_file_name(self, file_name: str) -> Optional[VmSoftware]:
        """Get software by file name"""
        pass

    @abstractmethod
    def get_all(self) -> List[VmSoftware]:
        """Get all software records"""
        pass

    @abstractmethod
    def update(self, vm_software: VmSoftware) -> bool:
        """Update an existing software record"""
        pass

    @abstractmethod
    def delete_by_id(self, software_id: int) -> bool:
        """Delete software by ID"""
        pass

    @abstractmethod
    def delete_by_file_name(self, file_name: str) -> bool:
        """Delete software by file name"""
        pass

    @abstractmethod
    def exists_by_file_name(self, file_name: str) -> bool:
        """Check if software exists by file name"""
        pass

    @abstractmethod
    def count(self) -> int:
        """Count total software records"""
        pass


class DeviceAllocationDAOInterface(ABC):
    """Interface for DeviceAllocation database operations"""

    @abstractmethod
    def get_by_mac_address(self, mac_address: str) -> Optional[DeviceAllocation]:
        """Get device allocation by MAC address"""
        pass

    @abstractmethod
    def get_by_bdf(self, bdf: str) -> Optional[DeviceAllocation]:
        """Get device allocation by BDF address"""
        pass

    @abstractmethod
    def allocate_devices_by_mac(
        self,
        mac_addresses: List[str],
        vm_id: str
    ) -> dict:
        """
        Allocate devices based on MAC addresses with concurrency protection.

        This method allocates devices for the given VM by checking the status of each MAC address.
        If any device is unavailable, the entire allocation fails and no devices are allocated.

        :param mac_addresses: List of MAC addresses to allocate devices for.
        :param vm_id: The VM ID to assign to the allocated devices.
        :return: A dictionary mapping MAC addresses to BDF addresses for successfully allocated devices.
                Returns an empty dictionary if any allocation fails.
        :raises RuntimeError: If the allocation process fails or an error occurs.
        """
        pass

    @abstractmethod
    def get_all_bdfs(self) -> set:
        """Get all BDFs from device allocation records"""
        pass

    @abstractmethod
    def insert_device(self, device_record: DeviceAllocation) -> None:
        """Insert a new device allocation record"""
        pass

    @abstractmethod
    def update_device(
        self,
        bdf: str,
        numa_node: int,
        vendor_id: int,
        device_id: int,
        device_name: Optional[str],
        mac_address: Optional[str],
        preserve_mac: bool = False
    ) -> bool:
        """
        Update device allocation record by BDF.

        :param bdf: BDF address to identify the record
        :param numa_node: NUMA node value
        :param vendor_id: Vendor ID
        :param device_id: Device ID
        :param device_name: Device name
        :param mac_address: MAC address
        :param preserve_mac: If True and mac_address is None, keep existing MAC address
        :return: True if record was updated, False if record not found
        """
        pass
