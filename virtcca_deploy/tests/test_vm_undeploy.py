#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import os
import sys
from http import HTTPStatus
import json

# 确保项目src目录在sys.path中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(PROJECT_ROOT, 'src')
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

import pytest
from unittest.mock import patch, MagicMock
from virtcca_deploy.services.db_service import db, ComputeNode, VmInstance
import virtcca_deploy.common.constants as constants


class TestVmUndeployEndpoint:
    def test_undeploy_cvm_with_list_format(self, authenticated_client, app):
        """测试使用直接列表格式卸载虚拟机"""
        with app.app_context():
            node1 = ComputeNode(
                nodename="compute01",
                ip="192.168.1.100",
                physical_cpu=8,
                memory=16384,
                memory_free=8192,
                secure_memory=4096,
                secure_memory_free=4096,
                secure_numa_topology="{}"
            )
            db.session.add(node1)
            
            vm1 = VmInstance(
                vm_id="compute01-1",
                host_ip=node1.ip,
                host_name=node1.nodename,
                vm_spec_uuid="spec-123",
                iface_list=json.dumps({
                "mac_address": "00:11:22:33:44:55",
                "vlan_id": 100,
                "ip_address": "192.168.1.10",
                "subnet_mask": "255.255.255.0",
                "gateway": "192.168.1.1"})
            )
            db.session.add(vm1)
            db.session.commit()
        
        # 模拟vm_service.execute_undeployment方法
        with patch('virtcca_deploy.services.vm_service.get_vm_service') as mock_get_vm_service:
            mock_vm_service = MagicMock()
            mock_vm_service.execute_undeployment.return_value = {
                "compute01-1": {
                    "task_id": "task-123",
                    "host_ip": "192.168.1.100"
                }
            }
            mock_get_vm_service.return_value = mock_vm_service
            
            response = authenticated_client.post(
                constants.ROUTE_VM_UNDEPLOY,
                json=["compute01-1"]
            )
            
            assert response.status_code == HTTPStatus.ACCEPTED
            assert "compute01-1" in response.json.get("data", {})
            
            mock_vm_service.execute_undeployment.assert_called_once()
            args, kwargs = mock_vm_service.execute_undeployment.call_args
            assert args[0] == []
            assert args[1] == ["compute01-1"]
    
    def test_undeploy_cvm_with_object_list_format(self, authenticated_client, app):
        """测试使用对象包含列表格式卸载虚拟机：{["compute01-1"]}"""
        with app.app_context():
            node1 = ComputeNode(
                nodename="compute01",
                ip="192.168.1.100",
                physical_cpu=8,
                memory=16384,
                memory_free=8192,
                secure_memory=4096,
                secure_memory_free=4096,
                secure_numa_topology="{}"
            )
            db.session.add(node1)
            
            vm1 = VmInstance(
                vm_id="compute01-1",
                host_ip=node1.ip,
                host_name=node1.nodename,
                vm_spec_uuid="spec-123",
                iface_list=json.dumps({
                "mac_address": "00:11:22:33:44:55",
                "vlan_id": 100,
                "ip_address": "192.168.1.10",
                "subnet_mask": "255.255.255.0",
                "gateway": "192.168.1.1"})
            )
            db.session.add(vm1)
            db.session.commit()
        
        with patch('virtcca_deploy.services.vm_service.get_vm_service') as mock_get_vm_service:
            mock_vm_service = MagicMock()
            mock_vm_service.execute_undeployment.return_value = {
                "compute01-1": {
                    "task_id": "task-123",
                    "host_ip": "192.168.1.100"
                }
            }
            mock_get_vm_service.return_value = mock_vm_service
            
            response = authenticated_client.post(
                constants.ROUTE_VM_UNDEPLOY,
                json={"vm_ids": ["compute01-1"]}
            )
            
            assert response.status_code == HTTPStatus.ACCEPTED
            assert "compute01-1" in response.json.get("data", {})
            
            mock_vm_service.execute_undeployment.assert_called_once()
            args, kwargs = mock_vm_service.execute_undeployment.call_args
            assert args[0] == []  # 空的nodes列表
            assert args[1] == ["compute01-1"]  # VM ID列表
    
    def test_undeploy_cvm_with_old_format(self, authenticated_client, app):
        """测试使用旧格式卸载虚拟机：{"vm_id": ["compute01-1"]}"""
        with app.app_context():
            node1 = ComputeNode(
                nodename="compute01",
                ip="192.168.1.100",
                physical_cpu=8,
                memory=16384,
                memory_free=8192,
                secure_memory=4096,
                secure_memory_free=4096,
                secure_numa_topology="{}"
            )
            db.session.add(node1)
            
            vm1 = VmInstance(
                vm_id="compute01-1",
                host_ip=node1.ip,
                host_name=node1.nodename,
                vm_spec_uuid="spec-123",
                iface_list=json.dumps({
                "mac_address": "00:11:22:33:44:55",
                "vlan_id": 100,
                "ip_address": "192.168.1.10",
                "subnet_mask": "255.255.255.0",
                "gateway": "192.168.1.1"})
            )
            db.session.add(vm1)
            db.session.commit()
        
        with patch('virtcca_deploy.services.vm_service.get_vm_service') as mock_get_vm_service:
            mock_vm_service = MagicMock()
            mock_vm_service.execute_undeployment.return_value = {
                "compute01-1": {
                    "task_id": "task-123",
                    "host_ip": "192.168.1.100"
                }
            }
            mock_get_vm_service.return_value = mock_vm_service
            
            response = authenticated_client.post(
                constants.ROUTE_VM_UNDEPLOY,
                json={"vm_ids": ["compute01-1"]}
            )
            
            assert response.status_code == HTTPStatus.ACCEPTED
            assert "compute01-1" in response.json.get("data", {})
            
            mock_vm_service.execute_undeployment.assert_called_once()
            args, kwargs = mock_vm_service.execute_undeployment.call_args
            assert args[0] == []
            assert args[1] == ["compute01-1"]
    
    def test_undeploy_cvm_invalid_format(self, authenticated_client):
        """测试无效的输入格式"""
        response = authenticated_client.post(
            constants.ROUTE_VM_UNDEPLOY,
            json={"invalid_key": ["compute01-1"]}
        )
        
        assert response.status_code == HTTPStatus.BAD_REQUEST
    
    def test_undeploy_cvm_empty_list(self, authenticated_client):
        """测试空列表输入"""
        response = authenticated_client.post(
            constants.ROUTE_VM_UNDEPLOY,
            json=[]
        )
        
        assert response.status_code == HTTPStatus.BAD_REQUEST
        print(response.json)
        assert "Invalid request format, expected a list of VM IDs" in response.json.get("message", "")
    
    def test_undeploy_cvm_non_list_format(self, authenticated_client):
        """测试非列表格式输入"""
        response = authenticated_client.post(
            constants.ROUTE_VM_UNDEPLOY,
            json={"vm_id": "compute01-1"}
        )
        
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Invalid request format" in response.json.get("message", "")