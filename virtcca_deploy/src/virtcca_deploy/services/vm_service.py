#!/usr/bin
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import logging
from typing import List, Tuple, Dict, Optional
from http import HTTPStatus
import json
from dataclasses import dataclass

from gevent import monkey
import gevent

# 确保猴子补丁已应用
monkey.patch_all()

from flask import current_app

from virtcca_deploy.common.constants import COMPUTE_PORT, TASK_TYPE_VM_CREATE, TASK_TYPE_VM_DELETE, TASK_TYPE_VM_STOP, TASK_TYPE_VM_START
from virtcca_deploy.common.data_model import (
    NetAllocReq, NetReleaseReq, VmDeploySpecInternal
)
from virtcca_deploy.services.db_service import ComputeNode, VmInstance, VmDeploySpecModel, db
from virtcca_deploy.services.network_service import NetworkService
from virtcca_deploy.services.task_service import get_task_service
from virtcca_deploy.services.dao import get_dao_registry
import virtcca_deploy.services.util_service as util_service


@dataclass
class DeploymentConflict:
    node_name: str
    node_ip: str
    conflict_type: str
    details: str


class PreDeploymentChecker:
    def __init__(self, logger):
        self.logger = logger

    def check_nodes(self, nodes: List[ComputeNode]) -> Tuple[bool, List[DeploymentConflict]]:
        conflicts = []
        for node in nodes:
            vm_conflict = self._check_existing_vms(node)
            if vm_conflict:
                conflicts.append(vm_conflict)

            task_conflict = self._check_ongoing_tasks(node)
            if task_conflict:
                conflicts.append(task_conflict)

        has_conflicts = len(conflicts) > 0
        return has_conflicts, conflicts

    def check_nodes_with_vm_ids(self, nodes: List[ComputeNode],
                                 vm_id_dict: Dict) -> Tuple[bool, List[DeploymentConflict]]:
        conflicts = []
        for node in nodes:
            if node.nodename not in vm_id_dict:
                continue

            requested_vm_ids = vm_id_dict[node.nodename]

            vm_conflict = self._check_existing_vms_by_ids(node, requested_vm_ids)
            if vm_conflict:
                conflicts.append(vm_conflict)

            task_conflict = self._check_ongoing_tasks_by_ids(node, requested_vm_ids)
            if task_conflict:
                conflicts.append(task_conflict)

        has_conflicts = len(conflicts) > 0
        return has_conflicts, conflicts

    def _check_existing_vms(self, node: ComputeNode) -> Optional[DeploymentConflict]:
        try:
            vm_instance_dao = get_dao_registry().vm_instance_dao
            existing_vms = vm_instance_dao.get_by_host_ip(node.ip)
            if existing_vms:
                vm_ids = [vm.vm_id for vm in existing_vms[:5]]
                details = f"Found {len(existing_vms)} deployed VMs: {', '.join(vm_ids)}"
                return DeploymentConflict(
                    node_name=node.nodename,
                    node_ip=node.ip,
                    conflict_type="existing_vms",
                    details=details
                )
        except Exception as e:
            self.logger.error(f"Failed to check existing VMs on node {node.nodename}: {e}")
        return None

    def _check_existing_vms_by_ids(self, node: ComputeNode,
                                    vm_ids: List[str]) -> Optional[DeploymentConflict]:
        try:
            vm_instance_dao = get_dao_registry().vm_instance_dao
            existing_vms = vm_instance_dao.get_by_vm_ids(vm_ids)

            conflict_vm_ids = []
            for vm in existing_vms:
                if vm.host_ip == node.ip:
                    conflict_vm_ids.append(vm.vm_id)

            if conflict_vm_ids:
                details = (
                    f"VM IDs already deployed on this node: {', '.join(conflict_vm_ids)}"
                )
                return DeploymentConflict(
                    node_name=node.nodename,
                    node_ip=node.ip,
                    conflict_type="existing_vms",
                    details=details
                )
        except Exception as e:
            self.logger.error(
                f"Failed to check existing VMs by IDs on node {node.nodename}: {e}"
            )
        return None

    def _check_ongoing_tasks(self, node: ComputeNode) -> Optional[DeploymentConflict]:
        try:
            task_service = get_task_service()
            pending_tasks = task_service.get_tasks_by_status("created")
            running_tasks = task_service.get_tasks_by_status("running")

            active_tasks = [t for t in pending_tasks + running_tasks
                           if t.task_type == TASK_TYPE_VM_CREATE]

            if active_tasks:
                task_ids = [t.task_id for t in active_tasks[:3]]
                details = f"Found {len(active_tasks)} ongoing deployment tasks: {', '.join(task_ids)}"
                return DeploymentConflict(
                    node_name=node.nodename,
                    node_ip=node.ip,
                    conflict_type="ongoing_deployment_task",
                    details=details
                )
        except Exception as e:
            self.logger.error(f"Failed to check ongoing tasks on node {node.nodename}: {e}")
        return None

    def _check_ongoing_tasks_by_ids(self, node: ComputeNode,
                                     vm_ids: List[str]) -> Optional[DeploymentConflict]:
        try:
            task_service = get_task_service()
            pending_tasks = task_service.get_tasks_by_status("created")
            running_tasks = task_service.get_tasks_by_status("running")

            active_tasks = [t for t in pending_tasks + running_tasks
                           if t.task_type == TASK_TYPE_VM_CREATE]

            conflict_task_ids = []
            for task in active_tasks:
                task_params = task.get_task_params()
                if task_params and "total_vms" in task_params:
                    total_vms = task_params["total_vms"]
                    if isinstance(total_vms, list):
                        matching_vms = [vm_id for vm_id in total_vms if vm_id in vm_ids]
                        if matching_vms:
                            conflict_task_ids.append({
                                "task_id": task.task_id,
                                "matching_vms": matching_vms
                            })

            if conflict_task_ids:
                task_details = []
                for item in conflict_task_ids[:3]:
                    vms_str = ", ".join(item["matching_vms"])
                    task_details.append(f"Task {item['task_id']} ({vms_str})")

                details = (
                    f"VM IDs are being deployed in ongoing tasks: {'; '.join(task_details)}"
                )
                return DeploymentConflict(
                    node_name=node.nodename,
                    node_ip=node.ip,
                    conflict_type="ongoing_deployment_task",
                    details=details
                )
        except Exception as e:
            self.logger.error(
                f"Failed to check ongoing tasks by IDs on node {node.nodename}: {e}"
            )
        return None


def format_conflict_error(conflicts: List[DeploymentConflict]) -> str:
    error_parts = []
    for conflict in conflicts:
        error_parts.append(
            f"Node {conflict.node_name} ({conflict.node_ip}): "
            f"[{conflict.conflict_type}] {conflict.details}"
        )
    return "Deployment aborted due to conflicts:\n" + "\n".join(error_parts)


class VmService:
    def __init__(self, ssl_cert, ip_allocator=None):
        self.ssl_cert = ssl_cert
        self.ip_allocator = ip_allocator
        self.logger = logging.getLogger(__name__)
        self.pre_deployment_checker = PreDeploymentChecker(self.logger)

    def execute_deployment(self, deploy_nodes: List[ComputeNode],
                           deploy_config: VmDeploySpecModel, vm_id_dict: Dict) -> Dict:
        vm_instances = {}
        node_task = {}
        
        task_service = get_task_service()
        
        if not vm_id_dict:
            node_to_spec, error_msg = self._prepare_default_deployment(deploy_nodes, deploy_config)
        else:
            node_to_spec, error_msg = self._prepare_specified_deployment(deploy_nodes, deploy_config, vm_id_dict)

        if error_msg:
            self.logger.error(f"Deployment preparation failed: {error_msg}")
            raise Exception(error_msg)

        for node in deploy_nodes:
            if node.nodename not in node_to_spec:
                continue
            cvm_spec_internal = node_to_spec[node.nodename]

            try:
                instance_task_id = task_service.create_task(TASK_TYPE_VM_CREATE, {"total_vms": cvm_spec_internal.vm_id_list})
                node_task[node.nodename] = instance_task_id
                
                for vm_name in cvm_spec_internal.vm_id_list:
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
                        
                        for vm_name in success_vms:
                            iface_list = cvm_spec_internal.vm_iface.get(vm_name, []) if cvm_spec_internal.vm_iface else []
                            iface_list_json = json.dumps([iface.to_dict() for iface in iface_list]) if iface_list else None

                            try:
                                vm_instance_dao = get_dao_registry().vm_instance_dao
                                existing_vm = vm_instance_dao.get_by_vm_id(vm_name)
                                if existing_vm:
                                    existing_vm.host_ip = node.ip
                                    existing_vm.host_name = node.nodename
                                    existing_vm.vm_spec_uuid = cvm_spec_internal.vm_spec.uuid
                                    existing_vm.iface_list = iface_list_json
                                    existing_vm.os_version = "openEuler-2403LTS-SP2"
                                    vm_instance_dao.update(existing_vm)
                                    self.logger.info(f"Successfully updated reused VM {vm_name} in database for node {node.ip}")
                                else:
                                    vm_instance = VmInstance(
                                        vm_id=vm_name,
                                        host_ip=node.ip,
                                        host_name=node.nodename,
                                        vm_spec_uuid=cvm_spec_internal.vm_spec.uuid,
                                        iface_list=iface_list_json,
                                        os_version="openEuler-2403LTS-SP2"
                                    )
                                    vm_instance_dao.create(vm_instance)
                                    self.logger.info(f"Successfully recorded VM {vm_name} in database for node {node.ip}")
                            except Exception as e:
                                self.logger.error(f"Failed to record VM instance {vm_name} to database: {e}")
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

        async_node_to_spec = {}
        for node in deploy_nodes:
            if node.nodename in node_task:
                node_spec = VmDeploySpecInternal.from_db_model(deploy_config)
                if not vm_id_dict:
                    node_spec.vm_id_list = [f"{node.nodename}-{i + 1}" for i in range(node_spec.vm_spec.max_vm_num)]
                else:
                    node_spec.vm_id_list = vm_id_dict.get(node.nodename, [f"{node.nodename}-{i + 1}" for i in range(node_spec.vm_spec.max_vm_num)])
                async_node_to_spec[node.nodename] = node_spec
        
        jobs = []
        for node in deploy_nodes:
            if node.nodename in node_task:
                jobs.append(gevent.spawn(
                    deploy_node_async, 
                    node, 
                    node_task[node.nodename], 
                    async_node_to_spec[node.nodename],
                    current_app._get_current_object()
                ))
        
        return vm_instances

    def _prepare_default_deployment(self, deploy_nodes: List[ComputeNode],
                                     deploy_config: VmDeploySpecModel) -> Tuple[Dict[str, VmDeploySpecInternal], str]:
        """vm_id_dict为空时的默认部署准备：自动生成vm_id并分配IP"""
        self.logger.info("vm_id_dict is empty, using default naming convention (nodename-number)")

        has_conflicts, conflicts = self.pre_deployment_checker.check_nodes(deploy_nodes)
        if has_conflicts:
            error_msg = format_conflict_error(conflicts)
            self.logger.error(error_msg)
            return {}, error_msg

        node_to_spec = {}

        for node in deploy_nodes:
            cvm_spec_internal = VmDeploySpecInternal.from_db_model(deploy_config)
            cvm_spec_internal.vm_id_list = [f"{node.nodename}-{i + 1}" for i in range(cvm_spec_internal.vm_spec.max_vm_num)]
            self.logger.info(f"Node {node.nodename}: generated {len(cvm_spec_internal.vm_id_list)} VM IDs: {cvm_spec_internal.vm_id_list}")

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
                        cvm_spec_internal.vm_iface = allocResp.vm_iface_map
                        self.logger.info(f"Allocated ifaces for node {node.nodename}: {cvm_spec_internal.vm_iface}")
                    else:
                        error_msg = (
                            f"Deployment failed due to insufficient resources."
                            f"- Failed to allocate the IP address to node {node.nodename} (IP address: {node.ip})."
                        )
                        self.logger.error(error_msg)
                        return {}, error_msg
                except Exception as e:
                    error_msg = (
                        f"Deployment failed due to insufficient resources. The IP address of"
                    f" node {node.nodename} (IP address: {node.ip}) failed to be allocated. Error: {e}"
                )
                    self.logger.error(error_msg)
                    return {}, error_msg

            node_to_spec[node.nodename] = cvm_spec_internal

        return node_to_spec, ""

    def _prepare_specified_deployment(self, deploy_nodes: List[ComputeNode],
                                       deploy_config: VmDeploySpecModel,
                                       vm_id_dict: Dict) -> Tuple[Dict[str, VmDeploySpecInternal], str]:
        """vm_id_dict非空时的指定部署准备：区分已有VM(复用资源)和新VM(分配资源)"""
        self.logger.info(f"vm_id_dict is not empty, processing specified VM IDs: {vm_id_dict}")

        has_conflicts, conflicts = self.pre_deployment_checker.check_nodes_with_vm_ids(
            deploy_nodes, vm_id_dict
        )
        if has_conflicts:
            error_msg = format_conflict_error(conflicts)
            self.logger.error(error_msg)
            return {}, error_msg

        node_to_spec = {}

        for node in deploy_nodes:
            cvm_spec_internal = VmDeploySpecInternal.from_db_model(deploy_config)
            requested_vm_ids = vm_id_dict[node.nodename]
            new_vm_ids = []
            reused_vm_ids = []

            for vm_id in requested_vm_ids:
                try:
                    vm_instance_dao = get_dao_registry().vm_instance_dao
                    existing_vm = vm_instance_dao.get_by_vm_id(vm_id)
                except Exception as e:
                    self.logger.error(f"Database query failed for vm_id '{vm_id}': {e}")
                    continue

                if existing_vm:
                    self.logger.info(f"vm_id '{vm_id}' already exists in database, reusing resources (host={existing_vm.host_ip})")
                    reused_vm_ids.append(vm_id)
                else:
                    self.logger.info(f"vm_id '{vm_id}' not found in database, will allocate new resources")
                    new_vm_ids.append(vm_id)

            cvm_spec_internal.vm_id_list = requested_vm_ids
            self.logger.info(f"Node {node.nodename}: total={len(requested_vm_ids)}, reused={len(reused_vm_ids)}, new={len(new_vm_ids)}")

            if new_vm_ids and self.ip_allocator:
                try:
                    allocReq = NetAllocReq(new_vm_ids,
                        cvm_spec_internal.vm_spec.vlan_id,
                        cvm_spec_internal.vm_spec.net_pf_num,
                        cvm_spec_internal.vm_spec.net_vf_num,
                        node.ip
                    )
                    allocResp = self.ip_allocator.allocate(request=allocReq)
                    if allocResp.success:
                        if not cvm_spec_internal.vm_iface:
                            cvm_spec_internal.vm_iface = {}
                        cvm_spec_internal.vm_iface.update(allocResp.vm_iface_map)
                        self.logger.info(f"Allocated ifaces for new VMs on node {node.nodename}: {allocResp.vm_iface_map}")
                    else:
                        error_msg = (
                            f"Deployment failed due to insufficient resources. Failed to"
                            f" allocate the new VM IP address to node {node.nodename} (IP address: {node.ip})."
                        )
                        self.logger.error(error_msg)
                        return {}, error_msg
                except Exception as e:
                    error_msg = (
                        f"Deployment failed due to insufficient resources. Failed to allocate"
                        f" the new VM IP address to node {node.nodename} (IP address: {node.ip}). Error: {e}")
                    self.logger.error(error_msg)
                    return {}, error_msg

            if reused_vm_ids:
                try:
                    vm_instance_dao = get_dao_registry().vm_instance_dao
                    reused_vms = vm_instance_dao.get_by_vm_ids(reused_vm_ids)
                    if not cvm_spec_internal.vm_iface:
                        cvm_spec_internal.vm_iface = {}
                    for vm in reused_vms:
                        if vm.iface_list:
                            cvm_spec_internal.vm_iface[vm.vm_id] = VmDeploySpecInternal.vm_iface_from_json(vm.iface_list)
                        self.logger.info(f"Reused iface for vm_id '{vm.vm_id}': {cvm_spec_internal.vm_iface.get(vm.vm_id, [])}")
                except Exception as e:
                    self.logger.error(f"Failed to query reused VM ifaces for node {node.nodename}: {e}")

            node_to_spec[node.nodename] = cvm_spec_internal

        return node_to_spec, ""

    def execute_undeployment(self, deploy_nodes: List[ComputeNode], vm_id_list: List[str]) -> Dict:
        vm_instances = {}
        node_task = {}
        
        task_service = get_task_service()
        
        # Step 1: If no nodes provided, find nodes based on VM IDs
        if not deploy_nodes:
            try:
                vm_instance_dao = get_dao_registry().vm_instance_dao
                vm_instances_db = vm_instance_dao.get_by_vm_ids(vm_id_list)
                if not vm_instances_db:
                    self.logger.warning(f"No VM instances found for IDs: {vm_id_list}")
                    return vm_instances
                
                node_vm_map = {}
                for vm in vm_instances_db:
                    if vm.host_ip not in node_vm_map:
                        node_vm_map[vm.host_ip] = []
                    node_vm_map[vm.host_ip].append(vm.vm_id)
                
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
                vm_instance_dao = get_dao_registry().vm_instance_dao
                node_vm_ids = []
                for vm_id in vm_id_list:
                    if vm_instance_dao.get_by_vm_id_and_host(vm_id, node.ip):
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
                                vm_instance_dao = get_dao_registry().vm_instance_dao
                                vm_instance_dao.delete_by_vm_id(vm_id)
                                self.logger.info(f"Successfully deleted VM instance from database for VM ID {vm_id}")
                            except Exception as e:
                                self.logger.error(f"Failed to process undeployment cleanup for VM {vm_id} on {node.ip}: {e}")
                    
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
                vm_instance_dao = get_dao_registry().vm_instance_dao
                node_vm_ids = []
                for vm_id in vm_id_list:
                    if vm_instance_dao.get_by_vm_id_and_host(vm_id, node.ip):
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
        
    def execute_stop(self, vm_id_list: List[str]) -> Dict:
        vm_instances = {}
        node_task = {}

        task_service = get_task_service()

        try:
            vm_instance_dao = get_dao_registry().vm_instance_dao
            vm_instances_db = vm_instance_dao.get_by_vm_ids(vm_id_list)
            if not vm_instances_db:
                self.logger.warning(f"No VM instances found for IDs: {vm_id_list}")
                return vm_instances

            node_vm_map = {}
            for vm in vm_instances_db:
                if vm.host_ip not in node_vm_map:
                    node_vm_map[vm.host_ip] = []
                node_vm_map[vm.host_ip].append(vm.vm_id)

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

        for node in deploy_nodes:
            try:
                node_vm_ids = node_vm_map.get(node.ip, [])
                if not node_vm_ids:
                    continue

                instance_task_id = task_service.create_task(TASK_TYPE_VM_STOP, {"total_vms": node_vm_ids})
                node_task[node.nodename] = instance_task_id

                for vm_name in node_vm_ids:
                    vm_instances[vm_name] = {
                        "task_id": instance_task_id,
                        "host_ip": node.ip
                    }
            except Exception as e:
                self.logger.error(f"Failed to create stop task for node {node.nodename}: {e}")
                continue

        def stop_node_async(node, node_task_id: str, node_vm_ids: List[str], app):
            with app.app_context():
                success_vms = []
                failed_vms = []
                try:
                    task_service.update_task_status(node_task_id, "running")

                    compute_link = NetworkService(
                        node.nodename, COMPUTE_PORT, True, self.ssl_cert
                    )
                    result = compute_link.vm_stop(node_vm_ids)
                    self.logger.info(f"Stop result for node {node.nodename}: {result}")

                    if result is None:
                        failed_vms = node_vm_ids
                        task_params = {
                            "success_vms": [],
                            "fail_vms": failed_vms,
                            "total_vms": node_vm_ids
                        }
                        task_service.update_task_params(node_task_id, task_params)
                        task_service.update_task_status(node_task_id, "failed")
                        self.logger.error(f"Stop request failed for node {node.nodename}: no response")
                        return

                    if result.status_code == HTTPStatus.OK:
                        try:
                            response_data = result.json()
                            failed_vm_list = response_data.get("data", {}).get("failed_vms", []) if response_data.get("data") else []
                            if failed_vm_list:
                                failed_vm_ids = [item["vm_id"] for item in failed_vm_list if isinstance(item, dict) and "vm_id" in item]
                                success_vms = [vm_id for vm_id in node_vm_ids if vm_id not in failed_vm_ids]
                            else:
                                success_vms = node_vm_ids

                            task_params = {
                                "success_vms": success_vms,
                                "fail_vms": failed_vm_ids if failed_vm_list else [],
                                "total_vms": node_vm_ids
                            }
                            task_service.update_task_params(node_task_id, task_params)

                            if failed_vm_list:
                                task_service.update_task_status(node_task_id, "failed")
                            else:
                                task_service.update_task_status(node_task_id, "success")

                        except Exception as e:
                            self.logger.error(f"Failed to parse stop result: {e}")
                            failed_vms = node_vm_ids
                            task_params = {
                                "success_vms": [],
                                "fail_vms": failed_vms,
                                "total_vms": node_vm_ids
                            }
                            task_service.update_task_params(node_task_id, task_params)
                            task_service.update_task_status(node_task_id, "failed")
                    else:
                        failed_vms = node_vm_ids
                        task_params = {
                            "success_vms": [],
                            "fail_vms": failed_vms,
                            "total_vms": node_vm_ids
                        }
                        task_service.update_task_params(node_task_id, task_params)
                        task_service.update_task_status(node_task_id, "failed")
                        self.logger.error(f"Stop request failed for node {node.nodename}: {result.status_code}")

                except Exception as e:
                    err_msg = f"Failed to stop VMs at {node.ip}, error reason: {e}"
                    self.logger.error(err_msg)
                    task_params = {
                        "success_vms": [],
                        "fail_vms": node_vm_ids,
                        "total_vms": node_vm_ids
                    }
                    task_service.update_task_params(node_task_id, task_params)
                    task_service.update_task_status(node_task_id, "failed")

        jobs = []
        for node in deploy_nodes:
            if node.nodename in node_task:
                node_vm_ids = node_vm_map.get(node.ip, [])
                if node_vm_ids:
                    jobs.append(gevent.spawn(
                        stop_node_async,
                        node,
                        node_task[node.nodename],
                        node_vm_ids,
                        current_app._get_current_object()
                    ))

        return vm_instances

    def execute_start(self, vm_id_list: List[str]) -> Dict:
        vm_instances = {}
        node_task = {}

        task_service = get_task_service()

        try:
            vm_instance_dao = get_dao_registry().vm_instance_dao
            vm_instances_db = vm_instance_dao.get_by_vm_ids(vm_id_list)
            if not vm_instances_db:
                self.logger.warning(f"No VM instances found for IDs: {vm_id_list}")
                return vm_instances

            node_vm_map = {}
            for vm in vm_instances_db:
                if vm.host_ip not in node_vm_map:
                    node_vm_map[vm.host_ip] = []
                node_vm_map[vm.host_ip].append(vm.vm_id)

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

        for node in deploy_nodes:
            try:
                node_vm_ids = node_vm_map.get(node.ip, [])
                if not node_vm_ids:
                    continue

                instance_task_id = task_service.create_task(TASK_TYPE_VM_START, {"total_vms": node_vm_ids})
                node_task[node.nodename] = instance_task_id

                for vm_name in node_vm_ids:
                    vm_instances[vm_name] = {
                        "task_id": instance_task_id,
                        "host_ip": node.ip
                    }
            except Exception as e:
                self.logger.error(f"Failed to create start task for node {node.nodename}: {e}")
                continue

        def start_node_async(node, node_task_id: str, node_vm_ids: List[str], app):
            with app.app_context():
                success_vms = []
                failed_vms = []
                try:
                    task_service.update_task_status(node_task_id, "running")

                    compute_link = NetworkService(
                        node.nodename, COMPUTE_PORT, True, self.ssl_cert
                    )
                    result = compute_link.vm_start(node_vm_ids)
                    self.logger.info(f"Start result for node {node.nodename}: {result}")

                    if result is None:
                        failed_vms = node_vm_ids
                        task_params = {
                            "success_vms": [],
                            "fail_vms": failed_vms,
                            "total_vms": node_vm_ids
                        }
                        task_service.update_task_params(node_task_id, task_params)
                        task_service.update_task_status(node_task_id, "failed")
                        self.logger.error(f"Start request failed for node {node.nodename}: no response")
                        return

                    if result.status_code == HTTPStatus.OK:
                        try:
                            response_data = result.json()
                            failed_vm_list = response_data.get("data", {}).get("failed_vms", []) if response_data.get("data") else []
                            if failed_vm_list:
                                failed_vm_ids = [item["vm_id"] for item in failed_vm_list if isinstance(item, dict) and "vm_id" in item]
                                success_vms = [vm_id for vm_id in node_vm_ids if vm_id not in failed_vm_ids]
                            else:
                                success_vms = node_vm_ids

                            task_params = {
                                "success_vms": success_vms,
                                "fail_vms": failed_vm_ids if failed_vm_list else [],
                                "total_vms": node_vm_ids
                            }
                            task_service.update_task_params(node_task_id, task_params)

                            if failed_vm_list:
                                task_service.update_task_status(node_task_id, "failed")
                            else:
                                task_service.update_task_status(node_task_id, "success")

                        except Exception as e:
                            self.logger.error(f"Failed to parse start result: {e}")
                            failed_vms = node_vm_ids
                            task_params = {
                                "success_vms": [],
                                "fail_vms": failed_vms,
                                "total_vms": node_vm_ids
                            }
                            task_service.update_task_params(node_task_id, task_params)
                            task_service.update_task_status(node_task_id, "failed")
                    else:
                        failed_vms = node_vm_ids
                        task_params = {
                            "success_vms": [],
                            "fail_vms": failed_vms,
                            "total_vms": node_vm_ids
                        }
                        task_service.update_task_params(node_task_id, task_params)
                        task_service.update_task_status(node_task_id, "failed")
                        self.logger.error(f"Start request failed for node {node.nodename}: {result.status_code}")

                except Exception as e:
                    err_msg = f"Failed to start VMs at {node.ip}, error reason: {e}"
                    self.logger.error(err_msg)
                    task_params = {
                        "success_vms": [],
                        "fail_vms": node_vm_ids,
                        "total_vms": node_vm_ids
                    }
                    task_service.update_task_params(node_task_id, task_params)
                    task_service.update_task_status(node_task_id, "failed")

        jobs = []
        for node in deploy_nodes:
            if node.nodename in node_task:
                node_vm_ids = node_vm_map.get(node.ip, [])
                if node_vm_ids:
                    jobs.append(gevent.spawn(
                        start_node_async,
                        node,
                        node_task[node.nodename],
                        node_vm_ids,
                        current_app._get_current_object()
                    ))

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
            "pagination": util_service.build_pagination_response(page, page_size, 0)
        }
        try:
            vm_instance_dao = get_dao_registry().vm_instance_dao
            
            host_ips = None
            vm_id_filter = None
            
            if nodes and len(nodes) > 0:
                nodes_db = ComputeNode.query.filter(ComputeNode.nodename.in_(nodes)).all()
                if not nodes_db:
                    return response_data, "No nodes found"
                host_ips = [node.ip for node in nodes_db]
            elif vm_ids and len(vm_ids) > 0:
                vm_id_filter = vm_ids
            
            total_vms, vm_instances = vm_instance_dao.query_with_filters(
                host_ips=host_ips,
                vm_ids=vm_id_filter,
                page=page,
                page_size=page_size
            )
            
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
                            "iface_list": json.loads(vm.iface_list) if vm.iface_list else [],
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
                                    "iface_list": json.loads(vm.iface_list) if vm.iface_list else [],
                                    "mem_used": 0.0,
                                    "host_ip": vm.host_ip
                                }
                        else:
                            self.logger.warning(f"Non-standard response format from node {node.ip}")
                            vm_states = response_data if isinstance(response_data, dict) else {}
                            
                            for vm in vms:
                                vm_state = vm_states.get(vm.vm_id, "UNKNOWN")
                                
                                vm_info_result[vm.vm_id] = {
                                    "state": vm_state,
                                    "create_at": vm.created_at.isoformat() + "Z" if vm.created_at else "",
                                    "os": vm.os_version or "Unknown",
                                    "iface_list": json.loads(vm.iface_list) if vm.iface_list else [],
                                    "mem_used": 0.0,
                                    "host_ip": vm.host_ip
                                }
                    else:
                        status_code = getattr(result, 'status_code', 'Unknown')
                        self.logger.error(f"Failed to query CVM state from node {node.ip}, status code: {status_code}")
                        failed_nodes.append(node.ip)
                        for vm in vms:
                            vm_info_result[vm.vm_id] = {
                                "state": "UNKNOWN",
                                "create_at": vm.created_at.isoformat() + "Z" if vm.created_at else "",
                                "os": vm.os_version or "Unknown",
                                "iface_list": json.loads(vm.iface_list) if vm.iface_list else [],
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
                            "iface_list": json.loads(vm.iface_list) if vm.iface_list else [],
                            "mem_used": 0.0,
                            "host_ip": vm.host_ip
                        }
            
            # 构建响应数据
            response_data = {
                "vm_info": vm_info_result,
                "pagination": util_service.build_pagination_response(page, page_size, total_vms)
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
