#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import logging
import socket
import sys

import flask

import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants
from virtcca_deploy.common.constants import HTTPStatusCodes, OperationCodes
import virtcca_deploy.services.virt_service as virt_service
import virtcca_deploy.services.network_service as network_service
import virtcca_deploy.services.util_service as util_service
from virtcca_deploy.common.data_model import VmDeploySpec, ApiResponse, VmDeploySpecInternal

g_logger = config.g_logger


def create_app():
    app = flask.Flask(__name__)

    server_config = config.Config(constants.DEFAULT_CONFIG_PATH)
    server_config.configure_log(constants.COMPUTE_LOG_NEME)
    server_config.configure_ssl()

    root_logger = logging.getLogger()
    app.logger.setLevel(logging.INFO)
    for handler in root_logger.handlers:
        app.logger.addHandler(handler)

    manager_domain_name = server_config.config.get("DEFAULT", "manager")
    try:
        manager_ip = socket.gethostbyname(manager_domain_name)
        g_logger.info("Resolve manager ip success: %s -> %s", manager_domain_name, manager_ip)
    except socket.gaierror:
        g_logger.error("Failed to resolve manager ip")

    g_logger.info("Virtcca Deploy Compute node start!")

    manager_link = network_service.NetworkService(
            server_config.config.get("DEFAULT", "manager").strip().strip('"').strip("'"),
            constants.MANAGER_PORT,
            True,
            server_config.ssl_cert)

    utils = util_service.UtilService()
    node_info = utils.get_node_info()
    manager_link.node_register(node_info)

    @app.route("/")
    def hello():
        return flask.jsonify(ApiResponse(message="This is virtcca deploy compute").to_dict())

    @app.before_request
    def before_request_check_ip():
        req_ip = flask.request.remote_addr
        if req_ip != manager_ip:
            g_logger.info('Access denied for IP: %s', req_ip)
            return flask.jsonify(ApiResponse(status=OperationCodes.IP_FORBIDDEN,
                message="Not allowed to access internal api").to_dict()), HTTPStatusCodes.FORBIDDEN

    @app.route(constants.ROUTE_NODE_INFO_INTERNAL, methods=[constants.GET])
    def query_node_info_internal():
        utils = util_service.UtilService()
        node_info = utils.get_node_info()
        return flask.jsonify(ApiResponse(data=node_info).to_dict())

    @app.route(constants.ROUTE_VM_STATE_INTERNAL, methods=[constants.GET])
    def query_cvm_state_internal():
        libvirt = virt_service.libvirtDriver()
        try:
            result = libvirt.list_all_cvm()
            return flask.jsonify(ApiResponse(data=result).to_dict())
        except Exception as e:
            g_logger.error("Error occurred: %s", e)
            return flask.jsonify(
                ApiResponse(
                    status=OperationCodes.COMPUTE_NODE_FAILED,
                    message=e
                ).to_dict()
            ), HTTPStatusCodes.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_DEPLOY_INTERNAL, methods=[constants.POST])
    def deploy_cvm_internal():
        cvm_spec_json = flask.request.get_json()
        g_logger.info("get cvm deploy request: %s", cvm_spec_json)
        if not cvm_spec_json:
            g_logger.error("Invalid param")
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = "Content-Type must be application/json"
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST
        vm_id = cvm_spec_json['vm_id']
        vm_spec_data = cvm_spec_json['vm_spec']
        vm_spec = VmDeploySpec(**vm_spec_data)
        g_logger.info("vm_spec: %s", vm_spec)
        cvm_deploy_spec_internal = VmDeploySpecInternal(vm_id=vm_id, vm_spec=vm_spec)
        if cvm_deploy_spec_internal.is_valid():
            cvm_deploy_config = cvm_deploy_spec_internal
        else:
            g_logger.error("Invalid spec")
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED, 
                    message = "Invalid cvm spec").to_dict()), HTTPStatusCodes.BAD_REQUEST

        xml_list = virt_service.config_xml(constants.CVM_TEMPLATE_XML, cvm_deploy_config)

        g_logger.info("deploy xml success: %s", xml_list)
        return flask.jsonify(ApiResponse().to_dict())

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=constants.COMPUTE_PORT)
