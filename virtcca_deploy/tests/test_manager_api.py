#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import os
import sys
from http import HTTPStatus

# 确保项目src目录在sys.path中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(PROJECT_ROOT, 'src')
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

import json
import pytest
from unittest.mock import patch, MagicMock
from flask.testing import FlaskClient
from virtcca_deploy.services.db_service import db, ComputeNode, VmInstance
from virtcca_deploy.services.vm_service import VmService, init_vm_service
from virtcca_deploy.services.task_service import init_task_service
import virtcca_deploy.common.constants as constants


class TestManagerApi:
    def test_get_cvm_state_by_nodes(self, authenticated_client, app):
        """测试通过节点查询虚拟机状态的API"""
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)
            init_vm_service(None, mock_vlan_pool_manager)

            # 创建测试节点和虚拟机
            node = ComputeNode(
                nodename="compute01",
                ip="192.168.1.100",
                physical_cpu=8,
                memory=16384,
                memory_free=8192,
                secure_memory=4096,
                secure_memory_free=4096,
                secure_numa_topology="{}"
            )
            db.session.add(node)

            vm = VmInstance(
                vm_id="compute01-1",
                host_ip=node.ip,
                host_name=node.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.10"
            )
            db.session.add(vm)
            db.session.commit()

            # 模拟vm_service的query_vm_states方法
            mock_result = {
                "vm_info": {
                    "compute01-1": {
                        "state": "RUNNING",
                        "create_at": "2023-01-01T00:00:00Z",
                        "os": "Unknown",
                        "ip_list": ["192.168.1.10"],
                        "mem_used": 0.0,
                        "host_ip": "192.168.1.100"
                    }
                },
                "pagination": {
                    "page": 1,
                    "page_size": 10,
                    "entry_num": 1
                }
            }
            
            with patch('virtcca_deploy.manager.manager.vm_service.get_vm_service') as mock_get_vm_service:
                mock_vm_service_instance = MagicMock()
                mock_vm_service_instance.query_vm_states.return_value = (mock_result, "Success")
                mock_get_vm_service.return_value = mock_vm_service_instance

                # 发送请求
                response = authenticated_client.post(
                    constants.ROUTE_VM_STATE,
                    content_type='application/json',
                    data=json.dumps({
                        "nodes": ["compute01"],
                        "vm_ids": [],
                        "pagination": {"page": 1, "page_size": 10}
                    })
                )

                # 验证响应
                assert response.status_code == HTTPStatus.OK
                response_data = response.get_json()
                assert response_data["message"] == "Success"
                assert response_data["data"] == mock_result
                
                # 验证vm_service的方法被正确调用
                mock_vm_service_instance.query_vm_states.assert_called_once_with(
                    ["compute01"], [], 1, 10
                )

    def test_get_cvm_state_by_vm_ids(self, authenticated_client, app):
        """测试通过虚拟机ID查询虚拟机状态的API"""
        
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)
            init_vm_service(None, mock_vlan_pool_manager)

            # 模拟vm_service的query_vm_states方法
            mock_result = {
                "vm_info": {
                    "compute01-1": {
                        "state": "RUNNING",
                        "create_at": "2023-01-01T00:00:00Z",
                        "os": "Unknown",
                        "ip_list": ["192.168.1.10"],
                        "mem_used": 0.0,
                        "host_ip": "192.168.1.100"
                    }
                },
                "pagination": {
                    "page": 1,
                    "page_size": 10,
                    "entry_num": 1
                }
            }
            
            with patch('virtcca_deploy.manager.manager.vm_service.get_vm_service') as mock_get_vm_service:
                mock_vm_service_instance = MagicMock()
                mock_vm_service_instance.query_vm_states.return_value = (mock_result, "Success")
                mock_get_vm_service.return_value = mock_vm_service_instance

                # 发送请求
                response = authenticated_client.post(
                    constants.ROUTE_VM_STATE,
                    content_type='application/json',
                    data=json.dumps({
                        "nodes": [],
                        "vm_ids": ["compute01-1"],
                        "pagination": {"page": 1, "page_size": 10}
                    })
                )

                # 验证响应
                assert response.status_code == HTTPStatus.OK
                response_data = response.get_json()
                assert response_data["message"] == "Success"
                assert response_data["data"] == mock_result
                
                # 验证vm_service的方法被正确调用
                mock_vm_service_instance.query_vm_states.assert_called_once_with(
                    [], ["compute01-1"], 1, 10
                )

    def test_get_cvm_state_nodes_and_vm_ids_both_non_empty(self, authenticated_client, app):
        """测试nodes和vm_ids同时非空的情况"""
        # 发送请求
        response = authenticated_client.post(
            constants.ROUTE_VM_STATE,
            content_type='application/json',
            data=json.dumps({
                "nodes": ["compute01"],
                "vm_ids": ["compute01-1"],
                "pagination": {"page": 1, "page_size": 10}
            })
        )

        # 验证响应
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = response.get_json()
        assert response_data["message"] == "Nodes and vm_ids cannot be non-empty at the same time"

    def test_get_cvm_state_invalid_pagination(self, authenticated_client, app):
        """测试无效的分页参数"""
        # 发送请求 - 页码为0
        response = authenticated_client.post(
            constants.ROUTE_VM_STATE,
            content_type='application/json',
            data=json.dumps({
                "nodes": ["compute01"],
                "vm_ids": [],
                "pagination": {"page": 0, "page_size": 10}
            })
        )

        # 验证响应
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = response.get_json()
        assert "Page must be >= 1." in response_data["message"]
        
        # 发送请求 - 页大小超过100
        response = authenticated_client.post(
            constants.ROUTE_VM_STATE,
            content_type='application/json',
            data=json.dumps({
                "nodes": ["compute01"],
                "vm_ids": [],
                "pagination": {"page": 1, "page_size": 200}
            })
        )

        # 验证响应
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = response.get_json()
        assert "Page size cannot exceed 100." in response_data["message"]

    def test_get_cvm_state_invalid_parameter_types(self, authenticated_client, app):
        """测试无效的参数类型"""
        # 发送请求 - nodes不是列表
        response = authenticated_client.post(
            constants.ROUTE_VM_STATE,
            content_type='application/json',
            data=json.dumps({
                "nodes": "compute01",  # 应该是列表
                "vm_ids": [],
                "pagination": {"page": 1, "page_size": 10}
            })
        )

        # 验证响应
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = response.get_json()
        assert "Invalid nodes parameter, expected list." in response_data["message"]
        
        # 发送请求 - vm_ids不是列表
        response = authenticated_client.post(
            constants.ROUTE_VM_STATE,
            content_type='application/json',
            data=json.dumps({
                "nodes": [],
                "vm_ids": "compute01-1",  # 应该是列表
                "pagination": {"page": 1, "page_size": 10}
            })
        )

        # 验证响应
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = response.get_json()
        assert "Invalid vm_ids parameter, expected list." in response_data["message"]
        
        # 发送请求 - 分页参数不是整数
        response = authenticated_client.post(
            constants.ROUTE_VM_STATE,
            content_type='application/json',
            data=json.dumps({
                "nodes": ["compute01"],
                "vm_ids": [],
                "pagination": {"page": "one", "page_size": "ten"}  # 应该是整数
            })
        )

        # 验证响应
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = response.get_json()
        assert "Pagination parameters must be integers." in response_data["message"]

    def test_get_cvm_state_vm_service_error(self, authenticated_client, app):
        """测试vm_service返回错误的情况"""
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)
            init_vm_service(None, mock_vlan_pool_manager)

            # 模拟vm_service的query_vm_states方法返回错误
            with patch('virtcca_deploy.manager.manager.vm_service.get_vm_service') as mock_get_vm_service:
                mock_vm_service_instance = MagicMock()
                mock_vm_service_instance.query_vm_states.return_value = ({}, "Service error")
                mock_get_vm_service.return_value = mock_vm_service_instance

                # 发送请求
                response = authenticated_client.post(
                    constants.ROUTE_VM_STATE,
                    content_type='application/json',
                    data=json.dumps({
                        "nodes": ["compute01"],
                        "vm_ids": [],
                        "pagination": {"page": 1, "page_size": 10}
                    })
                )

                # 验证响应
                assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
                response_data = response.get_json()
                assert response_data["message"] == "Service error"
