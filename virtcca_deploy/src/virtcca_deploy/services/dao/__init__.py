# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
Data Access Object (DAO) layer for database operations
Provides interface-based access to database models
"""

from virtcca_deploy.services.dao.interfaces import (
    NetworkConfigDAOInterface,
    VmInstanceDAOInterface,
    VmSoftwareDAOInterface
)
from virtcca_deploy.services.dao.impl import (
    NetworkConfigDAO,
    VmInstanceDAO,
    VmSoftwareDAO
)
from virtcca_deploy.services.dao.registry import (
    DAORegistry,
    get_dao_registry,
    init_dao_registry
)

__all__ = [
    'NetworkConfigDAOInterface',
    'VmInstanceDAOInterface',
    'VmSoftwareDAOInterface',
    'NetworkConfigDAO',
    'VmInstanceDAO',
    'VmSoftwareDAO',
    'DAORegistry',
    'get_dao_registry',
    'init_dao_registry'
]
