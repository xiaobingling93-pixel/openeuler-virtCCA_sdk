#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import json
from virtcca_deploy.services.db_service import db
from virtcca_deploy.services.db_service import ComputeNode


class NodeService:
    @staticmethod
    def create_node(ip, node_data):
        int_fields = [
            ('physical_cpu', node_data.get('physical_cpu')),
            ('logical_cpu', node_data.get('logical_cpu')), 
            ('memory', node_data.get('memory')),
            ('memory_free', node_data.get('memory_free')),
            ('secure_memory', node_data.get('secure_memory')),
            ('secure_memory_free', node_data.get('secure_memory_free'))
        ]

        for field_name, value in int_fields:
            if not isinstance(value, int):
                g_logger.error("%s must be a int", field_name)
                raise ValueError("Must be a non-negative integer.")
            if value < 0:
                g_logger.error("%s value must be non-negative", field_name)
                raise ValueError("Must be a non-negative integer.")

        existing_node = ComputeNode.query.filter_by(ip=ip).first()
        if existing_node:
            existing_node.nodename = node_data.get('hostname')
            existing_node.physical_cpu = node_data.get('physical_cpu')
            existing_node.logical_cpu = node_data.get('logical_cpu')
            existing_node.memory = node_data.get('memory')
            existing_node.memory_free = node_data.get('memory_free')
            existing_node.secure_memory = node_data.get('secure_memory')
            existing_node.secure_memory_free = node_data.get('secure_memory_free')
            existing_node.secure_numa_topology = json.dumps(node_data.get('secure_numa_topology'))
            db.session.commit()

            return existing_node
        else:
            new_node = ComputeNode(ip=ip,
                nodename=node_data.get('hostname'), 
                physical_cpu=node_data.get('physical_cpu'),
                logical_cpu=node_data.get('logical_cpu'),
                memory=node_data.get('memory'),
                memory_free=node_data.get('memory_free'),
                secure_memory=node_data.get('secure_memory'),
                secure_memory_free=node_data.get('secure_memory_free'),
                secure_numa_topology=json.dumps(node_data.get('secure_numa_topology')))

            db.session.add(new_node)
            db.session.commit()
            return new_node

    @staticmethod
    def get_all_nodes():
        return ComputeNode.query.all()

    @staticmethod
    def get_node_by_id(node_id):
        return ComputeNode.query.get(node_id)

    @staticmethod
    def get_node_by_ip(ip):
        return ComputeNode.query.filter_by(ip=ip).first()

    @staticmethod
    def get_secure_numa_by_ip(ip):
        node = ComputeNode.query.filter_by(ip=ip).first()
        return json.loads(node.secure_numa_topology)

    @staticmethod
    def delete_node(node_id):
        node = ComputeNode.query.get(node_id)
        if node:
            db.session.delete(node)
            db.session.commit()
            return True
        return False
