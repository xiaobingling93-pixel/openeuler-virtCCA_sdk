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
from flask import Flask
import virtcca_deploy.common.constants as constants
from virtcca_deploy.common.constants import HTTPStatusCodes, OperationCodes
from virtcca_deploy.common.data_model import ApiResponse
from virtcca_deploy.services.virt_service import deploy_cvm


class TestComputeDeploy:
    def test_deploy_cvm_internal_valid_request(self, compute_client, monkeypatch):
        """测试有效的部署请求"""
        # 模拟请求数据
        request_data = {
            'vm_id_list': ['compute01-1', 'compute01-2'],
            'vm_spec': {
                'max_vm_num': 2,
                'memory': 8192,
                'core_num': 4,
                'vlan_id': 0,
                'gateway_ip': '192.168.100.1',
                'net_pf_num': 1,
                'net_vf_num': 0,
                'disk_size': 10,
                'uuid': '74260cba-197f-42d1-9af5-4247d182edd5'
            },
            'vm_ip_dict': {}
        }
        
        # 模拟部署结果
        mock_deployed_cvms = ['compute01-1', 'compute01-2']
        
        with patch('virtcca_deploy.compute.compute.virt_service.deploy_cvm') as mock_deploy_cvm, \
             patch('virtcca_deploy.services.virt_service.cvm_net_check') as mock_net_check, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_libvirt_driver:
            # 配置模拟返回值
            mock_deploy_cvm.return_value = (mock_deployed_cvms, None)
            mock_net_check.return_value = []  # 模拟所有IP都可到达
            
            # 模拟libvirtDriver实例
            mock_libvirt_instance = mock_libvirt_driver.return_value
            mock_libvirt_instance.start_vm_by_xml.return_value = True
            
            # 发送请求
            response = compute_client.post(
                constants.ROUTE_VM_DEPLOY_INTERNAL,
                data=json.dumps(request_data),
                content_type='application/json'
            )
            
            # 验证响应
            assert response.status_code == 200
            response_data = response.get_json()
            assert response_data.get('data') == mock_deployed_cvms
    
    def test_deploy_cvm_internal_missing_field(self, compute_client):
        """测试缺少必填字段的情况"""
        # 缺少vm_id_list字段的请求数据
        request_data = {
            'vm_spec': {
                'max_vm_num': 2,
                'memory': 8192,
                'core_num': 4,
                'vlan_id': 0,
                'gateway_ip': '192.168.100.1',
                'net_pf_num': 1,
                'net_vf_num': 0,
                'disk_size': 10,
                'uuid': '74260cba-197f-42d1-9af5-4247d182edd5'
            },
            'vm_ip_dict': {}
        }
        
        response = compute_client.post(
            constants.ROUTE_VM_DEPLOY_INTERNAL,
            data=json.dumps(request_data),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        response_data = response.get_json()
        assert 'Missing required field: vm_id_list' in response_data.get('message', '')
    
    def test_deploy_cvm_internal_invalid_vm_id_list(self, compute_client):
        """测试无效的vm_id_list格式"""
        # vm_id_list不是列表
        request_data = {
            'vm_id_list': 'compute01-1',  # 应该是列表
            'vm_spec': {
                'max_vm_num': 2,
                'memory': 8192,
                'core_num': 4,
                'vlan_id': 0,
                'gateway_ip': '192.168.100.1',
                'net_pf_num': 1,
                'net_vf_num': 0,
                'disk_size': 10,
                'uuid': '74260cba-197f-42d1-9af5-4247d182edd5'
            },
            'vm_ip_dict': {}
        }
        
        response = compute_client.post(
            constants.ROUTE_VM_DEPLOY_INTERNAL,
            data=json.dumps(request_data),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        response_data = response.get_json()
        assert 'vm_id_list must be a non-empty list' in response_data.get('message', '')
    
    def test_deploy_cvm_internal_empty_vm_id_list(self, compute_client):
        """测试空的vm_id_list"""
        request_data = {
            'vm_id_list': [],  # 空列表
            'vm_spec': {
                'max_vm_num': 2,
                'memory': 8192,
                'core_num': 4,
                'vlan_id': 0,
                'gateway_ip': '192.168.100.1',
                'net_pf_num': 1,
                'net_vf_num': 0,
                'disk_size': 10,
                'uuid': '74260cba-197f-42d1-9af5-4247d182edd5'
            },
            'vm_ip_dict': {}
        }
        
        response = compute_client.post(
            constants.ROUTE_VM_DEPLOY_INTERNAL,
            data=json.dumps(request_data),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        response_data = response.get_json()
        assert 'vm_id_list must be a non-empty list' in response_data.get('message', '')
    
    def test_deploy_cvm_internal_invalid_vm_spec(self, compute_client):
        """测试无效的vm_spec格式"""
        request_data = {
            'vm_id_list': ['compute01-1'],
            'vm_spec': 'invalid_spec',  # 应该是字典
            'vm_ip_dict': {}
        }
        
        response = compute_client.post(
            constants.ROUTE_VM_DEPLOY_INTERNAL,
            data=json.dumps(request_data),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        response_data = response.get_json()
        assert 'vm_spec must be a dictionary' in response_data.get('message', '')
    
    def test_deploy_cvm_internal_invalid_vm_ip_dict(self, compute_client):
        """测试无效的vm_ip_dict格式"""
        request_data = {
            'vm_id_list': ['compute01-1'],
            'vm_spec': {
                'max_vm_num': 2,
                'memory': 8192,
                'core_num': 4,
                'vlan_id': 0,
                'gateway_ip': '192.168.100.1',
                'net_pf_num': 1,
                'net_vf_num': 0,
                'disk_size': 10,
                'uuid': '74260cba-197f-42d1-9af5-4247d182edd5'
            },
            'vm_ip_dict': 'invalid_ip_dict'  # 应该是字典
        }
        
        response = compute_client.post(
            constants.ROUTE_VM_DEPLOY_INTERNAL,
            data=json.dumps(request_data),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        response_data = response.get_json()
        assert 'vm_ip_dict must be a dictionary' in response_data.get('message', '')
    
    def test_deploy_cvm_internal_deployment_failure(self, compute_client):
        """测试部署失败的情况"""
        request_data = {
            'vm_id_list': ['compute01-1', 'compute01-2'],
            'vm_spec': {
                'max_vm_num': 2,
                'memory': 8192,
                'core_num': 4,
                'vlan_id': 0,
                'gateway_ip': '192.168.100.1',
                'net_pf_num': 1,
                'net_vf_num': 0,
                'disk_size': 10,
                'uuid': '74260cba-197f-42d1-9af5-4247d182edd5'
            },
            'vm_ip_dict': {}
        }
        
        # 模拟部分部署失败
        mock_deployed_cvms = ['compute01-1']
        mock_error_msg = 'Failed to deploy compute01-2'
        
        with patch('virtcca_deploy.compute.compute.virt_service.deploy_cvm') as mock_deploy_cvm, \
             patch('virtcca_deploy.services.virt_service.cvm_net_check') as mock_net_check, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_libvirt_driver:
            mock_deploy_cvm.return_value = (mock_deployed_cvms, mock_error_msg)
            mock_net_check.return_value = []  # 模拟所有IP都可到达
            
            # 模拟libvirtDriver实例
            mock_libvirt_instance = mock_libvirt_driver.return_value
            mock_libvirt_instance.start_vm_by_xml.return_value = True
            
            response = compute_client.post(
                constants.ROUTE_VM_DEPLOY_INTERNAL,
                data=json.dumps(request_data),
                content_type='application/json'
            )
            
            assert response.status_code == 200  # 注意：失败时返回200但status字段为FAILED
            response_data = response.get_json()
            assert 'Deploy cvm failed' in response_data.get('message', '')
            assert response_data.get('data') == mock_deployed_cvms


class TestVirtServiceDeploy:
    def test_deploy_cvm_with_vm_id_list(self, monkeypatch):
        """测试virt_service.deploy_cvm函数处理vm_id_list"""
        from virtcca_deploy.common.data_model import VmDeploySpecInternal, VmDeploySpec
        
        # 创建测试数据
        vm_spec = VmDeploySpec(
            max_vm_num=2,
            memory=8192,
            core_num=4,
            vlan_id=0,
            gateway_ip='192.168.100.1',
            net_pf_num=1,
            net_vf_num=0,
            disk_size=10,
            uuid='74260cba-197f-42d1-9af5-4247d182edd5'
        )
        
        cvm_deploy_spec_internal = VmDeploySpecInternal(
            vm_id_list=['compute01-1', 'compute01-2'],
            vm_spec=vm_spec,
            vm_ip_dict={}
        )
        
        server_config = MagicMock()
        
        # 补丁依赖函数
        with patch('virtcca_deploy.services.virt_service.cvm_numa_check') as mock_numa_check:
            mock_numa_check.return_value = ([0], None)
            
            with patch('virtcca_deploy.services.virt_service.cvm_device_check') as mock_device_check:
                mock_device_check.return_value = (['device1'], None)
                
                with patch('virtcca_deploy.services.virt_service._execute_deploy_cvm') as mock_execute_deploy:
                    mock_execute_deploy.return_value = None
                    
                    with patch('virtcca_deploy.services.virt_service.cvm_net_check') as mock_net_check:
                        mock_net_check.return_value = []
                        
                        # 调用函数
                        result, err_msg = deploy_cvm(cvm_deploy_spec_internal, server_config)
                        
                        # 验证结果
                        assert err_msg is None
                        assert result == ['compute01-1', 'compute01-2']
                        assert mock_execute_deploy.call_count == 2

    def test_deploy_cvm_with_empty_vm_ip_dict(self, monkeypatch):
        """测试virt_service.deploy_cvm函数处理空的vm_ip_dict"""
        from virtcca_deploy.common.data_model import VmDeploySpecInternal, VmDeploySpec
        
        # 创建测试数据
        vm_spec = VmDeploySpec(
            max_vm_num=1,
            memory=8192,
            core_num=4,
            vlan_id=0,
            gateway_ip='192.168.100.1',
            net_pf_num=1,
            net_vf_num=0,
            disk_size=10,
            uuid='74260cba-197f-42d1-9af5-4247d182edd5'
        )
        
        cvm_deploy_spec_internal = VmDeploySpecInternal(
            vm_id_list=['compute01-1'],
            vm_spec=vm_spec,
            vm_ip_dict={}  # 空的IP字典
        )
        
        server_config = MagicMock()
        
        with patch('virtcca_deploy.services.virt_service.cvm_numa_check') as mock_numa_check:
            mock_numa_check.return_value = ([0], None)
            
            with patch('virtcca_deploy.services.virt_service.cvm_device_check') as mock_device_check:
                mock_device_check.return_value = (['device1'], None)
                
                with patch('virtcca_deploy.services.virt_service._execute_deploy_cvm') as mock_execute_deploy:
                    mock_execute_deploy.return_value = None
                    
                    with patch('virtcca_deploy.services.virt_service.cvm_net_check') as mock_net_check:
                        mock_net_check.return_value = []
                        
                        result, err_msg = deploy_cvm(cvm_deploy_spec_internal, server_config)
                        
                        assert err_msg is None
                        assert result == ['compute01-1']
                        # 验证_execute_deploy_cvm被调用时使用了空列表作为IP
                        mock_execute_deploy.assert_called_once()
                        call_args = mock_execute_deploy.call_args
                        assert call_args[0][4] == []  # IP列表应该是空的
