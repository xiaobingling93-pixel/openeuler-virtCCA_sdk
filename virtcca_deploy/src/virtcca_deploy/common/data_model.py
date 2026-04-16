#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from dataclasses import dataclass, field, asdict
from typing import Any, List, Dict, Optional
import uuid
import json
import virtcca_deploy.common.constants as constants
import virtcca_deploy.common.config as config
from virtcca_deploy.services.db_service import VmDeploySpecModel

g_logger = config.g_logger

DEFAULT_VM_ID = "CVM"
DEFAULT_VM_NUM = 1
DEFAULT_MEMORY = 8192
DEFAULT_CORE_NUM = 4
DEFAULT_VLAN_ID = 0
DEFAULT_GATEWAY_IP = "192.168.122.1"
DEFAULT_NET_PF_NUM = 0
DEFAULT_NET_VF_NUM = 0
DEFAULT_DISK_SIZE = 0

@dataclass
class VmDeploySpec:
    max_vm_num: int = DEFAULT_VM_NUM
    memory: int = DEFAULT_MEMORY
    core_num: int = DEFAULT_CORE_NUM
    vlan_id: int = DEFAULT_VLAN_ID
    gateway_ip: str = DEFAULT_GATEWAY_IP
    net_pf_num: int = DEFAULT_NET_PF_NUM
    net_vf_num: int = DEFAULT_NET_VF_NUM
    disk_size: int = DEFAULT_DISK_SIZE

    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))

    def is_valid(self) -> bool:
        int_fields = [
            ('max_vm_num', self.max_vm_num),
            ('memory', self.memory), 
            ('core_num', self.core_num),
            ('vlan_id', self.vlan_id),
            ('net_pf_num', self.net_pf_num),
            ('net_vf_num', self.net_vf_num)
        ]

        for field_name, value in int_fields:
            if not isinstance(value, int):
                g_logger.error("%s must be a int", field_name)
                return False

        if not (1 <= self.max_vm_num <= constants.MAX_CVM_NUM_PER_NODE):
            return False
        if not (constants.MIN_CVM_MEM <= self.memory <= constants.MAX_CVM_MEM):
            return False
        if not (1 <= self.core_num <= constants.MAX_CVM_CORE):
            return False
        if self.vlan_id < 0:
            return False
        # vf and pf cannot be used at the same time.
        if self.net_pf_num != 0 and self.net_vf_num != 0:
            return False
        return True

    def to_db_model(self):
        return VmDeploySpecModel(
            uuid=self.uuid,
            max_vm_num=self.max_vm_num,
            memory=self.memory,
            core_num=self.core_num,
            vlan_id=self.vlan_id,
            net_pf_num=self.net_pf_num,
            net_vf_num=self.net_vf_num,
            gateway_ip=self.gateway_ip,
            disk_size=self.disk_size
        )

    @classmethod
    def from_db_model(cls, model):
        return cls(
            uuid=model.uuid,
            max_vm_num=model.max_vm_num,
            memory=model.memory,
            core_num=model.core_num,
            vlan_id=model.vlan_id,
            net_pf_num=model.net_pf_num,
            net_vf_num=model.net_vf_num,
            gateway_ip=model.gateway_ip,
            disk_size=model.disk_size
        )

    def to_dict(self) -> Dict:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())

@dataclass
class VmDeploySpecInternal:
    vm_id_list: List[str] = field(default_factory=list)
    vm_spec: VmDeploySpec = field(default_factory=VmDeploySpec)
    vm_ip_dict: dict = field(default_factory=dict)

    def is_valid(self) -> bool:
        if not self.vm_spec.is_valid():
            return False

        if not self.vm_id_list or len(self.vm_id_list) == 0:
                    return False

        for vm_id in self.vm_id_list:
            if not (1 <= len(vm_id) <= constants.MAX_CVM_ID_LENGTH):
                return False

        return True


    @classmethod
    def from_db_model(cls, model):
        return VmDeploySpecInternal(vm_spec=VmDeploySpec.from_db_model(model))

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['vm_spec'] = self.vm_spec.to_dict()
        return result
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())

@dataclass
class ApiResponse:
    message: str = ""
    data: Any = None

    def to_dict(self):
        return {
            'message': self.message,
            'data': self.data
        }

@dataclass
class NetAllocReq:
    vm_id_list: List[str]
    vlan_id: int
    pf_num: int
    vf_num: int
    node_ip: str

@dataclass
class NetReleaseReq:
    vm_id_list: List[str]

    vlan_id: Optional[int] = None
    node_ip: Optional[str] = None

@dataclass
class NetAllocResp:
    success: bool
    vm_ip_map: Dict[str, List[str]] = field(default_factory=dict)
    failed_vms: Dict[str, str] = field(default_factory=dict)
    message: Optional[str] = None

@dataclass
class NetReleaseResp:
    success: bool
    released_vms: List[str] = field(default_factory=list)
    failed_vms: Dict[str, str] = field(default_factory=dict)
    message: Optional[str] = None


@dataclass
class DeviceAllocReq:
    vm_id: str
    pf_num: int
    vf_num: int
    numa_node: Optional[int] = None

@dataclass
class DeviceAllocResp:
    success: bool
    device_list: List[str]

@dataclass
class DeviceReleaseReq:
    vm_id: str

@dataclass
class DeviceReleaseResp:
    success: bool