#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

# 首先应用gevent猴子补丁，确保在导入其他模块之前完成
from gevent import monkey
monkey.patch_all()

import logging
from dataclasses import asdict
import os

import flask
from gevent import lock
from http import HTTPStatus

import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants
import virtcca_deploy.services.db_service as db_service
import virtcca_deploy.services.node_service as node_service
import virtcca_deploy.services.network_service as network_service
import virtcca_deploy.services.util_service as util_service
import virtcca_deploy.services.vm_service as vm_service
import virtcca_deploy.services.task_service as task_service
from virtcca_deploy.common.data_model import VmDeploySpec, ApiResponse
from virtcca_deploy.services.db_service import VmDeploySpecModel
from virtcca_deploy.services.resource_allocator import IpAllocator
from virtcca_deploy.services.network_config_service import init_network_config_service
from virtcca_deploy.services.software_service import init_software_service, get_software_service

g_logger = config.g_logger
g_cvm_deploy_spec = VmDeploySpec()
g_spec_lock = lock.RLock()


def create_app():
    server_config = config.Config(constants.DEFAULT_CONFIG_PATH)
    server_config.configure_log(constants.MANAGER_LOG_NAME)
    server_config.configure_ssl()
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
        with g_spec_lock:
            existing_spec = manager_db.db.session.query(VmDeploySpecModel).first()
            if not existing_spec:
                default_spec = g_cvm_deploy_spec.to_db_model()
                default_spec.is_default = True
                manager_db.db.session.add(default_spec)
                manager_db.db.session.commit()

                g_logger.info("Created default cvm spec with uuid: %s", default_spec.uuid)
            else:
                g_cvm_deploy_spec = VmDeploySpec.from_db_model(existing_spec)
                g_logger.info("Loaded existing cvm spec from database with uuid: %s", existing_spec.uuid)

        from virtcca_deploy.manager.auth import init_auth
        init_auth(app, server_config)
        init_network_config_service()
        init_software_service()
        ip_allocator = IpAllocator()

        vm_service.init_vm_service(server_config.ssl_cert, ip_allocator)
        task_service.init_task_service()

    g_logger.info("Virtcca Deploy Manager node start!")

    def _check_vm_ids_exist(vm_id_list):
        not_found = []
        for vm_id in vm_id_list:
            if not db_service.VmInstance.query.filter_by(vm_id=vm_id).first():
                not_found.append(vm_id)
        if not_found:
            return False, f"VM ID(s) not found: {', '.join(not_found)}"
        return True, ""

    @app.route("/")
    def hello():
        g_logger.info("hello!")
        return flask.jsonify(ApiResponse(message="This is virtcca deploy manager").to_dict())

    @app.route(constants.ROUTE_NODE_REGISTRY_INTERNAL, methods=[constants.POST])
    def node_register():
        if not flask.request.is_json:
            return flask.jsonify(ApiResponse(
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
                        "pagination": util_service.build_pagination_response(page, page_size, 0)
                    },
                    message=""
                ).to_dict())
            
            paged_nodes, total_nodes = util_service.paginate_list(query_nodes, page, page_size)
            
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
                        "os": node_data.get("os", "Unknown"),
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
                "pagination": util_service.build_pagination_response(page, page_size, total_nodes)
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
            manager_db.db.session.query(VmDeploySpecModel).delete()

            # Create new spec
            new_spec_model = cvm_spec.to_db_model()
            new_spec_model.is_default = True
            manager_db.db.session.add(new_spec_model)
            manager_db.db.session.commit()
            with g_spec_lock:
                g_logger.info("Saved cvm spec to database with uuid: %s, all existing specs deleted", g_cvm_deploy_spec.uuid)
        except Exception as e:
            manager_db.db.session.rollback()
            g_logger.error("Failed to save cvm spec to database: %s", str(e))
            return flask.jsonify(ApiResponse(
                    message="Failed to save config to database").to_dict())

        with g_spec_lock:
            g_cvm_deploy_spec = cvm_spec
        g_logger.info("set cvm spec success: %s", g_cvm_deploy_spec)
        return flask.jsonify(ApiResponse(data = g_cvm_deploy_spec.uuid).to_dict())

    @app.route(constants.ROUTE_GET_NODE_DEPLOY_CONFIG, methods=[constants.GET])
    def get_node_deploy_config():
        """根据deploy_id获取部署配置"""
        try:
            deploy_id = flask.request.args.get('deploy_config_id')
            
            if deploy_id:
                deploy_config = manager_db.db.session.query(VmDeploySpecModel).filter_by(uuid=deploy_id).first()
            else:
                deploy_config = manager_db.db.session.query(VmDeploySpecModel).filter_by(is_default=True).first()
            
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
        g_logger.info("Received VM deploy request")

        def validate_deploy_params(deploy_data):
            """验证部署参数"""
            if not deploy_data or "deploy_config_id" not in deploy_data:
                return False, None, "Invalid request format"
            return True, deploy_data, ""

        def process_deploy_config_id(deploy_config_id):
            """处理部署配置ID"""
            # 如果deploy_config_id为空，使用默认配置
            if not deploy_config_id:
                try:
                    default_config = manager_db.db.session.query(db_service.VmDeploySpecModel).filter_by(is_default=True).first()
                    if not default_config:
                        return False, None, "No default deployment config found"
                    return True, default_config, ""
                except Exception as e:
                    g_logger.error(f"Failed to get default deployment config: {e}")
                    return False, None, "Failed to get default deployment config"
            
            # 使用指定的配置ID
            try:
                requested_config = manager_db.db.session.query(db_service.VmDeploySpecModel).filter_by(uuid=deploy_config_id).first()
                if not requested_config:
                    return False, None, "Invalid deploy_config_id"
                return True, requested_config, ""
            except Exception as e:
                g_logger.error(f"Failed to get deployment config: {e}")
                return False, None, "Failed to get deployment config"

        def check_config_conflict(deploy_config_id):
            """检查是否有VM使用不同的配置"""
            try:
                active_vms = manager_db.db.session.query(db_service.VmInstance).filter(
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

        def check_vm_id(vm_id_dict, deploy_config):
            """检查vm_id参数"""
            if not vm_id_dict:
                g_logger.info("vm_id is empty, will use default naming convention (hostname-number)")
                return True, None, ""

            if not isinstance(vm_id_dict, dict):
                return False, None, "vm_id must be a dict"

            for node_name, vm_ids in vm_id_dict.items():
                if not isinstance(vm_ids, list) or len(vm_ids) == 0:
                    return False, None, f"vm_id['{node_name}'] must be a Non-empty list"

                node = node_service.NodeService.get_node_by_name(node_name)
                if not node:
                    return False, None, f"Node '{node_name}' does not exist"

                for vm_id in vm_ids:
                    if not isinstance(vm_id, str) or not vm_id:
                        return False, None, f"Invalid vm_id in node '{node_name}': must be a non-empty string"

                    if '-' not in vm_id:
                        return False, None, f"Invalid vm_id format '{vm_id}': expected '{{nodename}}-{{number}}'"

                    parts = vm_id.rsplit('-', 1)
                    id_nodename = parts[0]
                    id_number_str = parts[1]

                    if id_nodename != node_name:
                        return False, None, f"vm_id '{vm_id}' nodename '{id_nodename}' does not match node '{node_name}'"

                    try:
                        id_number = int(id_number_str)
                    except ValueError:
                        return False, None, f"Invalid vm_id format '{vm_id}': number part must be an integer"

                    if id_number < 1:
                        return False, None, f"Invalid vm_id '{vm_id}': number must be >= 1"

                    if id_number > deploy_config.max_vm_num:
                        return False, None, f"vm_id '{vm_id}' number {id_number} exceeds max_vm_num {deploy_config.max_vm_num}"

                    existing_vm = db_service.VmInstance.query.filter_by(vm_id=vm_id).first()
                    if existing_vm:
                        return False, None, f"vm_id '{vm_id}' already exists"

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
        success, _, error_msg = check_vm_id(vm_id_dict, requested_config)
        if not success:
            return flask.jsonify(ApiResponse(
                    data = None,
                    message = error_msg).to_dict()), HTTPStatus.BAD_REQUEST

        # Step 7: Execute deployment
        vm_service_instance = vm_service.get_vm_service()
        try:
            cvm_spec = VmDeploySpec.from_db_model(requested_config)
            vm_instances = vm_service_instance.execute_deployment(target_nodes, cvm_spec, vm_id_dict)
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
            vm_id_list = undeploy_data["vm_ids"]
        else:
            return flask.jsonify(ApiResponse(
                message = "Invalid request format, expected a list of VM IDs").to_dict()), HTTPStatus.BAD_REQUEST

        if not vm_id_list or not isinstance(vm_id_list, list):
            return flask.jsonify(ApiResponse(
                message = "Invalid request format, expected a list of VM IDs").to_dict()), HTTPStatus.BAD_REQUEST
        
        if len(vm_id_list) == 0:
            return flask.jsonify(ApiResponse(
                message = "VM ID list cannot be empty").to_dict()), HTTPStatus.BAD_REQUEST

        exist, err_msg = _check_vm_ids_exist(vm_id_list)
        if not exist:
            return flask.jsonify(ApiResponse(
                message = err_msg).to_dict()), HTTPStatus.BAD_REQUEST
        
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

    @app.route(constants.ROUTE_VM_STOP, methods=[constants.POST])
    def stop_cvm():
        stop_data = flask.request.get_json()

        vm_id_list = None
        if isinstance(stop_data, list):
            vm_id_list = stop_data
        elif isinstance(stop_data, dict) and "vm_ids" in stop_data:
            vm_id_list = stop_data["vm_ids"]
        else:
            return flask.jsonify(ApiResponse(
                message = "Invalid request format, expected a list of VM IDs"
            ).to_dict()), HTTPStatus.BAD_REQUEST

        if not vm_id_list or not isinstance(vm_id_list, list):
            return flask.jsonify(ApiResponse(
                message = "Invalid request format, expected a non-empty list of VM IDs"
            ).to_dict()), HTTPStatus.BAD_REQUEST

        if len(vm_id_list) == 0:
            return flask.jsonify(ApiResponse(
                message = "VM ID list cannot be empty"
            ).to_dict()), HTTPStatus.BAD_REQUEST

        exist, err_msg = _check_vm_ids_exist(vm_id_list)
        if not exist:
            return flask.jsonify(ApiResponse(
                message = err_msg
            ).to_dict()), HTTPStatus.BAD_REQUEST

        vm_service_instance = vm_service.get_vm_service()
        try:
            stop_results = vm_service_instance.execute_stop(vm_id_list)
            return flask.jsonify(ApiResponse(
                data = stop_results,
                message = ""
            ).to_dict()), HTTPStatus.ACCEPTED
        except Exception as e:
            g_logger.error(f"Failed to start stop operation: {e}")
            return flask.jsonify(ApiResponse(
                message = f"Failed to start stop operation: {e}"
            ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_START, methods=[constants.POST])
    def start_cvm():
        start_data = flask.request.get_json()

        vm_id_list = None
        if isinstance(start_data, list):
            vm_id_list = start_data
        elif isinstance(start_data, dict) and "vm_ids" in start_data:
            vm_id_list = start_data["vm_ids"]
        else:
            return flask.jsonify(ApiResponse(
                message = "Invalid request format, expected a list of VM IDs"
            ).to_dict()), HTTPStatus.BAD_REQUEST

        if not vm_id_list or not isinstance(vm_id_list, list):
            return flask.jsonify(ApiResponse(
                message = "Invalid request format, expected a non-empty list of VM IDs"
            ).to_dict()), HTTPStatus.BAD_REQUEST

        if len(vm_id_list) == 0:
            return flask.jsonify(ApiResponse(
                message = "VM ID list cannot be empty"
            ).to_dict()), HTTPStatus.BAD_REQUEST

        exist, err_msg = _check_vm_ids_exist(vm_id_list)
        if not exist:
            return flask.jsonify(ApiResponse(
                message = err_msg
            ).to_dict()), HTTPStatus.BAD_REQUEST

        vm_service_instance = vm_service.get_vm_service()
        try:
            start_results = vm_service_instance.execute_start(vm_id_list)
            return flask.jsonify(ApiResponse(
                data = start_results,
                message = ""
            ).to_dict()), HTTPStatus.ACCEPTED
        except Exception as e:
            g_logger.error(f"Failed to start operation: {e}")
            return flask.jsonify(ApiResponse(
                message = f"Failed to start operation: {e}"
            ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_STATE, methods=[constants.POST])
    def get_cvm_state():
        """
        查询虚拟机状态接口
        请求格式: {"nodes": ["compute01", "compute02"], "vm_ids": [], "pagination": {"page":1, "page_size": 10}}
        """
        try:
            # 获取请求数据
            try:
                request_data = flask.request.get_json()
                
                # 参数检查
                if not request_data or not isinstance(request_data, dict):
                    return flask.jsonify(ApiResponse(
                        message="Invalid request format, expected JSON object"
                    ).to_dict()), HTTPStatus.BAD_REQUEST
            except flask.BadRequest:
                # 处理JSON解析错误
                return flask.jsonify(ApiResponse(
                    message="Invalid request format, expected JSON object"
                ).to_dict()), HTTPStatus.BAD_REQUEST
            
            # 解析参数
            nodes = request_data.get("nodes", [])
            vm_ids = request_data.get("vm_ids", [])

            # 检查nodes和vm_ids不能同时非空
            if nodes and vm_ids:
                return flask.jsonify(ApiResponse(
                    message="Nodes and vm_ids cannot be non-empty at the same time"
                ).to_dict()), HTTPStatus.BAD_REQUEST
            
            # 检查nodes类型
            if nodes and not isinstance(nodes, list):
                return flask.jsonify(ApiResponse(
                    message="Invalid nodes parameter, expected list"
                ).to_dict()), HTTPStatus.BAD_REQUEST
            
            # 检查vm_ids类型
            if vm_ids and not isinstance(vm_ids, list):
                return flask.jsonify(ApiResponse(
                    message="Invalid vm_ids parameter, expected list"
                ).to_dict()), HTTPStatus.BAD_REQUEST

            # 校验分页参数
            success, error_msg, page, page_size = util_service.validate_and_extract_pagination(request_data)
            if not success:
                return flask.jsonify(ApiResponse(
                    message=error_msg
                ).to_dict()), HTTPStatus.BAD_REQUEST
            
            # 调用vm_service查询虚拟机状态
            vm_service_instance = vm_service.get_vm_service()
            response_data, message = vm_service_instance.query_vm_states(nodes, vm_ids, page, page_size)
            
            if not response_data:
                return flask.jsonify(ApiResponse(
                    message=message
                ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR
            
            return flask.jsonify(ApiResponse(
                message=message,
                data=response_data
            ).to_dict()), HTTPStatus.OK
            
        except Exception as e:
            g_logger.error(f"Unexpected error while querying VM state: {e}")
            return flask.jsonify(ApiResponse(
                message=f"Internal server error: {str(e)}"
            ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_LOG_COLLECT, methods=[constants.GET])
    def get_cvm_log():
        host_name = flask.request.args.get('host_name')
        vm_id = flask.request.args.get('vm_id')

        if not host_name or not vm_id:
            return flask.jsonify(ApiResponse(
                data=None,
                message="Missing required parameters: host_name and vm_id").to_dict()), HTTPStatus.BAD_REQUEST

        target_node = node_service.NodeService.get_node_by_name(host_name)
        if not target_node:
            return flask.jsonify(ApiResponse(
                        data=None,
                        message="No such compute node"
                    ).to_dict()), HTTPStatus.NOT_FOUND

        try:
            compute_link = network_service.NetworkService(
                target_node.nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert
            )
            response = compute_link.collect_cvm_log(vm_id)
            
            if not response:
                return flask.jsonify(ApiResponse(
                            data=None,
                            message="Virtual machine not found"
                            ).to_dict()), HTTPStatus.NOT_FOUND
            
            if response.status_code != HTTPStatus.OK:
                return flask.jsonify(ApiResponse(
                            data=None,
                            message="Failed to collect virtual machine log"
                            ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR
            
            log_file_name = f"{host_name}-{vm_id}.log"
            headers = {
                'Content-Type': 'text/plain; charset=utf-8',
                'Content-Disposition': f'attachment; filename="{log_file_name}"',
                'Content-Length': response.headers.get('Content-Length', '0')
            }
            
            g_logger.info("Successfully collected log for VM %s on node %s", vm_id, host_name)
            
            return flask.Response(
                response.iter_content(chunk_size=1024),
                status=HTTPStatus.OK,
                headers=headers
            )

        except Exception as e:
            err_msg = f"Failed to collect virtual machine log: {e}"
            g_logger.error(err_msg)
            return flask.jsonify(ApiResponse(
                            data=None,
                            message=err_msg
                        ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR


    @app.route(constants.ROUTE_VM_SOFTWARE, methods=[constants.POST])
    def upload_cvm_software():
        # 检查请求格式
        if 'file' not in flask.request.files:
            return flask.jsonify(ApiResponse(
                    message = "No file part in request",
                    ).to_dict()), HTTPStatus.BAD_REQUEST
        
        # 获取表单字段
        upload_file = flask.request.files['file']
        file_name = flask.request.form.get('file_name')
        file_hash = flask.request.form.get('file_hash')
        file_size_str = flask.request.form.get('file_size')
        signature = flask.request.form.get('signature')
        
        # 调用软件服务处理上传
        software_service = get_software_service()
        success, message, _ = software_service.upload_software(
            upload_file, file_name, file_hash, file_size_str, signature
        )
        
        if success:
            return flask.jsonify(ApiResponse(
                message = message,
                data = None
            ).to_dict()), HTTPStatus.OK
        else:
            # Determine appropriate HTTP status code based on error type
            if "Missing required fields" in message or "Invalid" in message or "No selected file" in message or "hash mismatch" in message:
                return flask.jsonify(ApiResponse(
                    message = message,
                    data = None
                ).to_dict()), HTTPStatus.BAD_REQUEST
            else:
                return flask.jsonify(ApiResponse(
                    message = message,
                    data = None
                ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_SOFTWARE, methods=[constants.GET])
    def get_vm_software():
        """
        查询当前已上传的软件包
        """
        software_service = get_software_service()
        success, message, data = software_service.get_software_list()
        
        if success:
            return flask.jsonify(ApiResponse(
                message = message,
                data = data
            ).to_dict()), HTTPStatus.OK
        else:
            return flask.jsonify(ApiResponse(
                message = message,
                data = None
            ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_SOFTWARE, methods=[constants.DELETE])
    def delete_vm_software():
        """
        删除当前已上传的软件包
        """
        try:
            # 获取请求体中的file_names列表
            request_data = flask.request.get_json()
            if not request_data or "file_names" not in request_data:
                return flask.jsonify(ApiResponse(
                    message = "Missing required field: file_names"
                ).to_dict()), HTTPStatus.BAD_REQUEST
            
            file_names = request_data["file_names"]
            if not isinstance(file_names, list) or not file_names:
                return flask.jsonify(ApiResponse(
                    message = "Invalid file_names: must be a non-empty list"
                ).to_dict()), HTTPStatus.BAD_REQUEST
            
            # 调用软件服务删除文件
            software_service = get_software_service()
            success, message, deleted_files = software_service.delete_software(file_names)
            
            if success:
                return flask.jsonify(ApiResponse(
                    message = message,
                    data = None
                ).to_dict()), HTTPStatus.OK
            else:
                # Determine if it's a 404 error vs 500 error
                if "No such software" in message:
                    return flask.jsonify(ApiResponse(
                        message = message
                    ).to_dict()), HTTPStatus.NOT_FOUND
                else:
                    return flask.jsonify(ApiResponse(
                        message = message
                    ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR
            
        except Exception as e:
            g_logger.error("Error deleting software: %s", e)
            return flask.jsonify(ApiResponse(
                message = f"Error deleting software: {str(e)}"
            ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR
            
        except Exception as e:
            g_logger.error("Error deleting software packages: %s", e)
            manager_db.db.session.rollback()
            return flask.jsonify(ApiResponse(
                message = "Error deleting software packages: {}".format(str(e))
            ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_TASKS, methods=[constants.GET])
    def get_vm_tasks():
        """查询虚机部署和卸载进度接口"""
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
            self.cfg.set("bind", constants.NetworkConfig.MANAGER_BIND)
            self.cfg.set("workers", constants.ServerConfig.WORKERS)
            self.cfg.set("worker_class", "gevent")
            self.cfg.set("timeout", constants.ServerConfig.TIMEOUT)
            self.cfg.set("certfile", f"{constants.PathConfig.CERT_DIR}/manager.crt")
            self.cfg.set("keyfile", f"{constants.PathConfig.CERT_DIR}/manager.key")

        def load(self):
            return app

    ManagerApp().run()


if __name__ == "__main__":
    main()
