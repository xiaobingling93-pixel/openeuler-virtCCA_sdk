#!/usr/bin
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

# 首先应用gevent猴子补丁，确保在导入其他模块之前完成
from gevent import monkey
monkey.patch_all()

import logging
from dataclasses import asdict
import os
from typing import List, Tuple, Dict

import flask
from http import HTTPStatus

import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants
from virtcca_deploy.common.constants import HTTPStatusCodes, OperationCodes
import virtcca_deploy.services.db_service as db_service
import virtcca_deploy.services.node_service as node_service
import virtcca_deploy.services.network_service as network_service
import virtcca_deploy.services.util_service as util_service
import virtcca_deploy.services.vm_service as vm_service
import virtcca_deploy.services.task_service as task_service
from virtcca_deploy.common.data_model import VmDeploySpec, ApiResponse
from virtcca_deploy.services.db_service import ComputeNode, VmDeploySpecModel

g_logger = config.g_logger
g_cvm_deploy_spec = VmDeploySpec()


def create_app():
    server_config = config.Config(constants.DEFAULT_CONFIG_PATH)
    server_config.configure_log(constants.MANAGER_LOG_NEME)
    server_config.configure_ssl()
    server_config.configure_vlan_pool()
    server_config.configure_auth()
    root_logger = logging.getLogger()

    if not os.path.exists(constants.MANAGER_DB_PATH):
        os.makedirs(constants.MANAGER_DB_PATH, exist_ok=True)

    app = flask.Flask(__name__)
    app.logger.setLevel(logging.INFO)
    for handler in root_logger.handlers:
        app.logger.addHandler(handler)

    app.config['SQLALCHEMY_DATABASE_URI'] = constants.MANAGER_DB
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    manager_db = db_service.DbService(app)
    manager_db.db.init_app(app)
    with app.app_context():
        manager_db.db.create_all()

        # Load existing spec from database if it exists
        global g_cvm_deploy_spec
        existing_spec = db_service.db.session.query(VmDeploySpecModel).first()
        if not existing_spec:
            default_spec = g_cvm_deploy_spec.to_db_model()
            default_spec.is_default = True
            db_service.db.session.add(default_spec)
            db_service.db.session.commit()

            g_logger.info("Created default cvm spec with uuid: %s", default_spec.uuid)
        else:
            g_cvm_deploy_spec = VmDeploySpec.from_db_model(existing_spec)
            g_logger.info("Loaded existing cvm spec from database with uuid: %s", existing_spec.uuid)

        from virtcca_deploy.manager.auth import init_auth
        init_auth(app, server_config)

        vm_service.init_vm_service(server_config.ssl_cert, server_config.vlan_pool_manager)
        task_service.init_task_service()

    g_logger.info("Virtcca Deploy Manager node start!")

    @app.route("/")
    def hello():
        g_logger.info("hello!")
        return flask.jsonify(ApiResponse(message="This is virtcca deploy manager").to_dict())

    @app.route(constants.ROUTE_NODE_REGISTRY_INTERNAL, methods=[constants.POST])
    def node_register():
        if not flask.request.is_json:
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED,
                    message = "Content-Type must be application/json").to_dict()), HTTPStatus.BAD_REQUEST
        try:
            node_data = flask.request.get_json()
            new_node = node_service.NodeService.create_node(
                flask.request.remote_addr, node_data)
            g_logger.info("compute node register success: %s", new_node)
            return flask.jsonify(ApiResponse().to_dict())
        except ValueError as e:
            g_logger.error("Registration error: %s", str(e))
            return flask.jsonify(ApiResponse(
                        message = "Invalid register data"
                        ).to_dict()), HTTPStatus.BAD_REQUEST

    @app.route(constants.ROUTE_NODE_INFO, methods=[constants.POST])
    def query_node_info():
        data = flask.request.get_json()

        if not data:
            return flask.jsonify(ApiResponse(
                message="Request must contain JSON data."
            ).to_dict()), HTTPStatus.BAD_REQUEST
        
        nodes = data.get('nodes', [])
        ips = data.get('ips', [])

        if nodes and ips:
            return flask.jsonify(ApiResponse(
                message="Parameters 'nodes' and 'ips' cannot be non-empty at the same time."
            ).to_dict()), HTTPStatus.BAD_REQUEST
        
        success, error_msg, page, page_size = util_service.validate_and_extract_pagination(data)
        if not success:
            return flask.jsonify(ApiResponse(
                message=error_msg
            ).to_dict()), HTTPStatus.BAD_REQUEST

        try:
            error_response = None
            if nodes:
                query_nodes, error_response = node_service.NodeService.get_nodes_by_name_list(nodes)
            elif ips:
                query_nodes, error_response = node_service.NodeService.get_nodes_by_ip_list(ips)
            else:
                query_nodes = node_service.NodeService.get_all_nodes()
            
            if error_response:
                return flask.jsonify(ApiResponse(
                    message=error_response
                ).to_dict()), HTTPStatus.BAD_REQUEST
            
            if not query_nodes:
                return flask.jsonify(ApiResponse(
                    data={
                        "host_info": {},
                        "pagination": {
                            "page": page,
                            "page_size": page_size,
                            "entry_num": 0
                        }
                    },
                    message=""
                ).to_dict())
            
            total_nodes = len(query_nodes)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paged_nodes = query_nodes[start_idx:end_idx]
            
            host_infos = {}
            for node in paged_nodes:
                try:
                    compute_link = network_service.NetworkService(
                        node.nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert
                    )
                    result = compute_link.query_node_info()
                    
                    if result.get("message"):
                        return flask.jsonify(ApiResponse(
                            message=f"Node not found for {node.nodename}"
                        ).to_dict()), HTTPStatus.BAD_REQUEST
                    
                    node_data = result.get("data", {})
                    host_info = {
                        "hostname": node.nodename,
                        "ip": node.ip,
                        "physical_cpu": node_data.get("physical_cpu", 0),
                        "physical_cpu_free": node_data.get("physical_cpu_free", 0),
                        "memory": node_data.get("memory", 0),
                        "memory_free": node_data.get("memory_free", 0),
                        "pf_num_total": node_data.get("pf_num_total", 0),
                        "pf_num_free": node_data.get("pf_num_free", 0),
                        "disks": node_data.get("disks", []),
                        "secure_memory": node_data.get("secure_memory", 0),
                        "secure_memory_free": node_data.get("secure_memory_free", 0),
                        "secure_numa_topology": node_data.get("secure_numa_topology", {})
                    }
                    
                    host_infos[node.nodename] = host_info
                    
                except Exception as e:
                    g_logger.error(f"Error querying node {node.nodename}: {str(e)}")
                    return flask.jsonify(ApiResponse(
                        message=f"Failed to query node {node.nodename}"
                    ).to_dict()), HTTPStatus.BAD_REQUEST
            
            g_logger.info("Node queries completed")
            
            response_data = {
                "host_info": host_infos,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "entry_num": total_nodes
                }
            }
            
            return flask.jsonify(ApiResponse(
                data=response_data,
                message=""
            ).to_dict())
            
        except Exception as e:
            g_logger.error(f"Unexpected error in query_node_info: {str(e)}")
            return flask.jsonify(ApiResponse(
                message="Internal server error"
            ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_SET_NODE_DEPLOY_CONFIG, methods=[constants.POST])
    def set_node_deploy_config():
        global g_cvm_deploy_spec
        cvm_spec_json = flask.request.get_json()
        if not cvm_spec_json:
            return flask.jsonify(ApiResponse(
                    message = "Content-Type must be application/json").to_dict()), HTTPStatus.BAD_REQUEST
        try:
            cvm_spec = VmDeploySpec(**cvm_spec_json)
        except TypeError as e:
            return flask.jsonify(ApiResponse(
                    message = "Invalid cvm config format").to_dict()), HTTPStatus.BAD_REQUEST

        if not cvm_spec.is_valid():
            return flask.jsonify(ApiResponse(
                    message = "Invalid cvm config value").to_dict())
        try:
            # Delete all existing specs to ensure only one is stored
            db_service.db.session.query(VmDeploySpecModel).delete()
            
            # Create new spec
            new_spec_model = cvm_spec.to_db_model()
            new_spec_model.is_default = True
            db_service.db.session.add(new_spec_model)
            db_service.db.session.commit()
            g_logger.info("Saved cvm spec to database with uuid: %s, all existing specs deleted", g_cvm_deploy_spec.uuid)
        except Exception as e:
            db_service.db.session.rollback()
            g_logger.error("Failed to save cvm spec to database: %s", str(e))
            return flask.jsonify(ApiResponse(
                    message="Failed to save config to database").to_dict())
        
        g_cvm_deploy_spec = cvm_spec
        g_logger.info("set cvm spec success: %s", g_cvm_deploy_spec)
        return flask.jsonify(ApiResponse(data = g_cvm_deploy_spec.uuid).to_dict())

    @app.route(constants.ROUTE_GET_NODE_DEPLOY_CONFIG, methods=[constants.GET])
    def get_node_deploy_config():
        """根据deploy_id获取部署配置"""
        try:
            deploy_id = flask.request.args.get('deploy_config_id')
            
            if deploy_id:
                deploy_config = db_service.db.session.query(VmDeploySpecModel).filter_by(uuid=deploy_id).first()
            else:
                deploy_config = db_service.db.session.query(VmDeploySpecModel).filter_by(is_default=True).first()
            
            if not deploy_config:
                 return flask.jsonify(ApiResponse(
                    message=f"Unable to get deploy config with ID {deploy_id}"
                 ).to_dict()), HTTPStatus.NOT_FOUND

            cvm_deploy_spec = VmDeploySpec.from_db_model(deploy_config)
            return flask.jsonify(ApiResponse(
                data = {
                    cvm_deploy_spec.uuid: asdict(cvm_deploy_spec)
                }
            ).to_dict())
            
        except Exception as e:
            g_logger.error(f"Failed to get deploy config: {e}")
            return flask.jsonify(ApiResponse(
                message=f"Failed to get deploy config: {str(e)}"
            ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_DEPLOY, methods=[constants.POST])
    def deploy_cvm():
        global g_cvm_deploy_spec
        g_logger.info("Received VM deploy request")

        def validate_deploy_params(deploy_data):
            """验证部署参数"""
            if not deploy_data or "deploy_config_id" not in deploy_data or "vm_id" not in deploy_data:
                return False, None, "Invalid request format"
            return True, deploy_data, ""

        def process_deploy_config_id(deploy_config_id):
            """处理部署配置ID"""
            # 如果deploy_config_id为空，使用默认配置
            if not deploy_config_id:
                try:
                    default_config = db_service.db.session.query(db_service.VmDeploySpecModel).filter_by(is_default=True).first()
                    if not default_config:
                        return False, None, "No default deployment config found"
                    return True, default_config, ""
                except Exception as e:
                    g_logger.error(f"Failed to get default deployment config: {e}")
                    return False, None, "Failed to get default deployment config"
            
            # 使用指定的配置ID
            try:
                requested_config = db_service.db.session.query(db_service.VmDeploySpecModel).filter_by(uuid=deploy_config_id).first()
                if not requested_config:
                    return False, None, "Invalid deploy_config_id"
                return True, requested_config, ""
            except Exception as e:
                g_logger.error(f"Failed to get deployment config: {e}")
                return False, None, "Failed to get deployment config"

        def check_config_conflict(deploy_config_id):
            """检查是否有VM使用不同的配置"""
            try:
                active_vms = db_service.db.session.query(db_service.VmInstance).filter(
                    db_service.VmInstance.vm_spec_uuid != deploy_config_id
                ).all()
                if active_vms:
                    return False, "Please undeploy all VMs using different config first"
                return True, ""
            except Exception as e:
                g_logger.error(f"Failed to check active VMs: {e}")
                return False, "Failed to check active VMs"

        def get_target_nodes(vm_id_dict):
            """根据vm_id_dict获取目标节点"""
            target_nodes = []
            if vm_id_dict:
                for node_name in vm_id_dict.keys():
                    node = node_service.NodeService.get_node_by_name(node_name)
                    if node:
                        target_nodes.append(node)
                    else:
                        return False, None, f"Node {node_name} not found"
            else:
                # 如果没有指定节点，使用所有可用节点
                try:
                    target_nodes = node_service.NodeService.get_all_nodes()
                except Exception as e:
                    g_logger.error(f"Failed to get all nodes: {e}")
                    return False, None, "Failed to get all nodes"

            if not target_nodes:
                return False, None, "No target nodes found"
            
            return True, target_nodes, ""

        def check_vm_id(vm_id_dict):
            """检查vm_id参数"""
            if not vm_id_dict:
                g_logger.info("vm_id is empty, will use default naming convention (hostname-number)")
                # 默认命名规则：以hostname-编号的形式为每个vm命名
                return True, None, ""
            return True, None, ""

        # Step 1: Validate basic parameters
        deploy_data = flask.request.get_json()
        success, deploy_data, error_msg = validate_deploy_params(deploy_data)
        if not success:
            return flask.jsonify(ApiResponse(
                    data = None,
                    message = error_msg).to_dict()), HTTPStatus.BAD_REQUEST

        # Step 2: Process deploy_config_id
        deploy_config_id = deploy_data.get('deploy_config_id')
        success, requested_config, error_msg = process_deploy_config_id(deploy_config_id)
        if not success:
            return flask.jsonify(ApiResponse(
                    data = None,
                    message = error_msg).to_dict()), HTTPStatus.BAD_REQUEST

        # Step 3: Check config conflict
        success, error_msg = check_config_conflict(requested_config.uuid)
        if not success:
            return flask.jsonify(ApiResponse(
                    data = None,
                    message = error_msg).to_dict()), HTTPStatus.BAD_REQUEST

        # Step 4: Get target nodes
        vm_id_dict = deploy_data.get('vm_id', {})
        g_logger.info(f"vm_id_dict: {vm_id_dict}")
        success, target_nodes, error_msg = get_target_nodes(vm_id_dict)
        if not success:
            return flask.jsonify(ApiResponse(
                    data = None,
                    message = error_msg).to_dict()), HTTPStatus.BAD_REQUEST

        # Step 5: Check vm_id
        success, _, error_msg = check_vm_id(vm_id_dict)
        if not success:
            return flask.jsonify(ApiResponse(
                    data = None,
                    message = error_msg).to_dict()), HTTPStatus.BAD_REQUEST

        # Step 7: Execute deployment
        vm_service_instance = vm_service.get_vm_service()
        try:
            vm_instances = vm_service_instance.execute_deployment(target_nodes, requested_config, vm_id_dict)
            return flask.jsonify(ApiResponse(
                data = vm_instances,
                message = ""
            ).to_dict()), HTTPStatus.ACCEPTED  # 202 Accepted
        except Exception as e:
            g_logger.error(f"Failed to start deployment: {e}")
            return flask.jsonify(ApiResponse(
                data = None,
                message = "Failed to start deployment"
            ).to_dict()), HTTPStatus.BAD_REQUEST


    @app.route(constants.ROUTE_VM_UNDEPLOY, methods=[constants.POST])
    def undeploy_cvm():
        # 处理外部传入的格式：{["compute01-1", "compute02-1"]}
        undeploy_data = flask.request.get_json()
        
        # 基本参数检查和格式处理
        vm_id_list = None
        if isinstance(undeploy_data, list):
            # 直接是列表格式：["compute01-1", "compute02-1"]
            vm_id_list = undeploy_data
        elif isinstance(undeploy_data, dict) and "vm_ids" in undeploy_data:
            # 包含一个列表的对象格式：{["compute01-1", "compute02-1"]}
            first_key = next(iter(undeploy_data))
            if isinstance(undeploy_data[first_key], list):
                vm_id_list = undeploy_data[first_key]
        else:
            return flask.jsonify(ApiResponse(
                message = "Invalid request format, expected a list of VM IDs").to_dict()), HTTPStatus.BAD_REQUEST

        if not vm_id_list or not isinstance(vm_id_list, list):
            return flask.jsonify(ApiResponse(
                message = "Invalid request format, expected a list of VM IDs").to_dict()), HTTPStatus.BAD_REQUEST
        
        if len(vm_id_list) == 0:
            return flask.jsonify(ApiResponse(
                message = "VM ID list cannot be empty").to_dict()), HTTPStatus.BAD_REQUEST
        
        # 获取VM服务实例
        vm_service_instance = vm_service.get_vm_service()
        
        # 调用execute_undeployment，传入空的nodes列表，由service内部根据vm_id查询节点
        try:
            deployment_results = vm_service_instance.execute_undeployment([], vm_id_list)
            return flask.jsonify(ApiResponse(
                data = deployment_results,
                message = ""
            ).to_dict()), HTTPStatus.ACCEPTED  # 202 Accepted
        except Exception as e:
            g_logger.error(f"Failed to start undeployment: {e}")
            return flask.jsonify(ApiResponse(
                message = f"Failed to start undeployment: {e}"
            ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_STATE, methods=[constants.GET])
    def get_cvm_state():
        target_nodes, error_response = node_service.NodeService.get_nodes_by_ip_list()
        if error_response:
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = error_response
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST

        state_results = {}
        success_nodes = 0
        for node in target_nodes:
            try:
                compute_link = network_service.NetworkService(
                    node.nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert
                )
                result = compute_link.query_cvm_state()
                if not result or result.status_code != HTTPStatusCodes.OK:
                    g_logger.error("Failed to query cvm state, status code: %s", result.status_code)
                    return flask.jsonify(ApiResponse(
                            status = OperationCodes.FAILED,
                            message = "Failed to query cvm state",
                            ).to_dict())
                if result.status_code != HTTPStatusCodes.OK or result.json().get("status") != OperationCodes.SUCCESS.value:
                    state_results[node.ip] = {
                        "message": result.json().get('message', 'Unknown error'),
                        "cvm_state": result.json().get("data")
                    }
                    continue
                state_results[node.ip] = {
                        "message": "Successfully query CVM state",
                        "cvm_state": result.json().get("data")
                    }
                success_nodes += 1

            except Exception as e:
                err_msg ="Failed to query CVM at {}, error reason: {}".format(node.ip, e)
                g_logger.error(err_msg)
                state_results[node.ip] = {"message": err_msg}
        if (success_nodes == len(target_nodes)):
                return flask.jsonify(ApiResponse(
                            message = "Successfully query CVM state to all nodes",
                            data = state_results
                        ).to_dict())
        return flask.jsonify(ApiResponse(
                            status = OperationCodes.FAILED,
                            message = "Some nodes failed to query CVM state",
                            data = state_results
                        ).to_dict())

    @app.route(constants.ROUTE_VM_LOG_COLLECT, methods=[constants.GET])
    def get_cvm_log():
        host_ip = flask.request.args.get('host_ip')
        vm_id = flask.request.args.get('vm_id')
        if not host_ip or not vm_id:
            return flask.jsonify(ApiResponse(
                message="Missing required parameters: host_name and vm_id").to_dict()), HTTPStatus.BAD_REQUEST
        target_node = node_service.NodeService.get_node_by_ip(host_ip)
        if not target_node:
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = "No such compute node"
                    ).to_dict()), HTTPStatusCodes.NOT_FOUND

        try:
            compute_link = network_service.NetworkService(
                target_node.nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert
            )
            response = compute_link.collect_cvm_log(vm_id)
            if not response:
                return flask.jsonify(ApiResponse(
                            status = OperationCodes.FAILED,
                            message = "Failed to collect CVM log",
                            ).to_dict())
            if response.status_code != HTTPStatusCodes.OK:
                return flask.jsonify(ApiResponse(
                            status = OperationCodes.FAILED,
                            ).to_dict())
            os.makedirs(constants.CVM_COLLECT_LOG_PATH, exist_ok=True)
            log_file_name = f"{host_ip}-{vm_id}.log"
            log_file_path = os.path.join(constants.CVM_COLLECT_LOG_PATH, log_file_name)
            g_logger.info("log_file_path: %s", log_file_path)
            try:
                with open(log_file_path, 'wb') as f:
                    g_logger.info("open the file: %s", log_file_name)
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                g_logger.info("Log file saved successfully: %s", log_file_path)
            except Exception as e:
                err_msg = f"Failed to collect CVM log, error reason 1: {e}"
                g_logger.error(err_msg)
                return flask.jsonify(ApiResponse(
                              message = err_msg
                              ).to_dict())
            return flask.jsonify(ApiResponse().to_dict())

        except Exception as e:
            err_msg = f"Failed to collect CVM log, error reason 2: {e}"
            g_logger.error(err_msg)
            return flask.jsonify(ApiResponse(
                            status = OperationCodes.FAILED,
                            message = err_msg,
                        ).to_dict())

    def _execute_upload(deploy_nodes: List[ComputeNode], upload_file) -> Tuple[Dict, int]:
        deployment_results = {}
        success_nodes = 0

        g_logger.info(f"_execute_upload deploy_nodes = {deploy_nodes}, upload_file = {upload_file}")
        for node in deploy_nodes:
            try:
                compute_link = network_service.NetworkService(
                    node.nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert
                )
                result = compute_link.upload_cvm_software(upload_file)
                if not result:
                    deployment_results[node.ip] = {
                        "message": "VM upload software failed",
                    }
                    continue
                if result.get("status") != OperationCodes.SUCCESS.value:
                    deployment_results[node.ip] = {
                        "message": result.get('message', 'Unknown error'),
                    }
                    continue
                else:
                    deployment_results[node.ip] = {"message": "Successfully upload software"}
                    success_nodes += 1

            except Exception as e:
                err_msg = "Failed to unload CVM software at {}, error reason: {}".format(node.ip, e)
                g_logger.error(err_msg)
                deployment_results[node.ip] = {
                    "message": err_msg,
                }

        return deployment_results, success_nodes

    @app.route(constants.ROUTE_VM_SOFTWARE, methods=[constants.POST])
    def upload_cvm_software():
        if 'file' not in flask.request.files:
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED, 
                    message = "No file part in request",
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST
        
        upload_file = flask.request.files['file']
        if upload_file.filename == '':
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED, 
                    message = "No selected file",
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST
                    
        # 防止路径穿越攻击，只保留文件名部分
        filename = os.path.basename(upload_file.filename)
        g_logger.info("receive upload software: %s", filename)

        target_nodes, error_response = node_service.NodeService.get_nodes_by_ip_list()
        if error_response:
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = error_response
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST

        g_logger.info("upload cvm software to compute nodes, %s", target_nodes)
        os.makedirs(constants.CVM_MANAGER_SOFTWARE_PATH, exist_ok=True)
        filepath = os.path.join(constants.CVM_MANAGER_SOFTWARE_PATH, filename)

        try:
            upload_file.save(filepath)
        except Exception as e:
            g_logger.error("Error saving file: %s", e)
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = "Error saving file"
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST

        upload_results, success_nodes = _execute_upload(target_nodes, filepath)
        if success_nodes == len(target_nodes):
            return flask.jsonify(ApiResponse(
                message = "Successfully unload CVM software to all nodes",
                data = upload_results
            ).to_dict())
        else:
            return flask.jsonify(ApiResponse(
                status = OperationCodes.COMPUTE_NODE_FAILED,
                message = "Some nodes failed to unload CVM software",
                data = upload_results
            ).to_dict())

    @app.route(constants.ROUTE_VM_TASKS, methods=[constants.GET])
    def get_vm_tasks():
        """查询虚机部署和卸载进度接口"""
        # 获取请求参数
        task_id = flask.request.args.get('task_id')
        if not task_id:
            return flask.jsonify(ApiResponse(
                message = "Invalid task id").to_dict()), HTTPStatus.BAD_REQUEST
        
        try:
            from virtcca_deploy.services.task_service import get_task_service
            task_service_instance = get_task_service()
            
            task = task_service_instance.get_task(task_id)
            if not task:
                return flask.jsonify(ApiResponse(
                    message = "Invalid task id").to_dict()), HTTPStatus.BAD_REQUEST
            
            task_data = {
                "task_id": task.task_id,
                "type": task.task_type,
                "status": task.status
            }
            
            task_data["params"] = task.get_task_params()
            return flask.jsonify(ApiResponse(
                data = task_data,
                message = "").to_dict()), HTTPStatus.OK
        
        except Exception as e:
            g_logger.error(f"Failed to query VM tasks: {e}")
            return flask.jsonify(ApiResponse(
                message = f"Failed to query VM tasks: {e}").to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    return app



app = create_app()


def main():
    from gunicorn.app.base import BaseApplication

    class ManagerApp(BaseApplication):
        def load_config(self):
            self.cfg.set("bind", "0.0.0.0:5001")
            self.cfg.set("workers", 1)
            self.cfg.set("worker_class", "gevent")
            self.cfg.set("timeout", 300)
            self.cfg.set("certfile", "/etc/virtcca_deploy/cert/manager.crt")
            self.cfg.set("keyfile", "/etc/virtcca_deploy/cert/manager.key")

        def load(self):
            return app

    ManagerApp().run()


if __name__ == "__main__":
    main()
