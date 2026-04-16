#!/usr/bin
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import logging
from typing import List, Tuple, Dict
from http import HTTPStatus

from gevent import monkey
import gevent

# 确保猴子补丁已应用
monkey.patch_all()

from flask import current_app

from virtcca_deploy.common.constants import COMPUTE_PORT, TASK_TYPE_VM_CREATE, TASK_TYPE_VM_DELETE
from virtcca_deploy.common.data_model import (
    NetAllocReq, NetReleaseReq, VmDeploySpecInternal
)
from virtcca_deploy.services.db_service import ComputeNode, VmInstance, VmDeploySpecModel, db
from virtcca_deploy.services.network_service import NetworkService
from virtcca_deploy.services.task_service import get_task_service


class VmService:
    def __init__(self, ssl_cert, ip_allocator=None):
        self.ssl_cert = ssl_cert
        self.ip_allocator = ip_allocator
        self.logger = logging.getLogger(__name__)

    def execute_deployment(self, deploy_nodes: List[ComputeNode],
                           deploy_config: VmDeploySpecModel, vm_id_dict: Dict) -> Dict:
        vm_instances = {}
        node_task = {}
        
        task_service = get_task_service()
        
        # Create individual tasks for each node
        node_to_spec = {}
        for node in deploy_nodes:
            # Generate all VM names for this node
            cvm_spec_internal = VmDeploySpecInternal.from_db_model(deploy_config)
            cvm_spec_internal.vm_id_list = [f"{node.nodename}-{i + 1}" for i in range(cvm_spec_internal.vm_spec.max_vm_num)]

            if self.ip_allocator:
                try:
                    allocReq = NetAllocReq(cvm_spec_internal.vm_id_list,
                        cvm_spec_internal.vm_spec.vlan_id,
                        cvm_spec_internal.vm_spec.net_pf_num,
                        cvm_spec_internal.vm_spec.net_vf_num,
                        node.ip
                    )
                    allocResp = self.ip_allocator.allocate(request=allocReq)
                    if allocResp.success:
                        cvm_spec_internal.vm_ip_dict = allocResp.vm_ip_map
                    self.logger.info(f"Allocated IPs for node {node.nodename}: {cvm_spec_internal.vm_ip_dict}")
                except Exception as e:
                    self.logger.error(f"Failed to allocate IPs for node {node.nodename}: {e}")

            node_to_spec[node.nodename] = cvm_spec_internal

            try:
                instance_task_id = task_service.create_task(TASK_TYPE_VM_CREATE, {"total_vms": cvm_spec_internal.vm_id_list})
                node_task[node.nodename] = instance_task_id
                
                for vm_name in cvm_spec_internal.vm_id_list:
                    # Record VM instance info in the response
                    vm_instances[vm_name] = {
                        "task_id": instance_task_id,
                        "host_ip": node.ip
                    }
            except Exception as e:
                self.logger.error(f"Failed to create instance task for node {node.nodename}: {e}")
                self.ip_allocator.release(request=NetReleaseReq(cvm_spec_internal.vm_id_list))
                continue
        
        def deploy_node_async(node: ComputeNode, node_task_id: str, cvm_spec_internal: VmDeploySpecInternal, app):
            with app.app_context():
                fail_vms = []
                try:
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
                    else:
                        fail_vms = all_vms
                        task_params = {
                            "success_vms": [],
                            "fail_vms": fail_vms,
                            "total_vms": all_vms
                        }
                        task_service.update_task_params(node_task_id, task_params)
                        task_service.update_task_status(node_task_id, "failed")

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
                    
                if fail_vms:
                    self.ip_allocator.release(request=NetReleaseReq(fail_vms))
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
                
                instance_task_id = task_service.create_task(TASK_TYPE_VM_DELETE, {"total_vms": node_vm_ids})
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
                success_vms = []
                failed_vms = []
                try:
                    task_service.update_task_status(node_task_id, "running")
                    
                    # Perform actual undeployment
                    compute_link = NetworkService(
                        node.nodename, COMPUTE_PORT, True, self.ssl_cert
                    )
                    result = compute_link.vm_undeploy(node_vm_ids)
                    self.logger.info(f"Undeployment result for node {node.nodename}: {result}")
                    if result.status_code == HTTPStatus.OK:
                        try:
                            response_data = result.json()
                            # 检查是否有部分卸载失败的情况
                            if response_data.get("data") and "failed_undeploy_cvm" in response_data["data"]:
                                failed_vms = response_data["data"]["failed_undeploy_cvm"]
                                if not isinstance(failed_vms, list):
                                    failed_vms = []
                                
                                # 成功卸载的虚机是总列表减去失败列表
                                success_vms = [vm_id for vm_id in node_vm_ids if vm_id not in failed_vms]
                                
                                # 更新任务参数，包含成功和失败的虚机信息
                                task_params = {
                                    "success_vms": success_vms,
                                    "fail_vms": failed_vms,
                                    "total_vms": node_vm_ids
                                }
                                
                                # 如果有失败的虚机，任务状态设为失败
                                if failed_vms:
                                    task_service.update_task_status(node_task_id, "failed")
                                    self.logger.warning(f"Partial undeployment failed on node {node.nodename}: "
                                                    f"successful={success_vms}, failed={failed_vms}")
                                else:
                                    task_service.update_task_status(node_task_id, "success")
                                    self.logger.info(f"All VMs undeployed successfully on node {node.nodename}")
                            
                            else:
                                # 如果没有failed_undeploy_cvm字段，则认为全部成功
                                success_vms = node_vm_ids
                                task_params = {
                                    "success_vms": success_vms,
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
                            failed_vms = node_vm_ids
                            task_params = {
                                "success_vms": [],
                                "fail_vms": failed_vms,
                                "total_vms": node_vm_ids
                            }
                            task_service.update_task_params(node_task_id, task_params)
                            task_service.update_task_status(node_task_id, "failed")
                    else:
                        # HTTP请求失败，认为全部卸载失败
                        failed_vms = node_vm_ids
                        task_params = {
                            "success_vms": [],
                            "fail_vms": failed_vms,
                            "total_vms": node_vm_ids
                        }
                        task_service.update_task_params(node_task_id, task_params)
                        task_service.update_task_status(node_task_id, "failed")
                        self.logger.error(f"Undeployment request failed for node {node.nodename}: {result.status_code}")
                    
                    # Process successful undeployments (only for successfully undeployed VMs)
                    if success_vms:
                        self.logger.info(f"Releasing IPs for successfully undeployed VMs on {node.ip}: {success_vms}")
                        for vm_id in success_vms:
                            try:
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
                    if failed_vms:
                        self.logger.warning(f"The following VMs failed to undeploy on node {node.ip}: {failed_vms}. "
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

                if success_vms:
                    self.ip_allocator.release(request=NetReleaseReq(success_vms))
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
        
    def query_vm_states(self, nodes: List[str] = None, vm_ids: List[str] = None, 
                       page: int = 1, page_size: int = 10) -> Tuple[Dict, str]:
        """
        查询虚拟机状态
        
        :param nodes: 节点列表
        :param vm_ids: 虚拟机ID列表
        :param page: 页码
        :param page_size: 每页大小
        :return: (vm_info_result, message)
        """
        response_data = {
            "vm_info": {},
            "pagination": {
                "page": page,
                "page_size": page_size,
                "entry_num": 0,
                "total": 0
            }
        }
        try:
            # 构建查询条件
            query = VmInstance.query
            
            if nodes and len(nodes) > 0:
                # 根据节点名查询节点
                nodes_db = ComputeNode.query.filter(ComputeNode.nodename.in_(nodes)).all()
                if not nodes_db:
                    return response_data, "No nodes found"
                
                # 获取节点IP列表
                node_ips = [node.ip for node in nodes_db]
                query = query.filter(VmInstance.host_ip.in_(node_ips))
            elif vm_ids and len(vm_ids) > 0:
                query = query.filter(VmInstance.vm_id.in_(vm_ids))
            
            # 分页查询
            total_vms = query.count()
            offset = (page - 1) * page_size
            vm_instances = query.offset(offset).limit(page_size).all()
            
            if not vm_instances:
                return response_data, "No VM instances found"
            
            # 按主机IP分组VM实例
            vms_by_host = {}
            for vm in vm_instances:
                if vm.host_ip not in vms_by_host:
                    vms_by_host[vm.host_ip] = []
                vms_by_host[vm.host_ip].append(vm)
            
            # 获取相关节点信息
            host_ips = list(vms_by_host.keys())
            from virtcca_deploy.services.node_service import NodeService
            target_nodes, error_response = NodeService.get_nodes_by_ip_list(host_ips)
            if error_response:
                return response_data, error_response
            
            # 构建节点IP到节点对象的映射
            node_by_ip = {node.ip: node for node in target_nodes}
            
            # 收集所有VM的状态信息
            vm_info_result = {}
            failed_nodes = []
            
            for host_ip, vms in vms_by_host.items():
                node = node_by_ip.get(host_ip)
                if not node:
                    self.logger.warning(f"Node not found for host IP: {host_ip}")
                    # 对于找不到节点的VM，只返回数据库中的基本信息
                    for vm in vms:
                        vm_info_result[vm.vm_id] = {
                            "state": "UNKNOWN",
                            "create_at": vm.created_at.isoformat() + "Z" if vm.created_at else "",
                            "os": vm.os_version or "Unknown",
                            "ip_list": vm.ip_list.split(",") if vm.ip_list else [],
                            "mem_used": 0.0,
                            "host_ip": vm.host_ip
                        }
                    continue
                
                try:
                    # 查询计算节点的VM状态
                    compute_link = NetworkService(
                        node.nodename, COMPUTE_PORT, True, self.ssl_cert
                    )
                    result = compute_link.query_cvm_state()
                    self.logger.info(f"Response from node {node.ip}: {result.text if result else 'No response'}")
                    
                    if result and result.status_code == HTTPStatus.OK:
                        response_data = result.json()
                        self.logger.info(f"Parsed response data: {response_data}")
                        
                        if isinstance(response_data, dict):
                            node_vm_data = response_data.get("data", {})
                            self.logger.info(f"VM data from node: {node_vm_data}")
                            
                            vm_states = {}
                            if isinstance(node_vm_data, dict):
                                # 直接是字典格式，如 {'cvm-migvm1': 'SHUTOFF', 'cvm-nemoclaw-phc': 'SHUTOFF'}
                                vm_states = node_vm_data
                            elif isinstance(node_vm_data, str):
                                # 如果是字符串，尝试解析为JSON
                                import json
                                try:
                                    vm_states = json.loads(node_vm_data)
                                except json.JSONDecodeError:
                                    self.logger.error(f"Failed to parse VM data as JSON: {node_vm_data}")
                                    vm_states = {}
                            
                            # 合并数据库信息和状态信息
                            for vm in vms:
                                vm_state = vm_states.get(vm.vm_id, "UNKNOWN")
                                
                                vm_info_result[vm.vm_id] = {
                                    "state": vm_state,
                                    "create_at": vm.created_at.isoformat() + "Z" if vm.created_at else "",
                                    "os": vm.os_version or "Unknown",
                                    "ip_list": vm.ip_list.split(",") if vm.ip_list else [],
                                    "mem_used": 0.0,  # 从节点返回的数据中没有内存使用信息，使用默认值
                                    "host_ip": vm.host_ip
                                }
                        else:
                            # 非标准响应格式，直接使用整个响应作为VM状态数据
                            self.logger.warning(f"Non-standard response format from node {node.ip}")
                            vm_states = response_data if isinstance(response_data, dict) else {}
                            
                            for vm in vms:
                                vm_state = vm_states.get(vm.vm_id, "UNKNOWN")
                                
                                vm_info_result[vm.vm_id] = {
                                    "state": vm_state,
                                    "create_at": vm.created_at.isoformat() + "Z" if vm.created_at else "",
                                    "os": vm.os_version or "Unknown",
                                    "ip_list": vm.ip_list.split(",") if vm.ip_list else [],
                                    "mem_used": 0.0,
                                    "host_ip": vm.host_ip
                                }
                    else:
                        # 网络请求失败
                        status_code = getattr(result, 'status_code', 'Unknown')
                        self.logger.error(f"Failed to query CVM state from node {node.ip}, status code: {status_code}")
                        failed_nodes.append(node.ip)
                        for vm in vms:
                            vm_info_result[vm.vm_id] = {
                                "state": "UNKNOWN",
                                "create_at": vm.created_at.isoformat() + "Z" if vm.created_at else "",
                                "os": vm.os_version or "Unknown",
                                "ip_list": vm.ip_list.split(",") if vm.ip_list else [],
                                "mem_used": 0.0,
                                "host_ip": vm.host_ip
                            }
                            
                except Exception as e:
                    err_msg = f"Failed to query CVM at {node.ip}, error reason: {e}"
                    self.logger.error(err_msg)
                    failed_nodes.append(node.ip)
                    for vm in vms:
                        vm_info_result[vm.vm_id] = {
                            "state": "UNKNOWN",
                            "create_at": vm.created_at.isoformat() + "Z" if vm.created_at else "",
                            "os": vm.os_version or "Unknown",
                            "ip_list": vm.ip_list.split(",") if vm.ip_list else [],
                            "mem_used": 0.0,
                            "host_ip": vm.host_ip
                        }
            
            # 构建响应数据
            response_data = {
                "vm_info": vm_info_result,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "entry_num": len(vm_instances),
                    "total": total_vms
                }
            }
            
            if failed_nodes:
                message = f"Successfully queried VM state, but failed to get real-time status from nodes: {failed_nodes}"
            else:
                message = "Successfully queried VM state from all nodes"
            
            return response_data, message
            
        except Exception as e:
            self.logger.error(f"Unexpected error while querying VM state: {e}")
            return response_data, f"Internal server error: {str(e)}"


_vm_service_instance = None

def get_vm_service():
    """获取VM服务实例"""
    global _vm_service_instance
    return _vm_service_instance

def init_vm_service(ssl_cert, ip_allocator=None):
    """初始化VM服务实例"""
    global _vm_service_instance
    _vm_service_instance = VmService(ssl_cert, ip_allocator)
    return _vm_service_instance
