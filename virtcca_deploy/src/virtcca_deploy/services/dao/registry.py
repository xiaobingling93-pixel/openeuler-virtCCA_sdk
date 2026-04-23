# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
DAO registry for dependency injection
Provides centralized access to DAO instances
"""

from virtcca_deploy.services.dao.impl import NetworkConfigDAO, VmInstanceDAO, VmSoftwareDAO, DeviceAllocationDAO
from virtcca_deploy.services.dao.interfaces import NetworkConfigDAOInterface, VmInstanceDAOInterface, VmSoftwareDAOInterface, DeviceAllocationDAOInterface


class DAORegistry:
    """Registry for DAO instances, supporting dependency injection"""

    def __init__(self):
        self._network_config_dao: NetworkConfigDAOInterface = NetworkConfigDAO()
        self._vm_instance_dao: VmInstanceDAOInterface = VmInstanceDAO()
        self._vm_software_dao: VmSoftwareDAOInterface = VmSoftwareDAO()
        self._device_allocation_dao: DeviceAllocationDAOInterface = DeviceAllocationDAO()

    @property
    def network_config_dao(self) -> NetworkConfigDAOInterface:
        """Get NetworkConfig DAO instance"""
        return self._network_config_dao

    @network_config_dao.setter
    def network_config_dao(self, dao: NetworkConfigDAOInterface):
        """Set NetworkConfig DAO instance (for testing/mocking)"""
        self._network_config_dao = dao

    @property
    def vm_instance_dao(self) -> VmInstanceDAOInterface:
        """Get VmInstance DAO instance"""
        return self._vm_instance_dao

    @vm_instance_dao.setter
    def vm_instance_dao(self, dao: VmInstanceDAOInterface):
        """Set VmInstance DAO instance (for testing/mocking)"""
        self._vm_instance_dao = dao

    @property
    def vm_software_dao(self) -> VmSoftwareDAOInterface:
        """Get VmSoftware DAO instance"""
        return self._vm_software_dao

    @vm_software_dao.setter
    def vm_software_dao(self, dao: VmSoftwareDAOInterface):
        """Set VmSoftware DAO instance (for testing/mocking)"""
        self._vm_software_dao = dao

    @property
    def device_allocation_dao(self) -> DeviceAllocationDAOInterface:
        """Get DeviceAllocation DAO instance"""
        return self._device_allocation_dao

    @device_allocation_dao.setter
    def device_allocation_dao(self, dao: DeviceAllocationDAOInterface):
        """Set DeviceAllocation DAO instance (for testing/mocking)"""
        self._device_allocation_dao = dao


g_dao_registry = None


def get_dao_registry() -> DAORegistry:
    """Get or create the global DAO registry instance"""
    global g_dao_registry
    if g_dao_registry is None:
        g_dao_registry = DAORegistry()
    return g_dao_registry


def init_dao_registry() -> DAORegistry:
    """Initialize the DAO registry"""
    global g_dao_registry
    g_dao_registry = DAORegistry()
    return g_dao_registry
