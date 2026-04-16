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
from virtcca_deploy.services.vm_service import VmService
from virtcca_deploy.services.task_service import init_task_service

class TestVmServiceUndeployment:
    def test_execute_undeployment_success(self, app):
        with app.app_context():
            init_task_service()

            SimpleIpAllocator = MagicMock()
            vm_service = VmService(None, SimpleIpAllocator)

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

            # 创建测试虚拟机实例
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

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                mock_task = MagicMock()
                mock_task.create_task.return_value = "task-undeploy-123"
                mock_get_task_service.return_value = mock_task

                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_network_instance.vm_undeploy.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # Mock gevent → 同步执行
                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                result = vm_service.execute_undeployment([node], ["compute01-1", "compute01-2"])

                assert result is not None
                assert len(result) == 2

                assert "compute01-1" in result
                assert "compute01-2" in result

                assert mock_task.create_task.called
                assert mock_task.update_task_status.called

                mock_network_service.assert_called_once()
                mock_network_instance.vm_undeploy.assert_called_once()

                # 验证IP释放
                assert SimpleIpAllocator.release.call_count == 1

                # 验证数据库中虚拟机已被删除
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 0

    def test_execute_undeployment_failure(self, app):
        with app.app_context():
            init_task_service()

            SimpleIpAllocator = MagicMock()
            vm_service = VmService(None, SimpleIpAllocator)

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

            # 创建测试虚拟机实例
            vm1 = VmInstance(
                vm_id="compute01-1",
                host_ip=node.ip,
                host_name=node.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.10"
            )
            db.session.add(vm1)
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                mock_task = MagicMock()
                mock_task.create_task.return_value = "task-undeploy-123"
                mock_get_task_service.return_value = mock_task

                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_network_instance.vm_undeploy.return_value = {
                    "data": ["compute01-1"],
                    "message": "Undeployment failed"
                }
                mock_network_service.return_value = mock_network_instance

                # Mock gevent → 同步执行
                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                result = vm_service.execute_undeployment([node], ["compute01-1"])

                assert result is not None
                assert len(result) == 1

                assert mock_task.create_task.called
                # 验证任务状态更新为failed
                mock_task.update_task_status.assert_any_call("task-undeploy-123", "failed")

                mock_network_service.assert_called_once()
                mock_network_instance.vm_undeploy.assert_called_once()

                # 验证IP未释放（因为卸载失败）
                SimpleIpAllocator.release.assert_not_called()

                # 验证数据库中虚拟机仍存在
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 1

    def test_execute_undeployment_task_creation_failure(self, app):
        with app.app_context():
            init_task_service()

            SimpleIpAllocator = MagicMock()
            vm_service = VmService(None, SimpleIpAllocator)

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

            # 创建测试虚拟机实例
            vm1 = VmInstance(
                vm_id="compute01-1",
                host_ip=node.ip,
                host_name=node.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.10"
            )
            db.session.add(vm1)
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service:

                mock_task = MagicMock()
                mock_task.create_task.side_effect = Exception("Task creation failed")
                mock_get_task_service.return_value = mock_task

                result = vm_service.execute_undeployment([node], ["compute01-1"])

                # 返回值
                assert result is not None
                assert len(result) == 0

                # 不应该调用 NetworkService
                mock_network_service.assert_not_called()

                # 虚拟机仍然存在于数据库中
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 1

    def test_execute_undeployment_multiple_nodes(self, app):
        with app.app_context():
            init_task_service()

            SimpleIpAllocator = MagicMock()
            vm_service = VmService(None, SimpleIpAllocator)

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

            # 在每个节点上创建虚拟机实例
            vm1 = VmInstance(
                vm_id="compute01-1",
                host_ip=node1.ip,
                host_name=node1.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.10"
            )
            vm2 = VmInstance(
                vm_id="compute02-1",
                host_ip=node2.ip,
                host_name=node2.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.11"
            )
            db.session.add_all([vm1, vm2])
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                mock_task = MagicMock()
                mock_task.create_task.side_effect = ["task-undeploy-1", "task-undeploy-2"]
                mock_get_task_service.return_value = mock_task

                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_network_instance.vm_undeploy.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # Mock gevent → 同步执行
                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                result = vm_service.execute_undeployment(
                    [node1, node2], 
                    ["compute01-1", "compute02-1"]
                )

                assert result is not None
                assert len(result) == 2

                assert "compute01-1" in result
                assert "compute02-1" in result

                # NetworkService 调用次数
                assert mock_network_service.call_count == 2
                assert mock_network_instance.vm_undeploy.call_count == 2

                # task 创建次数
                assert mock_task.create_task.call_count == 2

                # 验证IP释放
                assert SimpleIpAllocator.release.call_count == 2

                # 数据库验证（关键）
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 0

    def test_execute_undeployment_with_empty_nodes(self, app):
        with app.app_context():
            init_task_service()

            SimpleIpAllocator = MagicMock()
            vm_service = VmService(None, SimpleIpAllocator)

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

            # 在每个节点上创建虚拟机实例
            vm1 = VmInstance(
                vm_id="compute01-1",
                host_ip=node1.ip,
                host_name=node1.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.10"
            )
            vm2 = VmInstance(
                vm_id="compute02-1",
                host_ip=node2.ip,
                host_name=node2.nodename,
                vm_spec_uuid="spec-123",
                ip_list="192.168.1.11"
            )
            db.session.add_all([vm1, vm2])
            db.session.commit()

            with patch('virtcca_deploy.services.vm_service.get_task_service') as mock_get_task_service, \
                patch('virtcca_deploy.services.vm_service.NetworkService') as mock_network_service, \
                patch('virtcca_deploy.services.vm_service.gevent.spawn') as mock_spawn:

                mock_task = MagicMock()
                mock_task.create_task.side_effect = ["task-undeploy-1", "task-undeploy-2"]
                mock_get_task_service.return_value = mock_task

                mock_network_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_network_instance.vm_undeploy.return_value = mock_response
                mock_network_service.return_value = mock_network_instance

                # Mock gevent → 同步执行
                def sync_spawn(func, *args, **kwargs):
                    func(*args, **kwargs)
                    return MagicMock()

                mock_spawn.side_effect = sync_spawn

                # 传入空的nodes列表，测试自动节点查询功能
                result = vm_service.execute_undeployment([], ["compute01-1", "compute02-1"])

                assert result is not None
                assert len(result) == 2

                assert "compute01-1" in result
                assert "compute02-1" in result

                # NetworkService 调用次数
                assert mock_network_service.call_count == 2
                assert mock_network_instance.vm_undeploy.call_count == 2

                # task 创建次数
                assert mock_task.create_task.call_count == 2

                # 验证IP释放
                assert SimpleIpAllocator.release.call_count == 2

                # 数据库验证（关键）
                vm_list = VmInstance.query.all()
                assert len(vm_list) == 0