#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import logging
import uuid
import json
from typing import List, Dict
from datetime import datetime

from virtcca_deploy.services.db_service import Task, db


class TaskService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def create_task(self, task_type: str, task_params) -> str:
        """
        创建任务
        :param task_type: 任务类型，如 'vm-create', 'vm-delete'
        :param task_params: 任务参数，支持结构字典
        :return: 任务ID
        """
        try:
            task_id = str(uuid.uuid4())
            
            task = Task(
                task_id=task_id,
                task_type=task_type,
                status="created"
            )
            task.set_task_params(task_params.copy())
            
            db.session.add(task)
            db.session.commit()
            
            self.logger.info(f"Created task {task_id} of type {task_type}")
            return task_id
        except Exception as e:
            self.logger.error(f"Failed to create task: {e}")
            db.session.rollback()
            raise

    def get_task(self, task_id: str) -> Task:
        """
        获取任务
        :param task_id: 任务ID
        :return: 任务对象
        """
        try:
            task = Task.query.filter_by(task_id=task_id).first()
            return task
        except Exception as e:
            self.logger.error(f"Failed to get task {task_id}: {e}")
            raise

    def update_task_status(self, task_id: str, status: str) -> bool:
        """
        更新任务状态
        :param task_id: 任务ID
        :param status: 新状态，如 'running', 'success', 'failed'
        :return: 是否更新成功
        """
        try:
            task = Task.query.filter_by(task_id=task_id).first()
            if task:
                task.status = status
                task.updated_at = datetime.now()
                
                # 如果任务完成，记录完成时间
                if status in ['success', 'failed']:
                    task.completed_at = datetime.now()
                
                db.session.commit()
                self.logger.info(f"Updated task {task_id} status to {status}")
                return True
            else:
                self.logger.warning(f"Task {task_id} not found")
                return False
        except Exception as e:
            self.logger.error(f"Failed to update task {task_id} status: {e}")
            db.session.rollback()
            return False

    def update_task_params(self, task_id: str, task_params) -> bool:
        """
        更新任务参数
        :param task_id: 任务ID
        :param task_params: 新的任务参数
        :return: 是否更新成功
        """
        try:
            task = Task.query.filter_by(task_id=task_id).first()
            if task:
                task.set_task_params(task_params.copy())
                task.updated_at = datetime.now()
                
                db.session.commit()
                self.logger.info(f"Updated task {task_id} parameters")
                return True
            else:
                self.logger.warning(f"Task {task_id} not found")
                return False
        except Exception as e:
            self.logger.error(f"Failed to update task {task_id} parameters: {e}")
            db.session.rollback()
            return False

    def get_tasks_by_status(self, status: str) -> List[Task]:
        """
        根据状态获取任务列表
        :param status: 任务状态
        :return: 任务列表
        """
        try:
            tasks = Task.query.filter_by(status=status).all()
            return tasks
        except Exception as e:
            self.logger.error(f"Failed to get tasks with status {status}: {e}")
            raise

    def get_tasks_by_type(self, task_type: str) -> List[Task]:
        """
        根据类型获取任务列表
        :param task_type: 任务类型
        :return: 任务列表
        """
        try:
            tasks = Task.query.filter_by(task_type=task_type).all()
            return tasks
        except Exception as e:
            self.logger.error(f"Failed to get tasks with type {task_type}: {e}")
            raise


# 创建全局服务实例的引用
_task_service_instance = None

def get_task_service():
    """获取任务服务实例"""
    global _task_service_instance
    return _task_service_instance

def init_task_service():
    """初始化任务服务实例"""
    global _task_service_instance
    _task_service_instance = TaskService()
    return _task_service_instance