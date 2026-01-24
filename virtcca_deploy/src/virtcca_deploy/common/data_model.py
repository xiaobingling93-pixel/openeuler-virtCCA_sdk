#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from dataclasses import dataclass, field
from typing import Any
import virtcca_deploy.common.constants as constants
from virtcca_deploy.common.constants import OperationCodes
import virtcca_deploy.common.config as config

g_logger = config.g_logger

DEFAULT_VM_ID = "CVM"
DEFAULT_VM_NUM = 1
DEFAULT_MEMORY = 8192
DEFAULT_CORE_NUM = 4
DEFAULT_VLAN_ID = 0
DEFAULT_NET_PF_NUM = 0
DEFAULT_NET_VF_NUM = 0


@dataclass
class VmDeploySpec:
    vm_num: int = DEFAULT_VM_NUM
    memory: int = DEFAULT_MEMORY
    core_num: int = DEFAULT_CORE_NUM
    vlan_id: int = DEFAULT_VLAN_ID
    net_pf_num: int = DEFAULT_NET_PF_NUM
    net_vf_num: int = DEFAULT_NET_VF_NUM

    def is_valid(self) -> bool:
        int_fields = [
            ('vm_num', self.vm_num),
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

        if not (1 <= self.vm_num <= constants.MAX_CVM_NUM_PER_NODE):
            return False
        if not (constants.MIN_CVM_MEM <= self.memory <= constants.MAX_CVM_MEM):
            return False
        if not (1 <= self.core_num <= constants.MAX_CVM_CORE):
            return False
        return True


@dataclass
class VmDeploySpecInternal:
    vm_id: str = DEFAULT_VM_ID
    vm_spec: VmDeploySpec = field(default_factory=VmDeploySpec)

    def is_valid(self) -> bool:
        if not self.vm_spec.is_valid():
            return False
        if not (1 <= len(self.vm_id) <= constants.MAX_CVM_ID_LENGTH):
            return False

        return True


@dataclass
class ApiResponse:
    status: int = OperationCodes.SUCCESS
    message: str = ""
    data: Any = None

    def to_dict(self):
        return {
            'status': self.status.value,
            'message': self.message,
            'data': self.data
        }
