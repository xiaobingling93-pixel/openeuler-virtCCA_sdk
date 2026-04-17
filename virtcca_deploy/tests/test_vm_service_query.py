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
from virtcca_deploy.services.db_service import db, ComputeNode, VmInstance
from virtcca_deploy.services.vm_service import VmService, init_vm_service
from virtcca_deploy.services.task_service import init_task_service
import virtcca_deploy.common.constants as constants


class TestVmServiceQuery:
    def test_query_vm_states_by_nodes(self, app):
        """测试根据节点查询虚拟机状态"""
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)

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

            # 创建两个虚拟机实例
            vm1 = VmInstance(
                vm_id="compute01-1",
                host_ip=node.ip,
                host_name=node.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.10,192.168.1.11"
            )
            vm2 = VmInstance(
                vm_id="compute01-2",
                host_ip=node.ip,
                host_name=node.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.12"
            )
            db.session.add_all([vm1, vm2])
            db.session.commit()

            # 模拟NetworkService和节点服务
            with patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                 patch('virtcca_deploy.services.node_service.NodeService') as mock_node_service:

                # 模拟节点服务返回节点
                mock_node_service.get_nodes_by_ip_list.return_value = ([node], None)

                # 模拟NetworkService的响应
                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_response.json.return_value = {
                    "data": {
                        "compute01-1": "RUNNING",
                        "compute01-2": "SHUTOFF"
                    },
                    "message": ""
                }
                mock_network_instance.query_cvm_state.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # 执行查询
                result, message = vm_service.query_vm_states(nodes=["compute01"], page=1, page_size=10)

                # 验证结果
                assert result is not None
                assert "vm_info" in result
                assert "pagination" in result
                
                vm_info = result["vm_info"]
                assert len(vm_info) == 2
                assert "compute01-1" in vm_info
                assert "compute01-2" in vm_info
                
                # 验证状态信息
                assert vm_info["compute01-1"]["state"] == "RUNNING"
                assert vm_info["compute01-2"]["state"] == "SHUTOFF"
                
                # 验证分页信息
                pagination = result["pagination"]
                assert pagination["page"] == 1
                assert pagination["page_size"] == 10
                assert pagination["entry_num"] == 2

    def test_query_vm_states_by_vm_ids(self, app):
        """测试根据虚拟机ID查询虚拟机状态"""
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)

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

            # 创建两个虚拟机实例
            vm1 = VmInstance(
                vm_id="compute01-1",
                host_ip=node.ip,
                host_name=node.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.10"
            )
            vm2 = VmInstance(
                vm_id="compute01-2",
                host_ip=node.ip,
                host_name=node.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.11"
            )
            db.session.add_all([vm1, vm2])
            db.session.commit()

            # 模拟NetworkService和节点服务
            with patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                 patch('virtcca_deploy.services.node_service.NodeService') as mock_node_service:

                # 模拟节点服务返回节点
                mock_node_service.get_nodes_by_ip_list.return_value = ([node], None)

                # 模拟NetworkService的响应
                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_response.json.return_value = {
                    "data": {
                        "compute01-1": "RUNNING",
                        "compute01-2": "SHUTOFF"
                    },
                    "message": ""
                }
                mock_network_instance.query_cvm_state.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # 执行查询
                result, message = vm_service.query_vm_states(vm_ids=["compute01-1"], page=1, page_size=10)

                # 验证结果
                assert result is not None
                assert "vm_info" in result
                assert "pagination" in result
                
                vm_info = result["vm_info"]
                assert len(vm_info) == 1
                assert "compute01-1" in vm_info
                assert "compute01-2" not in vm_info
                
                # 验证状态信息
                assert vm_info["compute01-1"]["state"] == "RUNNING"

    def test_query_vm_states_pagination(self, app):
        """测试分页查询"""
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)

            # 创建测试节点
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

            # 创建多个虚拟机实例
            vms = []
            for i in range(15):
                vm = VmInstance(
                    vm_id=f"compute01-{i+1}",
                    host_ip=node.ip,
                    host_name=node.nodename,
                    vm_spec_uuid="spec-123",
                    ip_list=f"192.168.1.{i+10}"
                )
                vms.append(vm)
            db.session.add_all(vms)
            db.session.commit()

            # 模拟NetworkService和节点服务
            with patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                 patch('virtcca_deploy.services.node_service.NodeService') as mock_node_service:

                # 模拟节点服务返回节点
                mock_node_service.get_nodes_by_ip_list.return_value = ([node], None)

                # 模拟NetworkService的响应
                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                
                # 构建模拟的VM状态数据
                vm_states = {}
                for i in range(15):
                    vm_states[f"compute01-{i+1}"] = "RUNNING" if i % 2 == 0 else "SHUTOFF"
                
                mock_response.json.return_value = {
                    "data": vm_states,
                    "message": ""
                }
                mock_network_instance.query_cvm_state.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # 测试第一页（10条记录）
                result, message = vm_service.query_vm_states(nodes=["compute01"], page=1, page_size=10)
                
                vm_info = result["vm_info"]
                pagination = result["pagination"]
                
                assert len(vm_info) == 10
                assert pagination["page"] == 1
                assert pagination["page_size"] == 10
                assert pagination["entry_num"] == 15
                
                # 测试第二页（5条记录）
                result, message = vm_service.query_vm_states(nodes=["compute01"], page=2, page_size=10)
                
                vm_info = result["vm_info"]
                pagination = result["pagination"]
                
                assert len(vm_info) == 5
                assert pagination["page"] == 2
                assert pagination["page_size"] == 10
                assert pagination["entry_num"] == 15

    def test_query_vm_states_network_failure(self, app):
        """测试网络请求失败的情况"""
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)

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

            # 模拟NetworkService和节点服务
            with patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                 patch('virtcca_deploy.services.node_service.NodeService') as mock_node_service:

                # 模拟节点服务返回节点
                mock_node_service.get_nodes_by_ip_list.return_value = ([node], None)

                # 模拟NetworkService请求失败
                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
                mock_network_instance.query_cvm_state.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # 执行查询
                result, message = vm_service.query_vm_states(nodes=["compute01"])

                # 验证结果 - 应该返回UNKNOWN状态
                assert result is not None
                assert "vm_info" in result
                
                vm_info = result["vm_info"]
                assert "compute01-1" in vm_info
                assert vm_info["compute01-1"]["state"] == "UNKNOWN"

    def test_query_vm_states_node_not_found(self, app):
        """测试节点不存在的情况"""
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)

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

            # 模拟NetworkService和节点服务
            with patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                 patch('virtcca_deploy.services.node_service.NodeService') as mock_node_service:

                # 模拟节点服务返回空列表（节点不存在）
                mock_node_service.get_nodes_by_ip_list.return_value = ([], None)

                # 执行查询
                result, message = vm_service.query_vm_states(nodes=["compute01"])

                # 验证结果 - 应该返回UNKNOWN状态
                assert result is not None
                assert "vm_info" in result
                
                vm_info = result["vm_info"]
                assert "compute01-1" in vm_info
                assert vm_info["compute01-1"]["state"] == "UNKNOWN"

    def test_query_vm_states_invalid_json_response(self, app):
        """测试无效的JSON响应"""
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)

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

            # 模拟NetworkService和节点服务
            with patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                 patch('virtcca_deploy.services.node_service.NodeService') as mock_node_service:

                # 模拟节点服务返回节点
                mock_node_service.get_nodes_by_ip_list.return_value = ([node], None)

                # 模拟NetworkService返回无效的JSON
                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
                mock_network_instance.query_cvm_state.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # 执行查询
                result, message = vm_service.query_vm_states(nodes=["compute01"])

                # 验证结果 - 应该返回UNKNOWN状态
                assert result is not None
                assert "vm_info" in result
                
                vm_info = result["vm_info"]
                assert "compute01-1" in vm_info
                assert vm_info["compute01-1"]["state"] == "UNKNOWN"

    def test_query_vm_states_no_vms_found(self, app):
        """测试没有虚拟机的情况"""
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)

            # 执行查询 - 没有创建任何虚拟机
            result, message = vm_service.query_vm_states(nodes=["compute01"])

            # 验证结果
            assert result is not None
            assert "vm_info" in result
            assert "pagination" in result
            
            vm_info = result["vm_info"]
            pagination = result["pagination"]
            
            assert len(vm_info) == 0
            assert pagination["entry_num"] == 0
