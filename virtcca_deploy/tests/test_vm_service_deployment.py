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
from virtcca_deploy.common.data_model import VmDeploySpec, NetAllocResp, NetReleaseReq
import virtcca_deploy.common.constants as constants
from virtcca_deploy.services.resource_allocator import IpAllocator

class TestVmServiceDeployment:
    def test_execute_deployment_success(self, app):
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=True,
                    vm_iface_map={
                        "compute01-1": [],
                        "compute01-2": []
                    }
                )
                vm_service = VmService(None, ip_allocator)

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

                deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                deploy_spec_model.is_default = True
                db.session.add(deploy_spec_model)
                db.session.commit()

                with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                    patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                    patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn, \
                    patch('virtcca_deploy.services.vm_service.gevent.joinall') as mock_joinall:

                    mock_task = MagicMock()
                    mock_task.create_task.return_value = "task-123"
                    mock_get_task_service.return_value = mock_task

                    mock_network_instance = MagicMock()
                    mock_response = MagicMock()
                    mock_response.status_code = HTTPStatus.OK
                    # 模拟返回成功部署的VM列表
                    mock_response.json.return_value = {"data": ["compute01-1", "compute01-2"], "message": ""}
                    # 模拟返回成功部署的VM列表
                    mock_response.json.return_value = {"data": ["compute01-1", "compute01-2"], "message": ""}
                    mock_network_instance.vm_deploy.return_value = mock_response
                    mock_network_service.return_value = mock_network_instance

                    # Mock gevent → 同步执行
                    jobs = []
                    def sync_spawn(func, *args, **kwargs):
                        # 立即执行函数并创建mock job
                        func(*args, **kwargs)
                        job_mock = MagicMock()
                        jobs.append(job_mock)
                        return job_mock
                    
                    def sync_joinall(jobs_to_join, timeout=None):
                        # 同步join，不执行任何操作
                        pass

                    mock_spawn.side_effect = sync_spawn
                    mock_joinall.side_effect = sync_joinall

                    result = vm_service.execute_deployment([node], deploy_spec_model, {})

                    assert result is not None
                    assert len(result) == 2

                    assert mock_task.create_task.called
                    mock_task.update_task_status.assert_any_call("task-123", "running")
                    mock_task.update_task_status.assert_any_call("task-123", "success")
                    
                    # 验证任务参数是否正确更新
                    mock_task.update_task_params.assert_called_once()
                    call_args = mock_task.update_task_params.call_args
                    assert call_args[0][0] == "task-123"
                    task_params = call_args[0][1]
                    assert set(task_params["success_vms"]) == {"compute01-1", "compute01-2"}
                    assert task_params["fail_vms"] == []
                    assert set(task_params["total_vms"]) == {"compute01-1", "compute01-2"}

                    mock_network_service.assert_called_once()
                    mock_network_instance.vm_deploy.assert_called_once()

                    # 刷新会话并查询
                    db.session.expire_all()
                    vm_list = VmInstance.query.all()
                    assert len(vm_list) == 2

    def test_execute_deployment_failure(self, app):
        with app.app_context():
            init_task_service()

            ip_allocator = MagicMock()
            ip_allocator.allocate.return_value = NetAllocResp(
                success=True,
                vm_iface_map={
                    "compute01-1": []
                }
            )
            vm_service = VmService(None, ip_allocator)

            # ===== 创建节点 =====
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

            # ===== 创建部署配置 =====
            deploy_spec = VmDeploySpec(max_vm_num=1, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                mock_task = MagicMock()
                mock_task.create_task.return_value = "task-123"
                mock_get_task_service.return_value = mock_task

                # ===== Mock NetworkService → 失败 =====
                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
                mock_network_instance.vm_deploy.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # ===== Mock gevent → 同步执行 =====
                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                # ===== 执行 =====
                result = vm_service.execute_deployment([node], deploy_spec_model, {})

                # ===== 断言：返回值 =====
                assert result is not None
                assert len(result) == 1
                assert "compute01-1" in result

                # ===== 断言：NetworkService =====
                mock_network_instance.vm_deploy.assert_called_once()

                # ===== 断言：任务状态更新为 failed =====
                mock_task.update_task_status.assert_any_call("task-123", "running")
                mock_task.update_task_status.assert_any_call("task-123", "failed")
                
                # 验证任务参数是否正确更新
                mock_task.update_task_params.assert_called_once()
                call_args = mock_task.update_task_params.call_args
                assert call_args[0][0] == "task-123"
                task_params = call_args[0][1]
                assert task_params["success_vms"] == []  # 没有成功的VM
                assert task_params["fail_vms"] == ["compute01-1"]  # 所有VM都失败
                assert set(task_params["total_vms"]) == {"compute01-1"}  # 总VM列表

                ip_allocator.release.assert_called()
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 0

    def test_prepare_default_deployment_empty_vm_id_dict(self, app):
        """vm_id_dict为空时：自动生成vm_id并分配IP"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=True,
                    vm_iface_map={
                        "compute01-1": [],
                        "compute01-2": [],
                        "compute01-3": []
                    }
                )
                vm_service = VmService(None, ip_allocator)

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

                deploy_spec = VmDeploySpec(max_vm_num=3, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                deploy_spec_model.is_default = True
                db.session.add(deploy_spec_model)
                db.session.commit()

                with patch.object(vm_service.pre_deployment_checker, 'check_nodes', return_value=(False, [])):
                    result, error_msg = vm_service._prepare_default_deployment([node], deploy_spec_model)

                    assert error_msg == ""
                    assert "compute01" in result
                    spec = result["compute01"]
                    assert spec.vm_id_list == ["compute01-1", "compute01-2", "compute01-3"]
                    assert len(spec.vm_id_list) == 3

    def test_prepare_default_deployment_multiple_nodes(self, app):
        """vm_id_dict为空时：多节点自动生成vm_id"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=True,
                    vm_iface_map={}
                )
                vm_service = VmService(None, ip_allocator)

                node1 = ComputeNode(
                    nodename="compute01", ip="192.168.1.100",
                    physical_cpu=8, memory=16384, memory_free=8192,
                    secure_memory=4096, secure_memory_free=4096, secure_numa_topology="{}"
                )
                node2 = ComputeNode(
                    nodename="compute02", ip="192.168.1.101",
                    physical_cpu=8, memory=16384, memory_free=8192,
                    secure_memory=4096, secure_memory_free=4096, secure_numa_topology="{}"
                )
                db.session.add_all([node1, node2])

                deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                deploy_spec_model.is_default = True
                db.session.add(deploy_spec_model)
                db.session.commit()

                with patch.object(vm_service.pre_deployment_checker, 'check_nodes', return_value=(False, [])):
                    result, error_msg = vm_service._prepare_default_deployment([node1, node2], deploy_spec_model)

                    assert error_msg == ""
                    assert "compute01" in result
                    assert "compute02" in result
                    assert result["compute01"].vm_id_list == ["compute01-1", "compute01-2"]
                    assert result["compute02"].vm_id_list == ["compute02-1", "compute02-2"]

    def test_prepare_default_deployment_no_ip_allocator(self, app):
        """vm_id_dict为空时：无IP分配器仍能生成vm_id"""
        with app.app_context():
            init_task_service()
            vm_service = VmService(None, None)

            node = ComputeNode(
                nodename="compute01", ip="192.168.1.100",
                physical_cpu=8, memory=16384, memory_free=8192,
                secure_memory=4096, secure_memory_free=4096, secure_numa_topology="{}"
            )
            db.session.add(node)

            deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            db.session.add(deploy_spec_model)
            db.session.commit()

            with patch.object(vm_service.pre_deployment_checker, 'check_nodes', return_value=(False, [])):
                result, error_msg = vm_service._prepare_default_deployment([node], deploy_spec_model)

                assert error_msg == ""
                assert result["compute01"].vm_id_list == ["compute01-1", "compute01-2"]
                assert result["compute01"].vm_iface == {}

    def test_prepare_specified_deployment_all_new(self, app):
        """vm_id_dict非空时：所有vm_id均为新VM，需分配IP"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service') as mock_get_service:
                mock_service = MagicMock()
                mock_service.allocate_ips_for_deployment.return_value = (
                    True,
                    {"compute01-1": ["192.168.100.10"], "compute01-2": ["192.168.100.11"]},
                    {
                        "compute01-1": [{"mac_address": "00:11:22:33:44:55", "vlan_id": 100,
                                         "ip_address": "192.168.100.10", "subnet_mask": "255.255.255.0",
                                         "gateway": "192.168.100.1"}],
                        "compute01-2": [{"mac_address": "00:11:22:33:44:56", "vlan_id": 100,
                                         "ip_address": "192.168.100.11", "subnet_mask": "255.255.255.0",
                                         "gateway": "192.168.100.1"}]
                    },
                    ""
                )
                mock_get_service.return_value = mock_service

                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=True,
                    vm_iface_map={
                        "compute01-1": [{"mac_address": "00:11:22:33:44:55", "vlan_id": 100,
                                         "ip_address": "192.168.100.10", "subnet_mask": "255.255.255.0",
                                         "gateway": "192.168.100.1"}],
                        "compute01-2": [{"mac_address": "00:11:22:33:44:56", "vlan_id": 100,
                                         "ip_address": "192.168.100.11", "subnet_mask": "255.255.255.0",
                                         "gateway": "192.168.100.1"}]
                    }
                )
                vm_service = VmService(None, ip_allocator)

                node = ComputeNode(
                    nodename="compute01", ip="192.168.1.100",
                    physical_cpu=8, memory=16384, memory_free=8192,
                    secure_memory=4096, secure_memory_free=4096, secure_numa_topology="{}"
                )
                db.session.add(node)

                deploy_spec = VmDeploySpec(max_vm_num=5, memory=4096, core_num=2, vlan_id=100, net_pf_num=2)
                deploy_spec_model = deploy_spec.to_db_model()
                db.session.add(deploy_spec_model)
                db.session.commit()

                vm_id_dict = {"compute01": ["compute01-1", "compute01-2"]}
                with patch.object(vm_service.pre_deployment_checker, 'check_nodes_with_vm_ids', return_value=(False, [])):
                    result, error_msg = vm_service._prepare_specified_deployment([node], deploy_spec_model, vm_id_dict)

                    assert error_msg == ""
                    assert result["compute01"].vm_id_list == ["compute01-1", "compute01-2"]
                    assert len(result["compute01"].vm_iface) == 2

    def test_prepare_specified_deployment_all_reused(self, app):
        """vm_id_dict非空时：所有vm_id已存在于数据库，复用IP"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                vm_service = VmService(None, ip_allocator)

                node = ComputeNode(
                    nodename="compute01", ip="192.168.1.100",
                    physical_cpu=8, memory=16384, memory_free=8192,
                    secure_memory=4096, secure_memory_free=4096, secure_numa_topology="{}"
                )
                db.session.add(node)

                deploy_spec = VmDeploySpec(max_vm_num=5, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                db.session.add(deploy_spec_model)

                existing_vm = VmInstance(
                    vm_id="compute01-1",
                    host_ip="192.168.1.100",
                    host_name="compute01",
                    vm_spec_uuid=deploy_spec_model.uuid,
                    iface_list=json.dumps([
                            {
                                "node_name": "compute01",
                                "mac_address": "00:11:22:33:44:55",
                                "vlan_id": 100,
                                "ip_address": "192.168.1.10",
                                "subnet_mask": "255.255.255.0",
                                "gateway": "192.168.1.1"
                            },
                            {
                                "node_name": "compute01",
                                "mac_address": "00:11:22:33:44:56",
                                "vlan_id": 100,
                                "ip_address": "192.168.1.11",
                                "subnet_mask": "255.255.255.0",
                                "gateway": "192.168.1.1"
                            }
                    ])
                )
                db.session.add(existing_vm)
                db.session.commit()

                vm_id_dict = {"compute01": ["compute01-1"]}
                with patch.object(vm_service.pre_deployment_checker, 'check_nodes_with_vm_ids', return_value=(False, [])):
                    result, error_msg = vm_service._prepare_specified_deployment([node], deploy_spec_model, vm_id_dict)

                    assert error_msg == ""
                    assert result["compute01"].vm_id_list == ["compute01-1"]
                    assert "compute01-1" in result["compute01"].vm_iface
                    assert len(result["compute01"].vm_iface["compute01-1"]) == 2
                    assert result["compute01"].vm_iface["compute01-1"][0].ip_address == "192.168.1.10"
                    assert result["compute01"].vm_iface["compute01-1"][1].ip_address == "192.168.1.11"

    def test_prepare_specified_deployment_mixed_new_and_reused(self, app):
        """vm_id_dict非空时：混合场景，部分复用部分新建"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service') as mock_get_service:
                mock_service = MagicMock()
                mock_service.allocate_ips_for_deployment.return_value = (
                    True,
                    {"compute01-2": ["192.168.100.11"]},
                    {
                        "compute01-2": [{"mac_address": "00:11:22:33:44:56", "vlan_id": 100,
                                         "ip_address": "192.168.100.11", "subnet_mask": "255.255.255.0",
                                         "gateway": "192.168.100.1"}]
                    },
                    ""
                )
                mock_get_service.return_value = mock_service

                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=True,
                    vm_iface_map={
                        "compute01-2": [{"mac_address": "00:11:22:33:44:56", "vlan_id": 100,
                                         "ip_address": "192.168.100.11", "subnet_mask": "255.255.255.0",
                                         "gateway": "192.168.100.1"}]
                    }
                )
                vm_service = VmService(None, ip_allocator)

                node = ComputeNode(
                    nodename="compute01", ip="192.168.1.100",
                    physical_cpu=8, memory=16384, memory_free=8192,
                    secure_memory=4096, secure_memory_free=4096, secure_numa_topology="{}"
                )
                db.session.add(node)

                deploy_spec = VmDeploySpec(max_vm_num=5, memory=4096, core_num=2, vlan_id=100, net_pf_num=2)
                deploy_spec_model = deploy_spec.to_db_model()
                db.session.add(deploy_spec_model)

                existing_vm = VmInstance(
                    vm_id="compute01-1",
                    host_ip="192.168.1.100",
                    host_name="compute01",
                    vm_spec_uuid=deploy_spec_model.uuid,
                    iface_list=json.dumps([
                        {
                            "node_name": "compute01",
                            "mac_address": "00:11:22:33:44:55",
                            "vlan_id": 100,
                            "ip_address": "192.168.1.10",
                            "subnet_mask": "255.255.255.0",
                            "gateway": "192.168.1.1"
                        }
                    ])
                )
                db.session.add(existing_vm)
                db.session.commit()

                vm_id_dict = {"compute01": ["compute01-1", "compute01-2"]}
                with patch.object(vm_service.pre_deployment_checker, 'check_nodes_with_vm_ids', return_value=(False, [])):
                    result, error_msg = vm_service._prepare_specified_deployment([node], deploy_spec_model, vm_id_dict)

                    assert error_msg == ""
                    assert result["compute01"].vm_id_list == ["compute01-1", "compute01-2"]
                    assert "compute01-1" in result["compute01"].vm_iface
                    assert len(result["compute01"].vm_iface["compute01-1"]) == 1
                    assert result["compute01"].vm_iface["compute01-1"][0].ip_address == "192.168.1.10"
                    assert "compute01-2" in result["compute01"].vm_iface

    def test_prepare_specified_deployment_db_query_failure(self, app):
        """vm_id_dict非空时：数据库查询异常，跳过该vm_id"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=True,
                    vm_iface_map={}
                )
                vm_service = VmService(None, ip_allocator)

                node = ComputeNode(
                    nodename="compute01", ip="192.168.1.100",
                    physical_cpu=8, memory=16384, memory_free=8192,
                    secure_memory=4096, secure_memory_free=4096, secure_numa_topology="{}"
                )
                db.session.add(node)

                deploy_spec = VmDeploySpec(max_vm_num=5, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                db.session.add(deploy_spec_model)
                db.session.commit()

                vm_id_dict = {"compute01": ["compute01-1", "compute01-2"]}

                with patch.object(vm_service.pre_deployment_checker, 'check_nodes_with_vm_ids', return_value=(False, [])), \
                     patch('virtcca_deploy.services.vm_service.VmInstance') as MockVmInstance:
                    mock_query = MagicMock()
                    mock_query.filter_by.return_value.first.side_effect = Exception("DB connection lost")
                    MockVmInstance.query = mock_query

                    result, error_msg = vm_service._prepare_specified_deployment([node], deploy_spec_model, vm_id_dict)

                    assert error_msg == ""
                    assert "compute01" in result
                    assert result["compute01"].vm_id_list == ["compute01-1", "compute01-2"]

    def test_execute_deployment_empty_vm_id_dict_calls_default(self, app):
        """vm_id_dict为空时：execute_deployment调用_prepare_default_deployment"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=True,
                    vm_iface_map={}
                )
                vm_service = VmService(None, ip_allocator)

                node = ComputeNode(
                    nodename="compute01", ip="192.168.1.100",
                    physical_cpu=8, memory=16384, memory_free=8192,
                    secure_memory=4096, secure_memory_free=4096, secure_numa_topology="{}"
                )
                db.session.add(node)

                deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                deploy_spec_model.is_default = True
                db.session.add(deploy_spec_model)
                db.session.commit()

                with patch.object(vm_service, '_prepare_default_deployment', wraps=vm_service._prepare_default_deployment) as mock_default, \
                    patch.object(vm_service, '_prepare_specified_deployment') as mock_specified, \
                    patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                    patch('virtcca_deploy.services.vm_service.NetworkService'), \
                    patch('virtcca_deploy.services.vm_service.gevent.spawn'):

                    mock_task = MagicMock()
                    mock_task.create_task.return_value = "task-123"
                    mock_get_task_service.return_value = mock_task

                    vm_service.execute_deployment([node], deploy_spec_model, {})

                    mock_default.assert_called_once_with([node], deploy_spec_model)
                    mock_specified.assert_not_called()

    def test_execute_deployment_nonempty_vm_id_dict_calls_specified(self, app):
        """vm_id_dict非空时：execute_deployment调用_prepare_specified_deployment"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=True,
                    vm_iface_map={}
                )
                vm_service = VmService(None, ip_allocator)

                node = ComputeNode(
                    nodename="compute01", ip="192.168.1.100",
                    physical_cpu=8, memory=16384, memory_free=8192,
                    secure_memory=4096, secure_memory_free=4096, secure_numa_topology="{}"
                )
                db.session.add(node)

                deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                deploy_spec_model.is_default = True
                db.session.add(deploy_spec_model)
                db.session.commit()

                vm_id_dict = {"compute01": ["compute01-1"]}

                with patch.object(vm_service, '_prepare_default_deployment') as mock_default, \
                    patch.object(vm_service, '_prepare_specified_deployment', wraps=vm_service._prepare_specified_deployment) as mock_specified, \
                    patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                    patch('virtcca_deploy.services.vm_service.NetworkService'), \
                    patch('virtcca_deploy.services.vm_service.gevent.spawn'):

                    mock_task = MagicMock()
                    mock_task.create_task.return_value = "task-123"
                    mock_get_task_service.return_value = mock_task

                    vm_service.execute_deployment([node], deploy_spec_model, vm_id_dict)

                    mock_specified.assert_called_once_with([node], deploy_spec_model, vm_id_dict)
                    mock_default.assert_not_called()

    def test_execute_deployment_with_vm_id_dict_full_flow(self, app):
        """vm_id_dict非空时：完整部署流程，验证vm_id使用指定值"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=True,
                    vm_iface_map={}
                )
                vm_service = VmService(None, ip_allocator)

                node = ComputeNode(
                    nodename="compute01", ip="192.168.1.100",
                    physical_cpu=8, memory=16384, memory_free=8192,
                    secure_memory=4096, secure_memory_free=4096, secure_numa_topology="{}"
                )
                db.session.add(node)

                deploy_spec = VmDeploySpec(max_vm_num=5, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                deploy_spec_model.is_default = True
                db.session.add(deploy_spec_model)
                db.session.commit()

                vm_id_dict = {"compute01": ["compute01-3", "compute01-5"]}

                with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                    patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                    patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                    mock_task = MagicMock()
                    mock_task.create_task.return_value = "task-123"
                    mock_get_task_service.return_value = mock_task

                    mock_network_instance = MagicMock()
                    mock_response = MagicMock()
                    mock_response.status_code = HTTPStatus.OK
                    mock_response.json.return_value = {"data": ["compute01-3", "compute01-5"], "message": ""}
                    mock_network_instance.vm_deploy.return_value = mock_response
                    mock_network_service.return_value = mock_network_instance

                    def sync_spawn(func, *args, **kwargs):
                        func(*args, **kwargs)
                        return MagicMock()

                    mock_spawn.side_effect = sync_spawn

                    result = vm_service.execute_deployment([node], deploy_spec_model, vm_id_dict)

                    assert "compute01-3" in result
                    assert "compute01-5" in result
                    assert len(result) == 2

                    db.session.expire_all()
                    vm_list = VmInstance.query.all()
                    assert len(vm_list) == 2
                    vm_ids = {vm.vm_id for vm in vm_list}
                    assert vm_ids == {"compute01-3", "compute01-5"}
                
    def test_execute_deployment_task_creation_failure(self, app):
        with app.app_context():
            init_task_service()

            ip_allocator = MagicMock()
            ip_allocator.allocate.return_value = NetAllocResp(
                success=True,
                vm_iface_map={"compute01-1": []}
            )
            vm_service = VmService(None, ip_allocator)

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

            deploy_spec = VmDeploySpec(max_vm_num=1, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service:

                mock_task = MagicMock()
                mock_task.create_task.side_effect = Exception("Task creation failed")
                mock_get_task_service.return_value = mock_task

                result = vm_service.execute_deployment([node], deploy_spec_model, {})

                # ===== 返回值 =====
                assert result is not None
                assert len(result) == 0

                # ===== 不应该调用 NetworkService =====
                mock_network_service.assert_not_called()

                # ===== 不应该写数据库 =====
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 0
    
    def test_execute_deployment_multiple_nodes(self, app):
        with app.app_context():
            init_task_service()

            ip_allocator = MagicMock()
            ip_allocator.allocate.return_value = NetAllocResp(
                success=True,
                vm_iface_map={}
            )
            vm_service = VmService(None, ip_allocator)

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

            node2 = ComputeNode(
                nodename="compute02",
                ip="192.168.1.101",
                physical_cpu=8,
                memory=16384,
                memory_free=8192,
                secure_memory=4096,
                secure_memory_free=4096,
                secure_numa_topology="{}"
            )

            db.session.add_all([node1, node2])

            deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                # ===== task service =====
                mock_task = MagicMock()
                mock_task.create_task.side_effect = ["task-1", "task-2"]
                mock_get_task_service.return_value = mock_task

                # ===== NetworkService =====
                mock_network_instance = MagicMock()
                
                # 创建两个不同的响应对象，分别用于两个节点
                response1 = MagicMock()
                response1.status_code = HTTPStatus.OK
                response1.json.return_value = {"data": ["compute01-1", "compute01-2"], "message": ""}
                
                response2 = MagicMock()
                response2.status_code = HTTPStatus.OK
                response2.json.return_value = {"data": ["compute02-1", "compute02-2"], "message": ""}
                
                # 使用side_effect直接返回这两个响应对象
                mock_network_instance.vm_deploy.side_effect = [response1, response2]
                mock_network_service.return_value = mock_network_instance

                # ===== gevent → 同步执行 =====
                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                # ===== 执行 =====
                result = vm_service.execute_deployment([node1, node2], deploy_spec_model, {})

                # ===== 返回值 =====
                assert result is not None
                assert len(result) == 4

                assert "compute01-1" in result
                assert "compute01-2" in result
                assert "compute02-1" in result
                assert "compute02-2" in result

                # ===== NetworkService 调用次数 =====
                assert mock_network_service.call_count == 2
                assert mock_network_instance.vm_deploy.call_count == 2

                # ===== task 创建次数 =====
                assert mock_task.create_task.call_count == 2
                
                # ===== 验证任务参数和状态更新 =====
                # 验证每个任务都被更新了状态和参数
                assert mock_task.update_task_status.call_count >= 4  # 每个任务至少有running和success状态更新
                
                task_params_calls = mock_task.update_task_params.call_args_list
                assert len(task_params_calls) == 2
                
                # 验证第一个任务的参数
                first_call = task_params_calls[0]
                second_call = task_params_calls[1]
                
                # 确保两个调用的任务ID不同
                assert first_call[0][0] != second_call[0][0]
                
                # 验证compute01节点的任务参数
                if first_call[0][0] == "task-1":
                    task1_params = first_call[0][1]
                    task2_params = second_call[0][1]
                else:
                    task1_params = second_call[0][1]
                    task2_params = first_call[0][1]
                
                # 验证任务1的参数
                assert set(task1_params["success_vms"]) == {"compute01-1", "compute01-2"}
                assert task1_params["fail_vms"] == []
                assert set(task1_params["total_vms"]) == {"compute01-1", "compute01-2"}
                
                # 验证任务2的参数
                assert set(task2_params["success_vms"]) == {"compute02-1", "compute02-2"}
                assert task2_params["fail_vms"] == []
                assert set(task2_params["total_vms"]) == {"compute02-1", "compute02-2"}
                
                # 确保两个任务的参数对象不是同一个（检查引用）
                assert task1_params is not task2_params

                # ===== 数据库验证 =====
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 4

                host_ips = set(vm.host_ip for vm in vm_list)
                assert host_ips == {"192.168.1.100", "192.168.1.101"}

    def test_execute_deployment_partial_success(self, app):
        """测试部分虚拟机部署成功的情况"""
        with app.app_context():
            init_task_service()

            # ===== Mock VLAN =====
            ip_allocator = MagicMock()

            vm_service = VmService(None, ip_allocator)

            # ===== 创建节点 =====
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

            # ===== 创建部署配置 =====
            deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                # ===== Mock task service =====
                mock_task = MagicMock()
                mock_task.create_task.return_value = "task-123"
                mock_get_task_service.return_value = mock_task

                # ===== Mock NetworkService → 部分成功 =====
                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"data": ["compute01-1"], "message": ""}
                mock_network_instance.vm_deploy.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # ===== Mock gevent → 同步执行 =====
                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                # ===== 执行 =====
                result = vm_service.execute_deployment([node], deploy_spec_model, {})

                # ===== 断言：返回值 =====
                assert result is not None
                assert len(result) == 2
                assert "compute01-1" in result
                assert "compute01-2" in result

                # ===== 断言：NetworkService =====
                mock_network_instance.vm_deploy.assert_called_once()

                # ===== 断言：任务状态和参数更新 =====
                mock_task.update_task_status.assert_any_call("task-123", "running")
                mock_task.update_task_status.assert_any_call("task-123", "failed")  # 有失败的VM，任务状态应为failed
                mock_task.update_task_params.assert_called_once()
                
                # 验证任务参数是否正确
                call_args = mock_task.update_task_params.call_args
                assert call_args[0][0] == "task-123"
                task_params = call_args[0][1]
                assert task_params["success_vms"] == ["compute01-1"]
                assert task_params["fail_vms"] == ["compute01-2"]
                assert set(task_params["total_vms"]) == {"compute01-1", "compute01-2"}

                # ===== 断言：IP释放 =====
                ip_allocator.release.assert_called_once_with(request=NetReleaseReq(vm_id_list=['compute01-2'], vlan_id=None, node_ip=None))

                # ===== 断言：只有成功的VM写入数据库 =====
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 1
                assert vm_list[0].vm_id == "compute01-1"

    def test_execute_deployment_all_success(self, app):
        """测试所有虚拟机部署成功的情况"""
        with app.app_context():
            init_task_service()

            # ===== Mock VLAN =====
            ip_allocator = MagicMock()
            ip_allocator.allocate.return_value = NetAllocResp(success=True, vm_ip_map={})

            vm_service = VmService(None, ip_allocator)

            # ===== 创建节点 =====
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

            # ===== 创建部署配置 =====
            deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                # ===== Mock task service =====
                mock_task = MagicMock()
                mock_task.create_task.return_value = "task-123"
                mock_get_task_service.return_value = mock_task

                # ===== Mock NetworkService → 全部成功 =====
                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"data": ["compute01-1", "compute01-2"], "message": ""}
                mock_network_instance.vm_deploy.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # ===== Mock gevent → 同步执行 =====
                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                # ===== 执行 =====
                result = vm_service.execute_deployment([node], deploy_spec_model, {})

                # ===== 断言：返回值 =====
                assert result is not None
                assert len(result) == 2
                assert "compute01-1" in result
                assert "compute01-2" in result

                # ===== 断言：NetworkService =====
                mock_network_instance.vm_deploy.assert_called_once()

                # ===== 断言：任务状态和参数更新 =====
                mock_task.update_task_status.assert_any_call("task-123", "running")
                mock_task.update_task_status.assert_any_call("task-123", "success")  # 全部成功，任务状态应为success
                mock_task.update_task_params.assert_called_once()
                
                # 验证任务参数是否正确
                call_args = mock_task.update_task_params.call_args
                assert call_args[0][0] == "task-123"
                task_params = call_args[0][1]
                assert set(task_params["success_vms"]) == {"compute01-1", "compute01-2"}
                assert task_params["fail_vms"] == []
                assert set(task_params["total_vms"]) == {"compute01-1", "compute01-2"}

                # ===== 断言：没有IP被释放 =====
                ip_allocator.release_ips_for_vm.assert_not_called()

                # ===== 断言：所有成功的VM写入数据库 =====
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 2
                vm_ids = [vm.vm_id for vm in vm_list]
                assert set(vm_ids) == {"compute01-1", "compute01-2"}

    def test_execute_deployment_invalid_response(self, app):
        """测试响应解析失败的情况"""
        with app.app_context():
            init_task_service()

            # ===== Mock VLAN =====
            ip_allocator = MagicMock()
            ip_allocator.allocate.return_value = NetAllocResp(success=True, vm_ip_map={
                    "compute01-1": ["192.168.1.10"],
                    "compute01-2": ["192.168.1.11"]
                })

            vm_service = VmService(None, ip_allocator)

            # ===== 创建节点 =====
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

            # ===== 创建部署配置 =====
            deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                # ===== Mock task service =====
                mock_task = MagicMock()
                mock_task.create_task.return_value = "task-123"
                mock_get_task_service.return_value = mock_task

                # ===== Mock NetworkService → 响应解析失败 =====
                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                # 模拟无效响应：json解析失败
                mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
                mock_network_instance.vm_deploy.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # ===== Mock gevent → 同步执行 =====
                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                # ===== 执行 =====
                result = vm_service.execute_deployment([node], deploy_spec_model, {})

                # ===== 断言：返回值 =====
                assert result is not None
                assert len(result) == 2
                assert "compute01-1" in result
                assert "compute01-2" in result

                # ===== 断言：NetworkService =====
                mock_network_instance.vm_deploy.assert_called_once()

                # ===== 断言：任务状态和参数更新 =====
                mock_task.update_task_status.assert_any_call("task-123", "running")
                mock_task.update_task_status.assert_any_call("task-123", "failed")  # 解析失败，任务状态应为failed
                mock_task.update_task_params.assert_called_once()
                
                # 验证任务参数是否正确
                call_args = mock_task.update_task_params.call_args
                assert call_args[0][0] == "task-123"
                task_params = call_args[0][1]
                assert task_params["success_vms"] == []  # 解析失败，成功列表为空
                assert set(task_params["fail_vms"]) == {"compute01-1", "compute01-2"}  # 所有VM都视为失败
                assert set(task_params["total_vms"]) == {"compute01-1", "compute01-2"}

                # ===== 断言：所有VM的IP都被释放 =====
                assert ip_allocator.release.call_count == 1

                # ===== 断言：没有VM写入数据库 =====
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 0

    def test_prepare_default_deployment_ip_allocation_failure(self, app):
        """测试_prepare_default_deployment中IP分配失败的场景"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=False,
                    vm_iface_map={}
                )
                vm_service = VmService(None, ip_allocator)

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

                deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                deploy_spec_model.is_default = True
                db.session.add(deploy_spec_model)
                db.session.commit()

                with patch.object(vm_service.pre_deployment_checker, 'check_nodes', return_value=(False, [])):
                    result, error_msg = vm_service._prepare_default_deployment([node], deploy_spec_model)

                    assert error_msg != ""
                    assert "Deployment failed due to insufficient resources." in error_msg
                    assert "compute01" in error_msg
                    assert "192.168.1.100" in error_msg
                    assert result == {}

    def test_prepare_default_deployment_ip_allocation_exception(self, app):
        """测试_prepare_default_deployment中IP分配抛出异常的场景"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.side_effect = Exception("IP allocator connection failed")
                vm_service = VmService(None, ip_allocator)

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

                deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                deploy_spec_model.is_default = True
                db.session.add(deploy_spec_model)
                db.session.commit()

                with patch.object(vm_service.pre_deployment_checker, 'check_nodes', return_value=(False, [])):
                    result, error_msg = vm_service._prepare_default_deployment([node], deploy_spec_model)

                    assert error_msg != ""
                    assert "Deployment failed due to insufficient resources." in error_msg
                    assert "compute01" in error_msg
                    assert "IP allocator connection failed" in error_msg
                    assert result == {}

    def test_prepare_specified_deployment_ip_allocation_failure(self, app):
        """测试_prepare_specified_deployment中IP分配失败的场景"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=False,
                    vm_iface_map={}
                )
                vm_service = VmService(None, ip_allocator)

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

                deploy_spec = VmDeploySpec(max_vm_num=5, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                db.session.add(deploy_spec_model)
                db.session.commit()

                vm_id_dict = {"compute01": ["compute01-1", "compute01-2"]}
                with patch.object(vm_service.pre_deployment_checker, 'check_nodes_with_vm_ids', return_value=(False, [])):
                    result, error_msg = vm_service._prepare_specified_deployment([node], deploy_spec_model, vm_id_dict)

                    assert error_msg != ""
                    assert "Deployment failed due to insufficient resources." in error_msg
                    assert "compute01" in error_msg
                    assert result == {}

    def test_execute_deployment_ip_allocation_failure_raises_exception(self, app):
        """测试execute_deployment在IP分配失败时抛出异常"""
        with app.app_context():
            init_task_service()
            with patch('virtcca_deploy.services.network_config_service.get_network_config_service'):
                ip_allocator = MagicMock()
                ip_allocator.allocate.return_value = NetAllocResp(
                    success=False,
                    vm_iface_map={}
                )
                vm_service = VmService(None, ip_allocator)

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

                deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
                deploy_spec_model = deploy_spec.to_db_model()
                deploy_spec_model.is_default = True
                db.session.add(deploy_spec_model)
                db.session.commit()

                with pytest.raises(Exception) as exc_info:
                    vm_service.execute_deployment([node], deploy_spec_model, {})

                assert "Deployment failed due to insufficient resources." in str(exc_info.value)
                assert "compute01" in str(exc_info.value)

    def test_execute_deployment_empty_response_data(self, app):
        """测试响应数据为空的情况"""
        with app.app_context():
            init_task_service()

            ip_allocator = MagicMock()
            ip_allocator.allocate.return_value = NetAllocResp(success=True, vm_ip_map={
                    "compute01-1": ["192.168.1.10"],
                    "compute01-2": ["192.168.1.11"]
                })

            vm_service = VmService(None, ip_allocator)

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

            deploy_spec = VmDeploySpec(max_vm_num=2, memory=4096, core_num=2, vlan_id=100)
            deploy_spec_model = deploy_spec.to_db_model()
            deploy_spec_model.is_default = True
            db.session.add(deploy_spec_model)
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                mock_task = MagicMock()
                mock_task.create_task.return_value = "task-123"
                mock_get_task_service.return_value = mock_task

                # ===== Mock NetworkService → 空响应数据 =====
                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"data": [], "message": ""}
                mock_network_instance.vm_deploy.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                result = vm_service.execute_deployment([node], deploy_spec_model, {})

                # ===== 断言：返回值 =====
                assert result is not None
                assert len(result) == 2
                assert "compute01-1" in result
                assert "compute01-2" in result

                # ===== 断言：NetworkService =====
                mock_network_instance.vm_deploy.assert_called_once()

                # ===== 断言：任务状态和参数更新 =====
                mock_task.update_task_status.assert_any_call("task-123", "running")
                mock_task.update_task_status.assert_any_call("task-123", "failed")  # 没有成功的VM，任务状态应为failed
                mock_task.update_task_params.assert_called_once()

                # 验证任务参数是否正确
                call_args = mock_task.update_task_params.call_args
                assert call_args[0][0] == "task-123"
                task_params = call_args[0][1]
                assert task_params["success_vms"] == []  # 成功列表为空
                assert set(task_params["fail_vms"]) == {"compute01-1", "compute01-2"}  # 所有VM都视为失败
                assert set(task_params["total_vms"]) == {"compute01-1", "compute01-2"}

                # ===== 断言：所有VM的IP都被释放 =====
                assert ip_allocator.release.call_count == 1

                # ===== 断言：没有VM写入数据库 =====
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 0