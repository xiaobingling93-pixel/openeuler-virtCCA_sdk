#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import logging
import socket
import os

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
    server_config.configure_device()

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
            g_logger.warning('Access denied for IP: %s', req_ip)
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
        vm_ip_dict = cvm_spec_json['vm_ip_dict']

        vm_spec = VmDeploySpec(**vm_spec_data)
        cvm_deploy_spec_internal = VmDeploySpecInternal(vm_id=vm_id, vm_spec=vm_spec, vm_ip_dict=vm_ip_dict)
        if cvm_deploy_spec_internal.is_valid():
            deployed_cvms, deploy_err_msg = virt_service.deploy_cvm(cvm_deploy_spec_internal, server_config)
            if (deployed_cvms is None or len(deployed_cvms) < vm_spec.vm_num):
                if deployed_cvms is None:
                    succe_cvm_num = 0
                else:
                    succe_cvm_num = len(deployed_cvms)
                error_msg = (
                    "Deploy cvm failed, "
                    "total %d cvms, "
                    "deployed %d, "
                    "reason: %s"
                ) % (vm_spec.vm_num, succe_cvm_num, deploy_err_msg)
                g_logger.error(error_msg)
                return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED, 
                        message = error_msg,
                        data = deployed_cvms).to_dict())
        else:
            g_logger.error("Invalid spec")
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED, 
                    message = "Invalid cvm spec").to_dict(),
                    data = 0), HTTPStatusCodes.BAD_REQUEST

        g_logger.info("deploy all cvms success")
        return flask.jsonify(ApiResponse(data = deployed_cvms).to_dict())

    @app.route(constants.ROUTE_VM_UNDEPLOY_INTERNAL, methods=[constants.POST])
    def undeploy_cvm_internal():
        cvm_id_json = flask.request.get_json()
        if not cvm_id_json or not isinstance(cvm_id_json, list):
            g_logger.error("Invalid param")
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = "Content-Type must be application/json"
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST
        g_logger.info("get cvm undeploy request: %s\n", cvm_id_json)
        failed_cvm = []
        for vm_id in cvm_id_json:
            result = virt_service.undeploy_cvm(vm_id, server_config)
            if result is False:
                failed_cvm.append(vm_id)
        if failed_cvm:
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED, 
                    message = "some cvm destroy failed",
                    data = failed_cvm
                    ).to_dict())
        return flask.jsonify(ApiResponse().to_dict())
    @app.route(constants.ROUTE_VM_STATE_INTERNAL, methods=[constants.GET])
    def get_cvm_state_internal():
        cvm_state = virt_service.get_all_cvm_state()
        return flask.jsonify(ApiResponse(data = cvm_state).to_dict())

    @app.route(constants.ROUTE_VM_LOG_COLLECT_INTERNAL, methods=[constants.GET])
    def get_cvm_log_internal(vm_name: str):
        cvm_log_file_path = os.path.join(constants.LIBVIRT_QEMU_LOG_PATH, f"{vm_name}.log")
        g_logger.info("collect cvm log request: %s", cvm_log_file_path)
        if not os.path.exists(cvm_log_file_path):
            g_logger.error("cvm log not found: %s", cvm_log_file_path)
            return flask.jsonify(ApiResponse(
                    status = OperationCodes.FAILED, 
                    message = "cvm log not found",
                    ).to_dict()), HTTPStatusCodes.NOT_FOUND
        g_logger.info("collect cvm log request success: %s", cvm_log_file_path)
        return flask.send_from_directory(constants.LIBVIRT_QEMU_LOG_PATH, f"{vm_name}.log", as_attachment=True)

    @app.route(constants.ROUTE_VM_SOFTWARE_INTERNAL, methods=[constants.POST])
    def upload_cvm_software_internal():
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

        g_logger.info("upload_cvm_software_internal: %s", flask.request.files)

        # 防止路径穿越攻击，只保留文件名部分
        filename = os.path.basename(upload_file.filename)

        os.makedirs(constants.CVM_COMPUTE_SOFTWARE_PATH, exist_ok=True)
        filepath = os.path.join(constants.CVM_COMPUTE_SOFTWARE_PATH, filename)

        try:
            upload_file.save(filepath)
            return flask.jsonify(ApiResponse().to_dict())
        except Exception as e:
            g_logger.error("Error saving file: %s", e)
            return flask.jsonify(ApiResponse(
                        status = OperationCodes.FAILED,
                        message = "Error saving file"
                    ).to_dict()), HTTPStatusCodes.BAD_REQUEST

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=constants.COMPUTE_PORT)
