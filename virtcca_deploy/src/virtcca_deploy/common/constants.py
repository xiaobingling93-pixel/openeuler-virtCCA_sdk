#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from typing import Dict, List
import json

class VirtCcaError(Exception):
    """基础异常类"""
    def __init__(self, message: str, cause: Exception = None):
        super().__init__(message)
        self.cause = cause
        self.message = message

    def __str__(self):
        if self.cause:
            return f"{self.message} (caused by: {self.cause})"
        return self.message


class VmServiceError(VirtCcaError):
    """VM 服务异常"""
    pass


class DeploymentError(VirtCcaError):
    """VM 部署异常"""
    pass


class UndeploymentError(VirtCcaError):
    """VM 卸载异常"""
    pass


class NodeError(VirtCcaError):
    """节点操作异常"""
    pass


class DeviceError(VirtCcaError):
    """设备操作异常"""
    pass


class TaskError(VirtCcaError):
    """任务操作异常"""
    pass


class ValidationError(VirtCcaError):
    """参数验证异常"""
    pass

# Runtime config
DEFAULT_CONFIG_PATH = "/etc/virtcca_deploy/virtcca_deploy.conf"
COMPUTE_PORT = 5000
MANAGER_PORT = 5001
MANAGER_DB_PATH = "/var/lib/virtcca_deploy/"
MANAGER_DB = "sqlite:////var/lib/virtcca_deploy/virtcca_deploy_manager.db"
MANAGER_LOG_NAME = "virtcca_deploy_manager.log"
COMPUTE_LOG_NAME = "virtcca_deploy_compute.log"
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
ROUTE_VM_STOP_INTERNAL = "/api/v1/internal/vm/stop"
ROUTE_VM_START_INTERNAL = "/api/v1/internal/vm/start"

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
ROUTE_VM_STOP = "/api/v1/vm/stop"
ROUTE_VM_START = "/api/v1/vm/start"
ROUTE_VM_TASKS = "/api/v1/vm/tasks/"

# restful methods
POST = "POST"
GET = "GET"
DELETE = "DELETE"

# Cvm spec limitations
MAX_CVM_NUM_PER_NODE = 8
MIN_CVM_MEM = 1024
MAX_CVM_MEM = 1024 * 512
MAX_CVM_CORE = 32
MAX_CVM_ID_LENGTH = 60
MAX_NET_PF_NUM = 8
MAX_NET_VF_NUM = 8
MIN_DISK_SIZE_GB = 1
MAX_DISK_SIZE_GB = 1024


# Auth routes
ROUTE_AUTH_LOGIN = "/api/v1/auth/login"
ROUTE_AUTH_LOGOUT = "/api/v1/auth/logout"

# Auth defaults
DEFAULT_JWT_EXPIRATION_MINUTES = 720
DEFAULT_MAX_LOGIN_ATTEMPTS = 5
DEFAULT_LOCKOUT_DURATION_MINUTES = 1
ROOT_USERNAME = "root"

# JWT secret key file path
JWT_SECRET_KEY_FILE = "/etc/virtcca_deploy/jwt_secret.key"

#Task types
TASK_TYPE_VM_CREATE = "vm-create"
TASK_TYPE_VM_DELETE = "vm-delete"
TASK_TYPE_VM_STOP = "vm-stop"
TASK_TYPE_VM_START = "vm-start"

class DeviceTypeConfig:
    """PCI 设备类型配置"""
    HUAWEI_VENDOR_ID = 0x19e5
    HI1822_PF_DEVICE_ID = 0x0222
    HI1822_VF_DEVICE_ID = 0x375f
    HI1822_DEVICE_IDS = {HI1822_PF_DEVICE_ID, HI1822_VF_DEVICE_ID}

    DEVICE_TYPE_NET_PF = "NET_PF"
    DEVICE_TYPE_NET_VF = "NET_VF"
    DEVICE_TYPE_PCI= "PCI"

    PCI_VENDOR_ID_MAX = 0xFFFF
    PCI_DEVICE_ID_MAX = 0xFFFF

    SYSFS_PCI_DEVICES = "/sys/bus/pci/devices"


class PathConfig:
    """路径配置"""
    CONF_DIR = "/etc/virtcca_deploy"
    DATA_DIR = "/var/lib/virtcca_deploy"
    LOG_DIR = "/var/log/virtcca_deploy"

    CONFIG_FILE = f"{CONF_DIR}/virtcca_deploy.conf"
    CERT_DIR = f"{CONF_DIR}/cert"
    BASE_QCOW2 = f"{CONF_DIR}/base.qcow2"
    TEMPLATE_XML = f"{CONF_DIR}/cvm_template.xml"
    IFCTL_TEMPLATE = f"{CONF_DIR}/ifcfg-template"
    XML_DIR = f"{CONF_DIR}/xml"
    SCRIPT_DIR = f"{CONF_DIR}/script"
    JWT_SECRET_KEY_FILE = f"{CONF_DIR}/jwt_secret.key"

    UPLOAD_DIR = f"{DATA_DIR}/upload"
    MANAGER_SOFTWARE_PATH = f"{UPLOAD_DIR}/manager"
    COMPUTE_SOFTWARE_PATH = f"{UPLOAD_DIR}/compute"
    QCOW2_DIR = f"{DATA_DIR}/qcow2"
    MOUNT_PATH = f"{QCOW2_DIR}/mnt"
    MANAGER_DB = f"sqlite:///{DATA_DIR}/virtcca_deploy_manager.db"
    COMPUTE_DB = f"sqlite:///{DATA_DIR}/virtcca_deploy_compute.db"

    LIBVIRT_QEMU_LOG = "/var/log/libvirt/qemu"
    CVM_COLLECT_LOG = f"{LOG_DIR}/compute"


class NetworkConfig:
    """网络与服务配置"""
    COMPUTE_PORT = 5000
    MANAGER_PORT = 5001
    BIND_ADDRESS = "0.0.0.0"
    MANAGER_BIND = f"{BIND_ADDRESS}:{MANAGER_PORT}"
    COMPUTE_BIND = f"{BIND_ADDRESS}:{COMPUTE_PORT}"
    LIBVIRT_URI = "qemu:///system"


class DefaultVmConfig:
    """VM 默认配置"""
    DEFAULT_VM_NUM = 1
    MAX_VM_NUM = 8
    MIN_MEM = 1024  # MiB
    MAX_MEM = 1024 * 512  # MiB
    DEFAULT_MEM = 8192
    DEFAULT_CORE = 4
    MAX_CORE = 32
    MAX_ID_LENGTH = 60
    OS_VERSION = "openEuler-2403LTS-SP2"


class ServerConfig:
    """服务进程配置"""
    WORKERS = 1
    TIMEOUT = 300
    MANAGER_LOG = "virtcca_deploy_manager.log"
    COMPUTE_LOG = "virtcca_deploy_compute.log"


class NetResourceConfig:
    """网络资源配置"""
    BASE_IP = "192.168.1.0"
    IP_COUNT = 254


class VmStateParser:
    """解析 VM 状态数据"""

    @staticmethod
    def parse(raw_data) -> Dict[str, str]:
        """
        解析 VM 状态原始数据
        :param raw_data: 原始数据（dict 或 JSON 字符串）
        :return: VM ID -> 状态 的字典
        :raises ValidationError: 当数据类型不符或 JSON 解析失败时
        """
        import json
        if isinstance(raw_data, dict):
            return raw_data
        if isinstance(raw_data, str):
            try:
                return json.loads(raw_data)
            except json.JSONDecodeError as e:
                raise ValidationError(
                    f"Invalid VM state JSON: {raw_data[:100]}"
                ) from e
        raise ValidationError(f"Unexpected VM state type: {type(raw_data)}")


class VmStateBuilder:
    """统一构建 VM 状态信息字典"""

    @staticmethod
    def from_vm_instance(vm: 'VmInstance', state: str = "UNKNOWN") -> Dict:
        """
        从 VmInstance 数据库记录构建状态信息字典
        :param vm: VmInstance 数据库对象
        :param state: VM 运行状态（如 SHUTOFF/RUNNING）
        :return: 状态信息字典
        """
        return {
            "state": state,
            "create_at": vm.created_at.isoformat() + "Z" if vm.created_at else "",
            "os": vm.os_version or "Unknown",
            "iface_list": json.loads(vm.iface_list) if vm.iface_list else [],
            "mem_used": 0.0,
            "host_ip": vm.host_ip
        }

    @staticmethod
    def unknown_state(vm: 'VmInstance') -> Dict:
        """查询失败时的降级状态"""
        return VmStateBuilder.from_vm_instance(vm, state="UNKNOWN")


class TaskResultBuilder:
    """统一构建 Task 参数"""

    @staticmethod
    def build_vm_result(success_vms: List, fail_vms: List, total_vms: List) -> Dict:
        """构建 VM 操作结果参数"""
        return {
            "success_vms": success_vms,
            "fail_vms": fail_vms,
            "total_vms": total_vms
        }

    @staticmethod
    def calc_status(fail_vms: List) -> str:
        """根据失败列表计算任务状态"""
        return "success" if not fail_vms else "failed"