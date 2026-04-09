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
from virtcca_deploy.services.task_service import TaskService, init_task_service, get_task_service
import virtcca_deploy.common.constants as constants


class TestTaskService:
    def test_create_task(self, app):
        """测试创建任务"""
        with app.app_context():
            # 初始化任务服务
            init_task_service()
            task_service = get_task_service()
            
            # 创建任务
            task_params = ["vm-1", "vm-2"]
            task_id = task_service.create_task("vm-create", task_params)
            
            # 验证任务创建成功
            assert task_id is not None
            assert isinstance(task_id, str)
            
            # 获取任务并验证参数
            task = task_service.get_task(task_id)
            assert task is not None
            assert task.task_id == task_id
            assert task.task_type == "vm-create"
            assert task.status == "created"
            assert json.loads(task.task_params) == task_params
    
    def test_get_task(self, app):
        """测试获取任务"""
        with app.app_context():
            # 初始化任务服务
            init_task_service()
            task_service = get_task_service()
            
            # 创建任务
            task_params = ["vm-1"]
            task_id = task_service.create_task("vm-create", task_params)
            
            # 获取任务
            task = task_service.get_task(task_id)
            
            # 验证任务信息
            assert task is not None
            assert task.task_id == task_id
            assert task.task_type == "vm-create"
            
            # 测试获取不存在的任务
            non_existent_task = task_service.get_task("non-existent-task-id")
            assert non_existent_task is None
    
    def test_update_task_status(self, app):
        """测试更新任务状态"""
        with app.app_context():
            # 初始化任务服务
            init_task_service()
            task_service = get_task_service()
            
            # 创建任务
            task_params = ["vm-1"]
            task_id = task_service.create_task("vm-create", task_params)
            
            # 更新任务状态为running
            result = task_service.update_task_status(task_id, "running")
            assert result is True
            
            # 验证状态更新
            task = task_service.get_task(task_id)
            assert task.status == "running"
            
            # 更新任务状态为success
            result = task_service.update_task_status(task_id, "success")
            assert result is True
            
            # 验证状态更新
            task = task_service.get_task(task_id)
            assert task.status == "success"
            assert task.completed_at is not None
            
            # 测试更新不存在的任务
            result = task_service.update_task_status("non-existent-task-id", "failed")
            assert result is False
    
    def test_update_task_results(self, app):
        """测试更新任务结果"""
        with app.app_context():
            # 初始化任务服务
            init_task_service()
            task_service = get_task_service()
            
            # 创建任务
            task_params = ["vm-1"]
            task_id = task_service.create_task("vm-create", task_params)
            
            # 更新任务结果
            results = {"success": True, "message": "Deployment completed"}
            result = task_service.update_task_results(task_id, results)
            assert result is True
            
            # 验证结果更新
            task = task_service.get_task(task_id)
            assert json.loads(task.results) == results
            
            # 测试更新不存在的任务
            result = task_service.update_task_results("non-existent-task-id", results)
            assert result is False
    
    def test_get_tasks_by_status(self, app):
        """测试根据状态获取任务列表"""
        with app.app_context():
            # 初始化任务服务
            init_task_service()
            task_service = get_task_service()
            
            # 创建不同状态的任务
            task_service.create_task("vm-create", ["vm-1"])
            task_id_running = task_service.create_task("vm-create", ["vm-2"])
            task_id_success = task_service.create_task("vm-delete", ["vm-3"])
            
            # 更新任务状态
            task_service.update_task_status(task_id_running, "running")
            task_service.update_task_status(task_id_success, "success")
            
            # 获取不同状态的任务
            created_tasks = task_service.get_tasks_by_status("created")
            running_tasks = task_service.get_tasks_by_status("running")
            success_tasks = task_service.get_tasks_by_status("success")
            
            # 验证结果
            assert len(created_tasks) == 1
            assert len(running_tasks) == 1
            assert len(success_tasks) == 1
    
    def test_get_tasks_by_type(self, app):
        """测试根据类型获取任务列表"""
        with app.app_context():
            # 初始化任务服务
            init_task_service()
            task_service = get_task_service()
            
            # 创建不同类型的任务
            task_service.create_task("vm-create", ["vm-1"])
            task_service.create_task("vm-create", ["vm-2"])
            task_service.create_task("vm-delete", ["vm-3"])
            
            # 获取不同类型的任务
            create_tasks = task_service.get_tasks_by_type("vm-create")
            delete_tasks = task_service.get_tasks_by_type("vm-delete")
            
            # 验证结果
            assert len(create_tasks) == 2
            assert len(delete_tasks) == 1