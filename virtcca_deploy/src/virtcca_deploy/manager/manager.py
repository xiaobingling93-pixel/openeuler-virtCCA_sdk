#!/usr/bin
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

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
from virtcca_deploy.common.data_model import VmDeploySpec, ApiResponse, VmDeploySpecInternal
from virtcca_deploy.services.db_service import ComputeNode, VmDeploySpecModel

g_logger = config.g_logger
g_cvm_deploy_spec = VmDeploySpec()


def create_app():
    server_config = config.Config(constants.DEFAULT_CONFIG_PATH)
    server_config.configure_log(constants.MANAGER_LOG_NEME)
    server_config.configure_ssl()
    server_config.configure_vlan_pool()
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
                    message = "Content-Type must be application/json").to_dict()), HTTPStatusCodes.BAD_REQUEST
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

    def _execute_deployment(deploy_nodes: List[ComputeNode],
                            cvm_spec_internal: VmDeploySpecInternal) -> Tuple[Dict, int]:
        deployment_results = {}
        success_nodes = 0
        result = {}
        vm_names_to_release = []
        for node in deploy_nodes:
            try:
                compute_link = network_service.NetworkService(
                    node.nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert
                )
                cvm_spec_internal.allocate_ip(server_config.vlan_pool_manager, node.ip)
                result = compute_link.vm_deploy(asdict(cvm_spec_internal))
                deployment_results[node.ip] = {
                    "message": result.get('message', 'Unknown error'),
                    "success_cvm": result.get("data")
                }
                if result.get("status") == OperationCodes.SUCCESS.value:
                    success_nodes += 1
                else:
                    # release ip of failed cvm
                    if result.get("data"):
                        vm_names_to_release = [
                            f"{cvm_spec_internal.vm_id}-{i + 1}" 
                            for i in range(cvm_spec_internal.vm_spec.vm_num) 
                            if f"{cvm_spec_internal.vm_id}-{i + 1}" not in result.get("data")
                        ]
                    else:
                        vm_names_to_release = [
                            f"{cvm_spec_internal.vm_id}-{i + 1}" 
                            for i in range(cvm_spec_internal.vm_spec.vm_num)
                        ]

            except Exception as e:
                err_msg = "Failed to deploy CVM at {}, error reason: {}".format(node.ip, e)
                g_logger.error(err_msg)
                vm_names_to_release = [
                            f"{cvm_spec_internal.vm_id}-{i + 1}" 
                            for i in range(cvm_spec_internal.vm_spec.vm_num)
                        ]
                deployment_results[node.ip] = {
                    "message": str(e),
                    "success_cvm": 0
                }
            for vm_name in vm_names_to_release:
                        server_config.vlan_pool_manager.release_ips_for_vm(node.ip, vm_name)
        return deployment_results, success_nodes

    @app.route(constants.ROUTE_VM_DEPLOY, methods=[constants.POST])
    def deploy_cvm():
        global g_cvm_deploy_spec
        g_logger.info("cvm_deploy_spec: %s", g_cvm_deploy_spec)

        deploy_data = flask.request.get_json()
        if not deploy_data or 'host_ip' not in deploy_data or "vm_id" not in deploy_data:
            return flask.jsonify(ApiResponse(status = OperationCodes.FAILED,
                    message = "Invalid cvm config value").to_dict()), HTTPStatusCodes.BAD_REQUEST

        cvm_spec_internal = VmDeploySpecInternal(vm_id=deploy_data["vm_id"], vm_spec=g_cvm_deploy_spec)

        deploy_nodes, error_response = node_service.NodeService.get_nodes_by_ip_list(deploy_data.get('host_ip', []))
        if error_response:
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = error_response
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST

        deployment_results, success_nodes = _execute_deployment(deploy_nodes, cvm_spec_internal)
        if success_nodes == len(deploy_nodes):
            return flask.jsonify(ApiResponse(
                status = OperationCodes.SUCCESS,
                message = "Successfully deployed CVM to all nodes",
                data = deployment_results
            ).to_dict())
        else:
            return flask.jsonify(ApiResponse(
                status = OperationCodes.COMPUTE_NODE_FAILED,
                message = "Some nodes failed to deploy CVM",
                data = deployment_results
            ).to_dict())

    def _execute_undeployment(deploy_nodes: List[ComputeNode], vm_id_list: List[str], vlan_pool_manager: config.VlanPoolManager) -> Tuple[Dict, int]:
        deployment_results = {}
        success_nodes = 0

        for node in deploy_nodes:
            try:
                success_vm_ids = []
                compute_link = network_service.NetworkService(
                    node.nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert
                )
                result = compute_link.vm_undeploy(vm_id_list)
                if not result:
                    deployment_results[node.ip] = {
                        "message": "VM undeploy failed",
                        "failed_undeploy_cvm": vm_id_list
                    }
                    continue
                if result.get("status") != OperationCodes.SUCCESS.value:
                    deployment_results[node.ip] = {
                        "message": result.get('message', 'Unknown error'),
                        "failed_undeploy_cvm": result.get("data")
                    }
                    success_vm_ids = []
                    success_vm_ids = list(set(vm_id_list) - set(result.get("data")))
                else:
                    deployment_results[node.ip] = {"message": "Successfully undeploy CVM"}
                    success_vm_ids = vm_id_list
                    success_nodes += 1

                g_logger.info("Releasing IPs for successfully undeployed VMs: %s", success_vm_ids)
                for vm_id in success_vm_ids:
                    vlan_pool_manager.release_ips_for_vm(node.ip, vm_id)

            except Exception as e:
                err_msg = (
                    "Failed to undeploy CVM at {}, error reason: {}"
                    .format(node.ip, e)
                )
                g_logger.error(err_msg)
                deployment_results[node.ip] = {
                    "message": str(e),
                }
                continue
        return deployment_results, success_nodes

    @app.route(constants.ROUTE_VM_UNDEPLOY, methods=[constants.POST])
    def undeploy_cvm():
        undeploy_data = flask.request.get_json()
        if not undeploy_data or not isinstance(undeploy_data.get('host_ip'), list) or not isinstance(undeploy_data.get('vm_id'), list):
            return flask.jsonify(ApiResponse(status = OperationCodes.FAILED,
                    message = "Invalid cvm config value").to_dict()), HTTPStatusCodes.BAD_REQUEST
        target_nodes, error_response = node_service.NodeService.get_nodes_by_ip_list(undeploy_data.get('host_ip', []))
        if error_response:
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = error_response
                    ).to_dict())
        deployment_results, success_nodes = _execute_undeployment(target_nodes, undeploy_data.get('vm_id', []), server_config.vlan_pool_manager)
        if success_nodes == len(target_nodes):
            return flask.jsonify(ApiResponse(
                message = "Successfully undeploy CVM to all nodes",
            ).to_dict())
        else:
            return flask.jsonify(ApiResponse(
                status = OperationCodes.COMPUTE_NODE_FAILED,
                message = "Some nodes failed to undeploy CVM",
                data = deployment_results
            ).to_dict())

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
            response = compute_link.collect_cvm_log(vm_name)
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
            log_file_name = f"{host_ip}-{vm_name}.log"
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
