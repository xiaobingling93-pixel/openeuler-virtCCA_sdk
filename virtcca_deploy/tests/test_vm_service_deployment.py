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
from virtcca_deploy.common.data_model import VmDeploySpec
import virtcca_deploy.common.constants as constants

class TestVmServiceDeployment:
    def test_execute_deployment_success(self, app):
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            mock_vlan_pool_manager.allocate_vlan_ips.return_value = "192.168.1.10"

            vm_service = VmService(None, mock_vlan_pool_manager)

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

            deploy_spec = VmDeploySpec(vm_num=2, memory=4096, core_num=2, vlan_id=100)
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

                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_network_instance.vm_deploy.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # ===== Mock gevent → 同步执行 =====
                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                result = vm_service.execute_deployment([node], deploy_spec_model, {})

                assert result is not None
                assert len(result) == 2

                assert mock_task.create_task.called

                mock_task.update_task_status.assert_called_with("task-123", "success")

                mock_network_service.assert_called_once()
                mock_network_instance.vm_deploy.assert_called_once()

                vm_list = VmInstance.query.all()
                assert len(vm_list) == 2

                vm_ids = [vm.vm_id for vm in vm_list]
                assert "compute01-1" in vm_ids
                assert "compute01-2" in vm_ids

                for vm in vm_list:
                    assert vm.ip_list is not None
                    assert vm.host_ip == "192.168.1.100"

    def test_execute_deployment_failure(self, app):
        with app.app_context():
            init_task_service()

            # ===== Mock VLAN =====
            mock_vlan_pool_manager = MagicMock()
            mock_vlan_pool_manager.allocate_vlan_ips.return_value = "192.168.1.10"

            vm_service = VmService(None, mock_vlan_pool_manager)

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
            deploy_spec = VmDeploySpec(vm_num=1, memory=4096, core_num=2, vlan_id=100)
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

                # ===== Mock NetworkService → 失败 =====
                mock_network_instance = MagicMock()
                mock_network_instance.vm_deploy.return_value = {
                    "status": constants.OperationCodes.FAILED.value,
                    "message": "Deployment failed"
                }
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
                mock_task.update_task_status.assert_any_call("task-123", "failed")

                # ===== ⭐ 断言：IP释放 =====
                mock_vlan_pool_manager.release_ips_for_vm.assert_called()

                # ===== ⭐ 断言：数据库没有写入 =====
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 0
                
    def test_execute_deployment_task_creation_failure(self, app):
        with app.app_context():
            init_task_service()

            mock_vlan_pool_manager = MagicMock()
            vm_service = VmService(None, mock_vlan_pool_manager)

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

            deploy_spec = VmDeploySpec(vm_num=1, memory=4096, core_num=2, vlan_id=100)
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

            mock_vlan_pool_manager = MagicMock()
            mock_vlan_pool_manager.allocate_vlan_ips.return_value = "192.168.1.10"

            vm_service = VmService(None, mock_vlan_pool_manager)

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

            deploy_spec = VmDeploySpec(vm_num=2, memory=4096, core_num=2, vlan_id=100)
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
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_network_instance.vm_deploy.return_value = mock_response

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

                # ===== 数据库验证（关键） =====
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 4

                host_ips = set(vm.host_ip for vm in vm_list)
                assert host_ips == {"192.168.1.100", "192.168.1.101"}