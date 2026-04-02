#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from flask_sqlalchemy import SQLAlchemy
from flask import Flask

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
    vm_num = db.Column(db.Integer, nullable=False)
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
            "<uuid: {}, vm_num: {}, memory: {}, core_num: {}, vlan_id: {}, "\
            "gateway_ip: {}, net_pf_num: {}, net_vf_num: {}, disk_size: {}, is_default: {}>"
            ).format(self.uuid, self.vm_num, self.memory, self.core_num, self.vlan_id,
                    self.gateway_ip, self.net_pf_num, self.net_vf_num, self.disk_size, self.is_default)
