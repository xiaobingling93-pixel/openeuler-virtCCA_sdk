#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from enum import Enum

# Runtime config
DEFAULT_CONFIG_PATH = "/etc/virtcca_deploy/virtcca_deploy.conf"
COMPUTE_PORT = 5000
MANAGER_PORT = 5001
MANAGER_DB_PATH = "/var/lib/virtcca_deploy/"
MANAGER_DB = "sqlite:////var/lib/virtcca_deploy/virtcca_deploy_manager.db"
MANAGER_LOG_NEME = "virtcca_deploy_manager.log"
COMPUTE_LOG_NEME = "virtcca_deploy_compute.log"

# Cvm template
CVM_TEMPLATE_XML = '/etc/virtcca_deploy/cvm_template.xml'

# Internal interface route
ROUTE_NODE_REGISTRY_INTERNAL = "/virtcca/internal/node/register"
ROUTE_NODE_INFO_INTERNAL = "/virtcca/internal/host/node-info"
ROUTE_SET_NODE_DEPLOY_CONFIG_INTERNAL = "/virtcca/internal/vm/node-info"

ROUTE_VM_DEPLOY_INTERNAL = "/virtcca/internal/vm/deploy"
ROUTE_VM_STATE_INTERNAL = "/virtcca/internal/vm/state"

# External interface route
ROUTE_HELLO = "/"
ROUTE_NODE_INFO = "/virtcca/host/node-info"
ROUTE_SET_NODE_DEPLOY_CONFIG = "/virtcca/vm/node-info"
ROUTE_VM_DEPLOY = "/virtcca/vm/deploy"

# restful methods
POST = "POST"
GET = "GET"

# Cvm spec limitations
MAX_CVM_NUM_PER_NODE = 1
MIN_CVM_MEM = 1024
MAX_CVM_MEM = 1024 * 512
MAX_CVM_CORE = 32
MAX_CVM_ID_LENGTH = 60


# HTTP status codes
class HTTPStatusCodes:
    OK = 200
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    INTERNAL_SERVER_ERROR = 500


# operation codes
class OperationCodes(Enum):
    SUCCESS = 0
    FAILED = 1
    COMPUTE_NODE_FAILED = 2
    IP_FORBIDDEN = 3
    INTERNAL_EXCEPTION = 3