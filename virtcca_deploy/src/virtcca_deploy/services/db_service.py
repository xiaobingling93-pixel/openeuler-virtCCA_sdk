#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from flask_sqlalchemy import SQLAlchemy
from flask import Flask
import json

db = SQLAlchemy()


class DbService:
    def __init__(self, app: Flask):
        self.db = db

    def get_session(self):
        return self.db.session


class ComputeNode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nodename = db.Column(db.String(80), unique=True, nullable=False)
    ip = db.Column(db.String(39), unique=True, nullable=False)
    physical_cpu = db.Column(db.Integer, unique=False, nullable=False)
    memory = db.Column(db.Integer, unique=False, nullable=False)
    memory_free = db.Column(db.Integer, unique=False, nullable=False)
    secure_memory = db.Column(db.Integer, unique=False, nullable=True)
    secure_memory_free = db.Column(db.Integer, unique=False, nullable=True)
    secure_numa_topology = db.Column(db.Text, unique=False, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return (
            "<nodename: {}, ip: {}, physical_cpu: {}, memory: {},secure_memory: {}>"
            ).format(self.nodename, self.ip, self.physical_cpu, self.memory, self.secure_memory)


class VmDeploySpecModel(db.Model):
    uuid = db.Column(db.String(36), primary_key=True)
    max_vm_num = db.Column(db.Integer, nullable=False)
    memory = db.Column(db.Integer, nullable=False)
    core_num = db.Column(db.Integer, nullable=False)
    vlan_id = db.Column(db.Integer, nullable=False)
    gateway_ip = db.Column(db.String, nullable=False)
    net_pf_num = db.Column(db.Integer, nullable=False)
    net_vf_num = db.Column(db.Integer, nullable=False)
    disk_size = db.Column(db.Integer, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return (
            "<uuid: {}, max_vm_num: {}, memory: {}, core_num: {}, vlan_id: {}, "
            "gateway_ip: {}, net_pf_num: {}, net_vf_num: {}, disk_size: {}, is_default: {}>"
            ).format(self.uuid, self.max_vm_num, self.memory, self.core_num, self.vlan_id,
                    self.gateway_ip, self.net_pf_num, self.net_vf_num, self.disk_size, self.is_default)


class VmInstance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vm_id = db.Column(db.String(80), nullable=False)
    host_ip = db.Column(db.String(39), nullable=False)
    host_name = db.Column(db.String(80), nullable=False)
    vm_spec_uuid = db.Column(db.String(36), db.ForeignKey('vm_deploy_spec_model.uuid'), nullable=False)
    ip_list = db.Column(db.Text, nullable=True)  # 存储VM的IP列表，使用逗号分隔
    os_version = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return (
            "<vm_id: {}, host_ip: {}, host_name: {}, "
            "vm_spec_uuid: {}, ip_list: {}, os_version: {}>"
            ).format(self.vm_id, self.host_ip, self.host_name, 
                    self.vm_spec_uuid, self.ip_list, self.os_version)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(36), unique=True, nullable=False)
    task_type = db.Column(db.String(20), nullable=False)  # vm-create/vm-delete
    task_params = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False)  # created/running/success/failed
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())
    completed_at = db.Column(db.DateTime, nullable=True)

    def set_task_params(self, params):
        if isinstance(params, dict):
            if "success_vms" not in params:
                params["success_vms"] = []
            if "fail_vms" not in params:
                params["fail_vms"] = []
            if "total_vms" not in params:
                params["total_vms"] = []
            
            self.task_params = json.dumps(params)
        else:
            self.task_params = json.dumps({
                "success_vms": [],
                "fail_vms": [],
                "total_vms": []
            })

    def get_task_params(self):
        if self.task_params:
            try:
                return json.loads(self.task_params)
            except json.JSONDecodeError:
                return {
                    "success_vms": [],
                    "fail_vms": [],
                    "total_vms": []
                }
        return {
            "success_vms": [],
            "fail_vms": [],
            "total_vms": []
        }

    def __repr__(self):
        return "<Task(task_id: {}, task_type: {}, task_params: {}, status: {})>".format(
            self.task_id,
            self.task_type,
            self.get_task_params(),
            self.status,
        )


class VmSoftware(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(128), unique=True, nullable=False)
    file_hash = db.Column(db.String(64), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    file_type = db.Column(db.String(20), nullable=True)
    signature = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return "<VmSoftware(file_name: {}, file_hash: {}, file_size: {}, file_type: {})>".format(
            self.file_name,
            self.file_hash,
            self.file_size,
            self.file_type
        )
