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
BASE_QCOW2 = "/etc/virtcca_deploy/base.qcow2"
LIBVIRT_QEMU_LOG_PATH = "/var/log/libvirt/qemu/"
CVM_COLLECT_LOG_PATH = "/var/log/virtcca_deploy/compute"
CVM_MANAGER_SOFTWARE_PATH = "/var/lib/virtcca_deploy/upload/manager"
CVM_COMPUTE_SOFTWARE_PATH = "/var/lib/virtcca_deploy/upload/compute"
MOUNT_PATH = "/var/lib/virtcca_deploy/qcow2/mnt"
GUEST_SCRIPT_PATH = "/etc/virtcca_deploy/script"
# Cvm template
CVM_TEMPLATE_XML = '/etc/virtcca_deploy/cvm_template.xml'

# Internal interface route
ROUTE_NODE_REGISTRY_INTERNAL = "/api/v1/internal/host/register"
ROUTE_NODE_INFO_INTERNAL = "/api/v1/internal/host/node-info"
ROUTE_VM_DEPLOY_INTERNAL = "/api/v1/internal/vm/deploy"
ROUTE_VM_UNDEPLOY_INTERNAL = "/api/v1/internal/vm/undeploy"
ROUTE_VM_STATE_INTERNAL = "/api/v1/internal/vm/state"
ROUTE_VM_LOG_COLLECT_INTERNAL = "/api/v1/internal/vm/logs/<vm_id>"
ROUTE_VM_SOFTWARE_INTERNAL = "/api/v1/internal/vm/software"

# External interface route
ROUTE_HELLO = "/"
ROUTE_NODE_INFO = "/api/v1/host/node-info"
ROUTE_SET_NODE_DEPLOY_CONFIG = "/api/v1/vm/deploy-config"
ROUTE_GET_NODE_DEPLOY_CONFIG = "/api/v1/vm/deploy-config"
ROUTE_VM_DEPLOY = "/api/v1/vm/deploy"
ROUTE_VM_UNDEPLOY = "/api/v1/vm/undeploy"
ROUTE_VM_STATE = "/api/v1/vm/state"
ROUTE_VM_LOG_COLLECT = "/api/v1/vm/logs/"
ROUTE_VM_SOFTWARE = "/api/v1/vm/software"

# restful methods
POST = "POST"
GET = "GET"

# Cvm spec limitations
MAX_CVM_NUM_PER_NODE = 8
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
    TOO_MANY_REQUESTS = 429
    INTERNAL_SERVER_ERROR = 500


# operation codes
class OperationCodes(Enum):
    SUCCESS = 0
    FAILED = 1
    COMPUTE_NODE_FAILED = 2
    IP_FORBIDDEN = 3
    INTERNAL_EXCEPTION = 3


# Auth routes
ROUTE_AUTH_LOGIN = "/api/v1/auth/login"
ROUTE_AUTH_LOGOUT = "/api/v1/auth/logout"

# Auth defaults
DEFAULT_JWT_EXPIRATION_MINUTES = 30
DEFAULT_MAX_LOGIN_ATTEMPTS = 5
DEFAULT_LOCKOUT_DURATION_MINUTES = 15
ROOT_USERNAME = "root"

# JWT secret key file path
JWT_SECRET_KEY_FILE = "/etc/virtcca_deploy/jwt_secret.key"