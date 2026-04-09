#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import os
import sys

# 确保项目src目录在sys.path中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(PROJECT_ROOT, 'src')
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

import json
import pytest
from unittest.mock import patch, MagicMock
from virtcca_deploy.services.db_service import db
from virtcca_deploy.common.data_model import VmDeploySpec
from virtcca_deploy.services.db_service import ComputeNode, VmDeploySpecModel
import virtcca_deploy.common.constants as constants


class TestVmDeployEndpoint:
    def test_deploy_cvm_success(self, authenticated_client, app):
        # 在数据库中创建测试节点和部署配置
        with app.app_context():
            # 创建计算节点
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
            
            # 创建部署配置
            deploy_spec = VmDeploySpec(vm_num=2, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()
            
            deploy_config_id = deploy_spec_model.uuid
        
        # 模拟vm_service.execute_deployment方法
        with patch('virtcca_deploy.services.vm_service.get_vm_service') as mock_get_vm_service:
            mock_vm_service = MagicMock()
            mock_vm_service.execute_deployment.return_value = {
                "compute01-1": {"task_id": "task-1", "host_ip": "192.168.1.100"},
                "compute01-2": {"task_id": "task-2", "host_ip": "192.168.1.100"}
            }
            mock_get_vm_service.return_value = mock_vm_service
            
            resp = authenticated_client.post(constants.ROUTE_VM_DEPLOY, json={
                "vm_id": {},
                "deploy_config_id": deploy_config_id
            })
            
            assert resp.status_code == 202  # ACCEPTED
            data = resp.get_json()
            assert "compute01-1" in data["data"]
            assert "compute01-2" in data["data"]
            assert data["data"]["compute01-1"]["task_id"] == "task-1"
            assert data["data"]["compute01-2"]["task_id"] == "task-2"
    
    def test_deploy_cvm_missing_config_id(self, authenticated_client):
        # 缺少deploy_config_id
        resp = authenticated_client.post(constants.ROUTE_VM_DEPLOY, json={
            "vm_id": {}
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid request format" in data["message"]
    
    def test_deploy_cvm_invalid_config_id(self, authenticated_client):
        # 无效的deploy_config_id
        resp = authenticated_client.post(constants.ROUTE_VM_DEPLOY, json={
            "vm_id": {},
            "deploy_config_id": "invalid-config-id"
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid deploy_config_id" in data["message"]
    
    def test_deploy_cvm_no_nodes(self, authenticated_client, app):
        # 没有可用节点
        with app.app_context():
            # 创建部署配置
            deploy_spec = VmDeploySpec(vm_num=2, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()
            deploy_config_id = deploy_spec_model.uuid
        
        resp = authenticated_client.post(constants.ROUTE_VM_DEPLOY, json={
            "vm_id": {},
            "deploy_config_id": deploy_config_id
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "No target nodes found" in data["message"]
    
    def test_deploy_cvm_with_custom_vm_id(self, authenticated_client, app):
        # 使用自定义vm_id
        with app.app_context():
            # 创建计算节点
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
            
            # 创建部署配置
            deploy_spec = VmDeploySpec(vm_num=1, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()
            deploy_config_id = deploy_spec_model.uuid
        
        # 模拟vm_service.execute_deployment方法
        with patch('virtcca_deploy.services.vm_service.get_vm_service') as mock_get_vm_service:
            mock_vm_service = MagicMock()
            mock_vm_service.execute_deployment.return_value = {
                "my-custom-vm-1": {"task_id": "task-1", "host_ip": "192.168.1.100"}
            }
            mock_get_vm_service.return_value = mock_vm_service
            
            resp = authenticated_client.post(constants.ROUTE_VM_DEPLOY, json={
                "deploy_config_id": deploy_config_id,
                "vm_id": {
                    "compute01": ["my-custom-vm-1"]
                }
            })
            
            assert resp.status_code == 202
            data = resp.get_json()
            assert "my-custom-vm-1" in data["data"]
    
    def test_deploy_cvm_invalid_node(self, authenticated_client, app):
        # 无效的节点名
        with app.app_context():
            # 创建部署配置
            deploy_spec = VmDeploySpec(vm_num=1, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()
            deploy_config_id = deploy_spec_model.uuid
        
        resp = authenticated_client.post(constants.ROUTE_VM_DEPLOY, json={
            "deploy_config_id": deploy_config_id,
            "vm_id": {
                "invalid-node": ["vm-1"]
            }
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Node invalid-node not found" in data["message"]
    
    def test_deploy_cvm_config_conflict(self, authenticated_client, app):
        # 配置冲突测试
        with app.app_context():
            # 创建计算节点
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
            
            # 创建第一个部署配置
            deploy_spec1 = VmDeploySpec(vm_num=1, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model1 = deploy_spec1.to_db_model()
            deploy_spec_model1.is_default = True
            db.session.add(deploy_spec_model1)
            
            # 创建第二个部署配置
            deploy_spec2 = VmDeploySpec(vm_num=1, memory=8192, core_num=4, vlan_id=200)
            deploy_spec_model2 = deploy_spec2.to_db_model()
            deploy_spec_model2.is_default = False
            db.session.add(deploy_spec_model2)
            
            # 创建一个使用第一个配置的VM实例
            from virtcca_deploy.services.db_service import VmInstance
            vm_instance = VmInstance(
                vm_id="existing-vm-1",
                host_ip="192.168.1.100",
                host_name="compute01",
                vm_spec_uuid=deploy_spec_model1.uuid,
                ip_list="10.0.0.10"
            )
            db.session.add(vm_instance)
            
            db.session.commit()
            
            deploy_config_id2 = deploy_spec_model2.uuid
        
        resp = authenticated_client.post(constants.ROUTE_VM_DEPLOY, json={
            "vm_id": {},
            "deploy_config_id": deploy_config_id2
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Please undeploy all VMs using different config first" in data["message"]
    
    def test_deploy_cvm_with_default_config(self, authenticated_client, app):
        # 使用默认配置（deploy_config_id为空）
        with app.app_context():
            # 创建计算节点
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
            
            # 创建默认部署配置
            deploy_spec = VmDeploySpec(vm_num=1, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()
        
        # 模拟vm_service.execute_deployment方法
        with patch('virtcca_deploy.services.vm_service.get_vm_service') as mock_get_vm_service:
            mock_vm_service = MagicMock()
            mock_vm_service.execute_deployment.return_value = {
                "compute01-1": {"task_id": "task-1", "host_ip": "192.168.1.100"}
            }
            mock_get_vm_service.return_value = mock_vm_service
            
            resp = authenticated_client.post(constants.ROUTE_VM_DEPLOY, json={
                "vm_id": {},
                "deploy_config_id": ""
            })
            
            # 验证结果
            assert resp.status_code == 202
            data = resp.get_json()
            assert "compute01-1" in data["data"]
