# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
Data Access Object (DAO) layer for database operations
Provides interface-based access to database models
"""

from virtcca_deploy.services.dao.interfaces import (
    NetworkConfigDAOInterface,
    VmInstanceDAOInterface
)
from virtcca_deploy.services.dao.impl import (
    NetworkConfigDAO,
    VmInstanceDAO
)
from virtcca_deploy.services.dao.registry import (
    DAORegistry,
    get_dao_registry,
    init_dao_registry
)

__all__ = [
    'NetworkConfigDAOInterface',
    'VmInstanceDAOInterface',
    'NetworkConfigDAO',
    'VmInstanceDAO',
    'DAORegistry',
    'get_dao_registry',
    'init_dao_registry'
]
