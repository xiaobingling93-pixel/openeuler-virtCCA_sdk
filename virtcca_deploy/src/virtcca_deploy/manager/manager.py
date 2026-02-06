#!/usr/bin
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import logging
from dataclasses import asdict
import os
from typing import List, Tuple, Dict

import flask

import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants
from virtcca_deploy.common.constants import HTTPStatusCodes, OperationCodes
import virtcca_deploy.services.db_service as db_service
import virtcca_deploy.services.node_service as node_service
import virtcca_deploy.services.network_service as network_service
from virtcca_deploy.common.data_model import VmDeploySpec, ApiResponse, VmDeploySpecInternal
from virtcca_deploy.services.db_service import ComputeNode

g_logger = config.g_logger
g_cvm_deploy_spec = VmDeploySpec()


def create_app():
    server_config = config.Config(constants.DEFAULT_CONFIG_PATH)
    server_config.configure_log(constants.MANAGER_LOG_NEME)
    server_config.configure_ssl()
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
        except ValueError:
            g_logger.error("Registration error: %s", str(e))
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = "Invalid register data"
                        ).to_dict()), HTTPStatusCodes.Failed

    @app.route(constants.ROUTE_NODE_INFO, methods=[constants.POST])
    def query_node_info():
        data = flask.request.get_json()
        if not data or 'ips' not in data or not data['ips']:
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED,
                    message = "Request must contain a list of IPs.").to_dict()), HTTPStatusCodes.BAD_REQUEST

        existing_node_infos = {}
        ip_list = data['ips']
        valid_nodes = {}
        for ip in ip_list:
            node = node_service.NodeService.get_node_by_ip(ip)
            if not node:
                g_logger.error("Node not found for IP: %s", ip)
                return flask.jsonify(ApiResponse(
                    status=OperationCodes.FAILED,
                    message=f"Node not found for IP: {ip}").to_dict()), HTTPStatusCodes.BAD_REQUEST
            else:
                valid_nodes[ip] = node
        for ip in ip_list:
            try:
                compute_link = network_service.NetworkService(
                valid_nodes[ip].nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert)
                result = compute_link.query_node_info()
                if result.get("status") == OperationCodes.SUCCESS.value:
                    existing_node_infos[ip] = result.get("data")
                else:
                    g_logger.error("Query failed for IP %s: %s", ip, result.get('message', 'Unknown error'))
                    existing_node_infos[ip] = None

            except Exception as e:
                g_logger.error("Error querying node for IP %s: %s", ip, str(e))
                existing_node_infos[ip] = None

        g_logger.info("Node queries completed")
        return flask.jsonify(ApiResponse(
            data=existing_node_infos).to_dict())

    @app.route(constants.ROUTE_SET_NODE_DEPLOY_CONFIG, methods=[constants.POST])
    def set_node_deploy_config():
        global g_cvm_deploy_spec
        cvm_spec_json = flask.request.get_json()
        if not cvm_spec_json:
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED,
                    message = "Content-Type must be application/json").to_dict()), HTTPStatusCodes.BAD_REQUEST
        try:
            cvm_spec = VmDeploySpec(**cvm_spec_json)
        except TypeError as e:
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED,
                    message = "Invalid cvm config format").to_dict()), HTTPStatusCodes.BAD_REQUEST

        if not cvm_spec.is_valid():
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED,
                    message = "Invalid cvm config value").to_dict())
        g_cvm_deploy_spec = cvm_spec
        g_logger.info("set cvm spec success: %s", g_cvm_deploy_spec)
        return flask.jsonify(ApiResponse().to_dict())

        return deploy_nodes, None

    def _execute_deployment(deploy_nodes: List[ComputeNode],
                            cvm_spec_internal: VmDeploySpecInternal) -> Tuple[Dict, int]:
        deployment_results = {}
        success_nodes = 0

        for node in deploy_nodes:
            try:
                compute_link = network_service.NetworkService(
                    node.nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert
                )
                result = compute_link.vm_deploy(asdict(cvm_spec_internal))
                deployment_results[node.ip] = {
                    "message": result.get('message', 'Unknown error'),
                    "success_cvm": result.get("data")
                }
                if result.get("status") == OperationCodes.SUCCESS.value:
                    success_nodes += 1

            except Exception as e:
                err_msg = "Failed to deploy CVM at {}, error reason: {}".format(node.ip, e)
                g_logger.error(err_msg)
                deployment_results[node.ip] = {
                    "message": str(e),
                    "success_cvm": 0
                }
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

    def _execute_undeployment(deploy_nodes: List[ComputeNode], vm_id: List[str]) -> Tuple[Dict, int]:
        deployment_results = {}
        success_nodes = 0

        for node in deploy_nodes:
            try:
                compute_link = network_service.NetworkService(
                    node.nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert
                )
                result = compute_link.vm_undeploy(vm_id)
                if not result:
                    deployment_results[node.ip] = {
                        "message": "VM undeploy failed",
                        "failed_undeploy_cvm": vm_id
                    }
                if result.status_code != HTTPStatusCodes.OK or result.get("status") != OperationCodes.SUCCESS:
                    deployment_results[node.ip] = {
                        "message": result.get('message', 'Unknown error'),
                        "failed_undeploy_cvm": result.get("data")
                    }
                else:
                    deployment_results[node.ip] = {"message": "Successfully undeploy CVM"}
                    success_nodes += 1

            except Exception as e:
                err_msg = (
                    "Failed to undeploy CVM at {}, error reason: {}"
                    .format(node.ip, e)
                )
                g_logger.error(err_msg)
                deployment_results[node.ip] = {
                    "message": str(e),
                }
        return deployment_results, success_nodes

    @app.route(constants.ROUTE_VM_UNDEPLOY, methods=[constants.POST])
    def undeploy_cvm():
        undeploy_data = flask.request.get_json()
        if not undeploy_data or 'host_ip' not in undeploy_data or "vm_id" not in undeploy_data:
            return flask.jsonify(ApiResponse(status = OperationCodes.FAILED,
                    message = "Invalid cvm config value").to_dict()), HTTPStatusCodes.BAD_REQUEST
        target_nodes, error_response = node_service.NodeService.get_nodes_by_ip_list(undeploy_data.get('host_ip', []))
        if error_response:
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = error_response
                    ).to_dict())
        deployment_results, success_nodes = _execute_undeployment(target_nodes, undeploy_data.get('vm_id', []))
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
                if result.status_code != HTTPStatusCodes.OK or result.get("status") != OperationCodes.SUCCESS.value:
                    state_results[node.ip] = {
                        "message": result.get('message', 'Unknown error'),
                        "cvm_state": result.get("data")
                    }
                    continue
                state_results[node.ip] = {
                        "message": "Successfully query CVM state",
                        "cvm_state": result.get("data")
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
    def get_cvm_log(host_ip: str, vm_name: str):
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

            if response.status_code != HTTPStatusCodes.OK or response.get("status") != OperationCodes.SUCCESS.value:
                return flask.jsonify(ApiResponse(
                            status = OperationCodes.FAILED,
                            message = response.get("message")
                            ).to_dict())
            os.makedirs(constants.CVM_COLLECT_LOG_PATH, exist_ok=True)
            log_file_name = f"{host_ip}-{vm_name}.log"
            log_file_path = os.path.join(constants.CVM_COLLECT_LOG_PATH, log_file_name)
            try:
                with open(log_file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                g_logger.info("Log file saved successfully: %s", log_file_path)
            except Exception as e:
                err_msg = f"Failed to collect CVM log, error reason: {e}"
                g_logger.error(err_msg)
                flask.jsonify(ApiResponse(status = OperationCodes.FAILED,
                              message = err_msg
                              ).to_dict())
            return flask.jsonify(ApiResponse().to_dict())

        except Exception as e:
            err_msg = f"Failed to collect CVM log, error reason: {e}"
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
                response = compute_link.upload_cvm_software(upload_file)
                if not response or response.status_code != HTTPStatusCodes.OK:
                    err_msg = "Failed to connect {}".format(node.ip)
                    g_logger.error(err_msg)
                    deployment_results[node.ip] = {
                        "message": err_msg,
                    }
                    continue

                deployment_results[node.ip] = {
                    "message": response.json().get('message', 'Unknown error'),
                }
                if response.json().get("status") == OperationCodes.SUCCESS.value:
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
        if not flask.request.files['file'] or not flask.request.files['file'].filename:
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED, 
                    message = "cvm log not found",
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST

        g_logger.info("receive upload software: %s", flask.request.files['file'].filename)

        target_nodes, error_response = node_service.NodeService.get_nodes_by_ip_list()
        if error_response:
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = error_response
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST

        g_logger.info("upload cvm software to compute nodes, %s", target_nodes)
        upload_file = flask.request.files['file']
        filename = upload_file.filename
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

if __name__ == "__main__":
    app.run(host='0.0.0.0',
        port=constants.MANAGER_PORT)
