# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
DAO implementations for NetworkConfig, VmInstance and VmSoftware models
Concrete implementations of database operations
"""

import logging
from typing import List, Optional

from virtcca_deploy.services.db_service import db, NetworkConfig, VmInstance, VmSoftware, DeviceAllocation
from virtcca_deploy.services.dao.interfaces import NetworkConfigDAOInterface, VmInstanceDAOInterface, VmSoftwareDAOInterface, DeviceAllocationDAOInterface

logger = logging.getLogger(__name__)


class NetworkConfigDAO(NetworkConfigDAOInterface):
    """Implementation of NetworkConfig database operations"""

    def create(self, network_config: NetworkConfig) -> NetworkConfig:
        """Create a new network config record"""
        try:
            db.session.add(network_config)
            db.session.commit()
            logger.info(f"Created network config: {network_config}")
            return network_config
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to create network config: {e}")
            raise

    def create_batch(self, configs: List[NetworkConfig]) -> List[NetworkConfig]:
        """Create multiple network config records in batch"""
        try:
            for config in configs:
                db.session.add(config)
            db.session.commit()
            logger.info(f"Created {len(configs)} network configs in batch")
            return configs
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to create network configs in batch: {e}")
            raise

    def get_by_id(self, config_id: int) -> Optional[NetworkConfig]:
        """Get network config by ID"""
        try:
            return db.session.get(NetworkConfig, config_id)
        except Exception as e:
            logger.error(f"Failed to get network config by id {config_id}: {e}")
            raise

    def get_by_node_name(self, node_name: str) -> List[NetworkConfig]:
        """Get all network configs for a specific node"""
        try:
            return NetworkConfig.query.filter_by(node_name=node_name).all()
        except Exception as e:
            logger.error(f"Failed to get network configs by node_name {node_name}: {e}")
            raise

    def get_by_mac_address(self, mac_address: str) -> Optional[NetworkConfig]:
        """Get network config by MAC address"""
        try:
            return NetworkConfig.query.filter_by(mac_address=mac_address).first()
        except Exception as e:
            logger.error(f"Failed to get network config by mac_address {mac_address}: {e}")
            raise

    def get_unused_by_node(self, node_name: str) -> List[NetworkConfig]:
        """Get unused network configs for a specific node"""
        try:
            return NetworkConfig.query.filter_by(
                node_name=node_name,
                status=NetworkConfig.STATUS_UNUSED
            ).order_by(NetworkConfig.id).all()
        except Exception as e:
            logger.error(f"Failed to get unused configs by node_name {node_name}: {e}")
            raise

    def get_by_status(self, status: str) -> List[NetworkConfig]:
        """Get network configs by status"""
        try:
            return NetworkConfig.query.filter_by(status=status).all()
        except Exception as e:
            logger.error(f"Failed to get network configs by status {status}: {e}")
            raise

    def update_status(self, config_id: int, status: str) -> bool:
        """Update the status of a network config"""
        try:
            config = db.session.get(NetworkConfig, config_id)
            if not config:
                logger.warning(f"Network config {config_id} not found")
                return False
            config.status = status
            config.updated_at = db.func.current_timestamp()
            db.session.commit()
            logger.info(f"Updated network config {config_id} status to {status}")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update network config {config_id} status: {e}")
            raise

    def update_status_batch(self, configs: List[NetworkConfig], status: str) -> bool:
        """Update the status of multiple network configs"""
        try:
            for config in configs:
                config.status = status
                config.updated_at = db.func.current_timestamp()
            db.session.commit()
            logger.info(f"Updated {len(configs)} network configs status to {status}")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update network configs status in batch: {e}")
            raise

    def delete_all(self) -> bool:
        """Delete all network configs"""
        try:
            NetworkConfig.query.delete()
            db.session.commit()
            logger.info("Deleted all network configs")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to delete all network configs: {e}")
            raise

    def count_by_status(self, status: str) -> int:
        """Count network configs by status"""
        try:
            return NetworkConfig.query.filter_by(status=status).count()
        except Exception as e:
            logger.error(f"Failed to count network configs by status {status}: {e}")
            raise

    def mark_as_used(self, configs: List[NetworkConfig]) -> bool:
        """Mark network configs as used"""
        return self.update_status_batch(configs, NetworkConfig.STATUS_USED)

    def mark_as_unused_by_mac(self, mac_addresses: List[str]) -> bool:
        """Mark network configs as unused by MAC addresses"""
        try:
            for mac in mac_addresses:
                config = NetworkConfig.query.filter_by(mac_address=mac).first()
                if config:
                    config.status = NetworkConfig.STATUS_UNUSED
                    config.updated_at = db.func.current_timestamp()
                    logger.info(f"Marked config as unused for MAC {mac}")
            db.session.commit()
            logger.info(f"Marked {len(mac_addresses)} configs as unused")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to mark configs as unused: {e}")
            raise


class VmInstanceDAO(VmInstanceDAOInterface):
    """Implementation of VmInstance database operations"""

    def create(self, vm_instance: VmInstance) -> VmInstance:
        """Create a new VM instance record"""
        try:
            db.session.add(vm_instance)
            db.session.commit()
            logger.info(f"Created VM instance: {vm_instance}")
            return vm_instance
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to create VM instance: {e}")
            raise

    def get_by_id(self, instance_id: int) -> Optional[VmInstance]:
        """Get VM instance by ID"""
        try:
            return db.session.get(VmInstance, instance_id)
        except Exception as e:
            logger.error(f"Failed to get VM instance by id {instance_id}: {e}")
            raise

    def get_by_vm_id(self, vm_id: str) -> Optional[VmInstance]:
        """Get VM instance by vm_id"""
        try:
            return VmInstance.query.filter_by(vm_id=vm_id).first()
        except Exception as e:
            logger.error(f"Failed to get VM instance by vm_id {vm_id}: {e}")
            raise

    def get_by_vm_ids(self, vm_id_list: List[str]) -> List[VmInstance]:
        """Get VM instances by list of vm_ids"""
        try:
            return VmInstance.query.filter(VmInstance.vm_id.in_(vm_id_list)).all()
        except Exception as e:
            logger.error(f"Failed to get VM instances by vm_ids: {e}")
            raise

    def get_by_host_ip(self, host_ip: str) -> List[VmInstance]:
        """Get all VM instances on a specific host"""
        try:
            return VmInstance.query.filter_by(host_ip=host_ip).all()
        except Exception as e:
            logger.error(f"Failed to get VM instances by host_ip {host_ip}: {e}")
            raise

    def get_by_vm_id_and_host(self, vm_id: str, host_ip: str) -> Optional[VmInstance]:
        """Get VM instance by vm_id and host_ip"""
        try:
            return VmInstance.query.filter_by(vm_id=vm_id, host_ip=host_ip).first()
        except Exception as e:
            logger.error(f"Failed to get VM instance by vm_id {vm_id} and host_ip {host_ip}: {e}")
            raise

    def update(self, vm_instance: VmInstance) -> bool:
        """Update an existing VM instance record"""
        try:
            db.session.commit()
            logger.info(f"Updated VM instance: {vm_instance}")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update VM instance: {e}")
            raise

    def delete_by_vm_id(self, vm_id: str) -> bool:
        """Delete VM instance by vm_id"""
        try:
            vm_instance = VmInstance.query.filter_by(vm_id=vm_id).first()
            if vm_instance:
                db.session.delete(vm_instance)
                db.session.commit()
                logger.info(f"Deleted VM instance: {vm_id}")
                return True
            logger.warning(f"VM instance {vm_id} not found for deletion")
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to delete VM instance {vm_id}: {e}")
            raise

    def delete_by_vm_ids(self, vm_id_list: List[str]) -> bool:
        """Delete VM instances by list of vm_ids"""
        try:
            vm_instances = VmInstance.query.filter(VmInstance.vm_id.in_(vm_id_list)).all()
            for vm in vm_instances:
                db.session.delete(vm)
            db.session.commit()
            logger.info(f"Deleted {len(vm_instances)} VM instances")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to delete VM instances: {e}")
            raise

    def exists_by_vm_id(self, vm_id: str) -> bool:
        """Check if a VM instance exists by vm_id"""
        try:
            return VmInstance.query.filter_by(vm_id=vm_id).first() is not None
        except Exception as e:
            logger.error(f"Failed to check existence of VM instance {vm_id}: {e}")
            raise

    def count_by_host_ip(self, host_ip: str) -> int:
        """Count VM instances on a specific host"""
        try:
            return VmInstance.query.filter_by(host_ip=host_ip).count()
        except Exception as e:
            logger.error(f"Failed to count VM instances by host_ip {host_ip}: {e}")
            raise

    def query_with_filters(self, host_ips: Optional[List[str]] = None,
                          vm_ids: Optional[List[str]] = None,
                          page: int = 1, page_size: int = 10) -> tuple:
        """Query VM instances with filters and pagination"""
        try:
            query = VmInstance.query
            
            if host_ips:
                query = query.filter(VmInstance.host_ip.in_(host_ips))
            elif vm_ids:
                query = query.filter(VmInstance.vm_id.in_(vm_ids))
            
            total_count = query.count()
            offset = (page - 1) * page_size
            vm_instances = query.offset(offset).limit(page_size).all()
            
            return total_count, vm_instances
        except Exception as e:
            logger.error(f"Failed to query VM instances with filters: {e}")
            raise


class VmSoftwareDAO(VmSoftwareDAOInterface):
    """Implementation of VmSoftware database operations"""

    def create(self, vm_software: VmSoftware) -> VmSoftware:
        """Create a new software record"""
        try:
            db.session.add(vm_software)
            db.session.commit()
            logger.info(f"Created software record: {vm_software}")
            return vm_software
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to create software record: {e}")
            raise

    def get_by_id(self, software_id: int) -> Optional[VmSoftware]:
        """Get software by ID"""
        try:
            return db.session.get(VmSoftware, software_id)
        except Exception as e:
            logger.error(f"Failed to get software by id {software_id}: {e}")
            raise

    def get_by_file_name(self, file_name: str) -> Optional[VmSoftware]:
        """Get software by file name"""
        try:
            return VmSoftware.query.filter_by(file_name=file_name).first()
        except Exception as e:
            logger.error(f"Failed to get software by file_name {file_name}: {e}")
            raise

    def get_all(self) -> List[VmSoftware]:
        """Get all software records"""
        try:
            return VmSoftware.query.all()
        except Exception as e:
            logger.error(f"Failed to get all software records: {e}")
            raise

    def update(self, vm_software: VmSoftware) -> bool:
        """Update an existing software record"""
        try:
            db.session.commit()
            logger.info(f"Updated software record: {vm_software}")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update software record: {e}")
            raise

    def delete_by_id(self, software_id: int) -> bool:
        """Delete software by ID"""
        try:
            vm_software = db.session.get(VmSoftware, software_id)
            if vm_software:
                db.session.delete(vm_software)
                db.session.commit()
                logger.info(f"Deleted software record: {software_id}")
                return True
            logger.warning(f"Software record {software_id} not found for deletion")
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to delete software record {software_id}: {e}")
            raise

    def delete_by_file_name(self, file_name: str) -> bool:
        """Delete software by file name"""
        try:
            vm_software = VmSoftware.query.filter_by(file_name=file_name).first()
            if vm_software:
                db.session.delete(vm_software)
                db.session.commit()
                logger.info(f"Deleted software record: {file_name}")
                return True
            logger.warning(f"Software record {file_name} not found for deletion")
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to delete software record {file_name}: {e}")
            raise

    def exists_by_file_name(self, file_name: str) -> bool:
        """Check if software exists by file name"""
        try:
            return VmSoftware.query.filter_by(file_name=file_name).first() is not None
        except Exception as e:
            logger.error(f"Failed to check existence of software {file_name}: {e}")
            raise

    def count(self) -> int:
        """Count total software records"""
        try:
            return VmSoftware.query.count()
        except Exception as e:
            logger.error(f"Failed to count software records: {e}")
            raise


class DeviceAllocationDAO(DeviceAllocationDAOInterface):
    """Implementation of DeviceAllocation database operations"""

    def get_by_mac_address(self, mac_address: str) -> Optional[DeviceAllocation]:
        """Get device allocation by MAC address"""
        try:
            return DeviceAllocation.query.filter_by(mac_address=mac_address).first()
        except Exception as e:
            logger.error(f"Failed to get device allocation by mac_address {mac_address}: {e}")
            raise
