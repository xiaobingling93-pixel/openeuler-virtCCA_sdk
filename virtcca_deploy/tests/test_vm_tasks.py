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

import pytest
from unittest.mock import patch, MagicMock
import virtcca_deploy.common.constants as constants


class TestVmTasksEndpoint:
    def test_get_vm_tasks_valid_id(self, authenticated_client, app):
        """测试使用有效的单个任务ID查询"""
        # 模拟Task对象
        mock_task = MagicMock()
        mock_task.task_id = "task-123"
        mock_task.task_type = "vm-create"
        mock_task.status = "running"
        mock_task.get_task_params.return_value = {
            "total_vms": ["compute01-1", "compute01-2"],
            "success_vms": ["compute01-1", "compute01-2"],
            "fail_vms": []
        }
        # 模拟task_service.get_task方法
        with patch('virtcca_deploy.services.task_service.get_task_service') as mock_get_task_service:
            mock_task_service = MagicMock()
            mock_task_service.get_task.return_value = mock_task
            mock_get_task_service.return_value = mock_task_service
            
            response = authenticated_client.get(
                f"{constants.ROUTE_VM_TASKS}?task_id={mock_task.task_id}"
            )
            
            assert response.status_code == HTTPStatus.OK
            
            data = response.json.get("data", {})
            print(data)
            assert mock_task.task_id in data["task_id"]
            assert data["type"] == mock_task.task_type
            assert data["status"] == mock_task.status
            assert "params" in data
            assert data["params"]["total_vms"] == ["compute01-1", "compute01-2"]
            assert data["params"]["success_vms"] == ["compute01-1", "compute01-2"]
            assert data["params"]["fail_vms"] == []
    
    def test_get_vm_tasks_invalid_id(self, authenticated_client, app):
        """测试使用无效的任务ID查询"""
        with patch('virtcca_deploy.services.task_service.get_task_service') as mock_get_task_service:
            mock_task_service = MagicMock()
            mock_task_service.get_task.return_value = None
            mock_get_task_service.return_value = mock_task_service
            
            response = authenticated_client.get(
                f"{constants.ROUTE_VM_TASKS}?task_id=invalid-task-id"
            )
            
            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert response.json.get("data") == None
    
    def test_get_vm_tasks_missing_param(self, authenticated_client):
        """测试缺失task_id参数"""
        response = authenticated_client.get(constants.ROUTE_VM_TASKS)
        
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Invalid task id" in response.json.get("message", "")
    
    def test_get_vm_tasks_empty_param(self, authenticated_client):
        """测试空的task_id参数"""
        response = authenticated_client.get(f"{constants.ROUTE_VM_TASKS}?task_id=")
        
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Invalid task id" in response.json.get("message", "")