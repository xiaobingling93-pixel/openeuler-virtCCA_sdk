#!/usr/bin
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import logging
from typing import List, Tuple, Dict
from dataclasses import asdict
from http import HTTPStatus

from gevent import monkey
import gevent

# 确保猴子补丁已应用
monkey.patch_all()

from flask import current_app

from virtcca_deploy.common.constants import COMPUTE_PORT
from virtcca_deploy.common.data_model import VmDeploySpecInternal, VmDeploySpec
from virtcca_deploy.services.db_service import ComputeNode, VmInstance, VmDeploySpecModel, db
from virtcca_deploy.services.network_service import NetworkService
from virtcca_deploy.services.task_service import get_task_service


class VmService:
    def __init__(self, ssl_cert, vlan_pool_manager):
        self.ssl_cert = ssl_cert
        self.vlan_pool_manager = vlan_pool_manager
        self.logger = logging.getLogger(__name__)

    def execute_deployment(self, deploy_nodes: List[ComputeNode],
                           deploy_config: VmDeploySpecModel, vm_id_dict: Dict) -> Dict:
        vm_instances = {}
        node_task = {}
        
        task_service = get_task_service()
        
        # Create individual tasks for each node
        for node in deploy_nodes:
            # Generate all VM names for this node
            cvm_spec_internal = VmDeploySpecInternal.from_db_model(deploy_config)
            cvm_spec_internal.vm_id_list = [f"{node.nodename}-{i + 1}" for i in range(cvm_spec_internal.vm_spec.max_vm_num)]
            
            try:
                instance_task_id = task_service.create_task("vm-create", {"total_vms": cvm_spec_internal.vm_id_list})
                node_task[node.nodename] = instance_task_id
                
                for vm_name in cvm_spec_internal.vm_id_list:
                    # Record VM instance info in the response
                    vm_instances[vm_name] = {
                        "task_id": instance_task_id,
                        "host_ip": node.ip
                    }
            except Exception as e:
                self.logger.error(f"Failed to create instance task for node {node.nodename}: {e}")
                continue
        
        def deploy_node_async(node: ComputeNode, node_task_id: str, cvm_spec_internal: VmDeploySpecInternal, app):
            with app.app_context():
                try:
                    # Allocate IP for this node specifically

                    task_service.update_task_status(node_task_id, "running")
                    
                    # Perform actual deployment
                    compute_link = NetworkService(
                        node.nodename, COMPUTE_PORT, True, self.ssl_cert
                    )
                    result = compute_link.vm_deploy(cvm_spec_internal.to_dict())
                    all_vms = cvm_spec_internal.vm_id_list
                    success_vms = []
                    fail_vms = []
                    if result.status_code == HTTPStatus.OK:
                        try:
                            response_data = result.json()
                            if response_data and "data" in response_data:
                                success_vms = response_data["data"]
                                if not isinstance(success_vms, list):
                                    success_vms = []
                        except Exception as e:
                            self.logger.error(f"Failed to parse deployment result: {e}")
                            success_vms = []
                        
                        success_vms_set = set(success_vms)
                        fail_vms = [vm for vm in all_vms if vm not in success_vms_set]
                        
                        task_params = {
                            "success_vms": success_vms,
                            "fail_vms": fail_vms,
                            "total_vms": all_vms
                        }
                        task_service.update_task_params(node_task_id, task_params)
                        
                        if len(fail_vms) == 0:
                            task_service.update_task_status(node_task_id, "success")
                        else:
                            task_service.update_task_status(node_task_id, "failed")
                        
                        # 只记录成功部署的VM到数据库
                        for vm_name in success_vms:
                            # 获取IP列表，如果没有分配IP则使用空字符串
                            ips = cvm_spec_internal.vm_ip_dict.get(vm_name, []) if cvm_spec_internal.vm_ip_dict else []
                            ip_list_str = ",".join(ips) if ips else ""

                            # Create VM instance record
                            vm_instance = VmInstance(
                                vm_id=vm_name,
                                host_ip=node.ip,
                                host_name=node.nodename,
                                vm_spec_uuid=cvm_spec_internal.vm_spec.uuid,
                                ip_list=ip_list_str,
                                os_version="openEuler-2403LTS-SP2"
                            )
                        
                            try:
                                db.session.add(vm_instance)
                                db.session.commit()
                                self.logger.info(f"Successfully recorded VM {vm_name} in database for node {node.ip}")
                            except Exception as e:
                                self.logger.error(f"Failed to record VM instance {vm_name} to database: {e}")
                                db.session.rollback()
                        
                        for vm_name in fail_vms:
                            self.vlan_pool_manager.release_ips_for_vm(node.ip, vm_name)
                    else:
                        fail_vms = all_vms
                        task_params = {
                            "success_vms": [],
                            "fail_vms": fail_vms,
                            "total_vms": all_vms
                        }
                        task_service.update_task_params(node_task_id, task_params)
                        task_service.update_task_status(node_task_id, "failed")

                        for vm_name in all_vms:
                            self.vlan_pool_manager.release_ips_for_vm(node.ip, vm_name)
                except Exception as e:
                    err_msg = f"Failed to deploy CVM at {node.ip}, error reason: {e}"
                    self.logger.error(err_msg)
                    
                    all_vms = cvm_spec_internal.vm_id_list
                    fail_vms = all_vms
                    
                    task_params = {
                        "success_vms": [],
                        "fail_vms": fail_vms,
                        "total_vms": all_vms
                    }
                    task_service.update_task_params(node_task_id, task_params)
                    task_service.update_task_status(node_task_id, "failed")
                    
                    for vm_name in all_vms:
                        self.vlan_pool_manager.release_ips_for_vm(node.ip, vm_name)
        
        node_to_spec = {}
        for node in deploy_nodes:
            if node.nodename in node_task:
                # 创建新的实例，避免引用问题
                node_spec = VmDeploySpecInternal.from_db_model(deploy_config)
                node_spec.vm_id_list = [f"{node.nodename}-{i + 1}" for i in range(node_spec.vm_spec.max_vm_num)]
                node_to_spec[node.nodename] = node_spec
        
        # Start deployment asynchronously for all nodes
        jobs = []
        for node in deploy_nodes:
            if node.nodename in node_task:  # 只处理任务创建成功的节点
                jobs.append(gevent.spawn(
                    deploy_node_async, 
                    node, 
                    node_task[node.nodename], 
                    node_to_spec[node.nodename],
                    current_app._get_current_object()
                ))
        
        return vm_instances

    def execute_undeployment(self, deploy_nodes: List[ComputeNode], vm_id_list: List[str]) -> Dict:
        vm_instances = {}
        node_task = {}
        
        task_service = get_task_service()
        
        # Step 1: If no nodes provided, find nodes based on VM IDs
        if not deploy_nodes:
            try:
                # 查询所有VM ID对应的节点IP
                vm_instances_db = VmInstance.query.filter(VmInstance.vm_id.in_(vm_id_list)).all()
                if not vm_instances_db:
                    self.logger.warning(f"No VM instances found for IDs: {vm_id_list}")
                    return vm_instances
                
                # 按节点分组VM IDs
                node_vm_map = {}
                for vm in vm_instances_db:
                    if vm.host_ip not in node_vm_map:
                        node_vm_map[vm.host_ip] = []
                    node_vm_map[vm.host_ip].append(vm.vm_id)
                
                # 根据IP获取节点对象
                deploy_nodes = []
                for host_ip in node_vm_map.keys():
                    node = ComputeNode.query.filter_by(ip=host_ip).first()
                    if node:
                        deploy_nodes.append(node)
                    else:
                        self.logger.warning(f"Node not found for IP: {host_ip}")
            except Exception as e:
                self.logger.error(f"Failed to find nodes for VM IDs: {e}")
                return vm_instances
        
        # Step 2: Create individual tasks for each node
        for node in deploy_nodes:
            try:
                # Find VMs on this specific node
                node_vm_ids = []
                for vm_id in vm_id_list:
                    if VmInstance.query.filter_by(vm_id=vm_id, host_ip=node.ip).first():
                        node_vm_ids.append(vm_id)
                
                if not node_vm_ids:
                    self.logger.info(f"No VMs found on node {node.nodename} for undeployment")
                    continue
                
                instance_task_id = task_service.create_task("vm-delete", {"total_vms": node_vm_ids})
                node_task[node.nodename] = instance_task_id
                
                for vm_name in node_vm_ids:
                    # Record VM instance info in the response
                    vm_instances[vm_name] = {
                        "task_id": instance_task_id,
                        "host_ip": node.ip
                    }
            except Exception as e:
                self.logger.error(f"Failed to create undeployment task for node {node.nodename}: {e}")
                continue
        
        def undeploy_node_async(node, node_task_id: str, node_vm_ids: List[str], app):
            with app.app_context():
                try:
                    task_service.update_task_status(node_task_id, "running")
                    
                    # Perform actual undeployment
                    compute_link = NetworkService(
                        node.nodename, COMPUTE_PORT, True, self.ssl_cert
                    )
                    result = compute_link.vm_undeploy(node_vm_ids)
                    self.logger.info(f"Undeployment result for node {node.nodename}: {result}")
                    
                    success_vm_ids = []
                    failed_vm_ids = []
                    
                    if result.status_code == HTTPStatus.OK:
                        try:
                            response_data = result.json()
                            # 检查是否有部分卸载失败的情况
                            if response_data.get("data") and "failed_undeploy_cvm" in response_data["data"]:
                                failed_vm_ids = response_data["data"]["failed_undeploy_cvm"]
                                if not isinstance(failed_vm_ids, list):
                                    failed_vm_ids = []
                                
                                # 成功卸载的虚机是总列表减去失败列表
                                success_vm_ids = [vm_id for vm_id in node_vm_ids if vm_id not in failed_vm_ids]
                                
                                # 更新任务参数，包含成功和失败的虚机信息
                                task_params = {
                                    "success_vms": success_vm_ids,
                                    "fail_vms": failed_vm_ids,
                                    "total_vms": node_vm_ids
                                }
                                
                                # 如果有失败的虚机，任务状态设为失败
                                if failed_vm_ids:
                                    task_service.update_task_status(node_task_id, "failed")
                                    self.logger.warning(f"Partial undeployment failed on node {node.nodename}: "
                                                    f"successful={success_vm_ids}, failed={failed_vm_ids}")
                                else:
                                    task_service.update_task_status(node_task_id, "success")
                                    self.logger.info(f"All VMs undeployed successfully on node {node.nodename}")
                            
                            else:
                                # 如果没有failed_undeploy_cvm字段，则认为全部成功
                                success_vm_ids = node_vm_ids
                                task_params = {
                                    "success_vms": success_vm_ids,
                                    "fail_vms": [],
                                    "total_vms": node_vm_ids
                                }
                                task_service.update_task_status(node_task_id, "success")
                                self.logger.info(f"All VMs undeployed successfully on node {node.nodename}")
                            
                            # 更新任务参数
                            task_service.update_task_params(node_task_id, task_params)
                            
                        except Exception as e:
                            self.logger.error(f"Failed to parse undeployment result: {e}")
                            # 如果解析失败，保守处理：认为全部失败
                            failed_vm_ids = node_vm_ids
                            task_params = {
                                "success_vms": [],
                                "fail_vms": failed_vm_ids,
                                "total_vms": node_vm_ids
                            }
                            task_service.update_task_params(node_task_id, task_params)
                            task_service.update_task_status(node_task_id, "failed")
                    else:
                        # HTTP请求失败，认为全部卸载失败
                        failed_vm_ids = node_vm_ids
                        task_params = {
                            "success_vms": [],
                            "fail_vms": failed_vm_ids,
                            "total_vms": node_vm_ids
                        }
                        task_service.update_task_params(node_task_id, task_params)
                        task_service.update_task_status(node_task_id, "failed")
                        self.logger.error(f"Undeployment request failed for node {node.nodename}: {result.status_code}")
                    
                    # Process successful undeployments (only for successfully undeployed VMs)
                    if success_vm_ids:
                        self.logger.info(f"Releasing IPs for successfully undeployed VMs on {node.ip}: {success_vm_ids}")
                        for vm_id in success_vm_ids:
                            try:
                                # Release IPs
                                self.vlan_pool_manager.release_ips_for_vm(node.ip, vm_id)
                                
                                # Delete VM from database
                                db_vm_instances = VmInstance.query.filter_by(
                                    vm_id=vm_id,
                                    host_ip=node.ip
                                ).all()
                                
                                for vm_instance in db_vm_instances:
                                    db.session.delete(vm_instance)
                                
                                db.session.commit()
                                self.logger.info(f"Successfully deleted {len(db_vm_instances)} VM instances from database for VM ID {vm_id}")
                            except Exception as e:
                                self.logger.error(f"Failed to process undeployment cleanup for VM {vm_id} on {node.ip}: {e}")
                                db.session.rollback()
                    
                    # 对于卸载失败的虚机，记录日志但不进行清理操作
                    if failed_vm_ids:
                        self.logger.warning(f"The following VMs failed to undeploy on node {node.ip}: {failed_vm_ids}. "
                                        f"IP addresses and database records are preserved.")
                        
                except Exception as e:
                    err_msg = f"Failed to undeploy VMs at {node.ip}, error reason: {e}"
                    self.logger.error(err_msg)
                    
                    # Update task status to failed and mark all VMs as failed
                    task_params = {
                        "success_vms": [],
                        "fail_vms": node_vm_ids,
                        "total_vms": node_vm_ids
                    }
                    task_service.update_task_params(node_task_id, task_params)
                    task_service.update_task_status(node_task_id, "failed")
        
        # Start undeployment asynchronously for all nodes
        jobs = []
        for node in deploy_nodes:
            if node.nodename in node_task:
                # Get node-specific VM IDs again
                node_vm_ids = []
                for vm_id in vm_id_list:
                    if VmInstance.query.filter_by(vm_id=vm_id, host_ip=node.ip).first():
                        node_vm_ids.append(vm_id)
                
                if node_vm_ids:
                    jobs.append(gevent.spawn(
                        undeploy_node_async, 
                        node, 
                        node_task[node.nodename], 
                        node_vm_ids,
                        current_app._get_current_object()
                    ))
        
        # Return immediate response with task information, same format as deployment
        return vm_instances


_vm_service_instance = None

def get_vm_service():
    """获取VM服务实例"""
    global _vm_service_instance
    return _vm_service_instance

def init_vm_service(ssl_cert, vlan_pool_manager):
    """初始化VM服务实例"""
    global _vm_service_instance
    _vm_service_instance = VmService(ssl_cert, vlan_pool_manager)
    return _vm_service_instance
