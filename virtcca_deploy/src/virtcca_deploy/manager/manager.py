#!/usr/bin
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import logging
from dataclasses import asdict
import os

import flask

import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants
from virtcca_deploy.common.constants import HTTPStatusCodes, OperationCodes
import virtcca_deploy.services.db_service as db_service
import virtcca_deploy.services.node_service as node_service
import virtcca_deploy.services.network_service as network_service
from virtcca_deploy.common.data_model import VmDeploySpec, ApiResponse, VmDeploySpecInternal

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

    def _get_target_nodes(ip_list):
        deploy_nodes = []

        if not ip_list:
            deploy_nodes = node_service.NodeService.get_all_nodes()
        else:
            for ip in ip_list:
                node = node_service.NodeService.get_node_by_ip(ip)
                if node:
                    deploy_nodes.append(node)
                else:
                    return None, flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = "Invalid compute node ip: {}".format(ip)
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST

        return deploy_nodes, None

    def _execute_deployment(deploy_nodes, cvm_spec_internal):
        deployment_results = {}
        success_nodes = []

        for node in deploy_nodes:
            try:
                compute_link = network_service.NetworkService(
                    node.nodename, constants.COMPUTE_PORT, True, server_config.ssl_cert
                )
                result = compute_link.vm_deploy(asdict(cvm_spec_internal))
                if result.get("status") == OperationCodes.SUCCESS.value:
                    success_nodes.append(node.ip)
                    deployment_results[node.ip] = {
                        "status": "SUCCESS", 
                        "message": "Deploy success!"
                    }
                else:
                    deployment_results[node.ip] = {
                        "status": "FAILED", 
                        "message": result.get('message', 'Unknown error')
                    }

            except Exception as e:
                err_msg = (
                    "Failed to deploy CVM at {}, error reason: {}, deploy CVM success at {}"
                    .format(node.ip, e, success_nodes)
                )
                g_logger.error(err_msg)
                deployment_results[node.ip] = {
                    "status": "FAILED", 
                    "message": str(e)
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

        deploy_nodes, error_response = _get_target_nodes(deploy_data.get('host_ip', []))
        if error_response:
            return error_response

        deployment_results, success_nodes = _execute_deployment(deploy_nodes, cvm_spec_internal)
        if len(success_nodes) == len(deploy_nodes):
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

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0',
        port=constants.MANAGER_PORT)
