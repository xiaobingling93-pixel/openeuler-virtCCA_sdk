#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

# 首先应用gevent猴子补丁，确保在导入其他模块之前完成
from gevent import monkey
monkey.patch_all()

import logging
import socket
import os
from http import HTTPStatus
import flask

import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants
import virtcca_deploy.services.virt_service as virt_service
import virtcca_deploy.services.network_service as network_service
import virtcca_deploy.services.util_service as util_service
import virtcca_deploy.services.db_service as db_service
import virtcca_deploy.services.resource_allocator as resource_allocator
from virtcca_deploy.common.data_model import VmDeploySpec, ApiResponse, VmDeploySpecInternal

g_logger = config.g_logger


def create_app():
    app = flask.Flask(__name__)

    server_config = config.Config(constants.DEFAULT_CONFIG_PATH)
    server_config.configure_log(constants.COMPUTE_LOG_NAME)
    server_config.configure_ssl()

    root_logger = logging.getLogger()
    app.logger.setLevel(logging.INFO)
    for handler in root_logger.handlers:
        app.logger.addHandler(handler)

    if not os.path.exists(constants.PathConfig.DATA_DIR):
        os.makedirs(constants.PathConfig.DATA_DIR, exist_ok=True)

    app.config['SQLALCHEMY_DATABASE_URI'] = constants.PathConfig.COMPUTE_DB
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    compute_db = db_service.DbService(app)
    compute_db.db.init_app(app)
    with app.app_context():
        compute_db.db.create_all()
        g_logger.info("Compute database initialized at %s", constants.PathConfig.COMPUTE_DB)

        device_allocator = resource_allocator.DeviceManagerAllocator()
        device_allocator.discover_hi1822_devices()
        device_allocator.sync_discovered_to_db()
        server_config.device_allocator = device_allocator
        g_logger.info("Device allocator initialized and devices synced to database")

    manager_domain_name = server_config.config.get("DEFAULT", "manager").strip().strip('"').strip("'")
    try:
        manager_ip = socket.gethostbyname(manager_domain_name)
        g_logger.info("Resolve manager ip success: %s -> %s", manager_domain_name, manager_ip)
    except socket.gaierror:
        g_logger.error("Failed to resolve manager ip")

    g_logger.info("Virtcca Deploy Compute node start!")

    manager_link = network_service.NetworkService(
            manager_domain_name,
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
            return flask.jsonify(ApiResponse(
                message="Not allowed to access internal api").to_dict()), HTTPStatus.FORBIDDEN

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
                    message=e
                ).to_dict()
            ), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_DEPLOY_INTERNAL, methods=[constants.POST])
    def deploy_cvm_internal():
        cvm_spec_json = flask.request.get_json()
        g_logger.info("get cvm deploy request: %s", cvm_spec_json)
        if not cvm_spec_json:
            g_logger.error("Invalid param: request body is empty")
            return flask.jsonify(ApiResponse(
                        message = "Content-Type must be application/json"
                    ).to_dict()), HTTPStatus.BAD_REQUEST
        
        required_fields = ['vm_id_list', 'vm_spec', 'vm_iface']
        for field in required_fields:
            if field not in cvm_spec_json:
                g_logger.error(f"Invalid param: missing required field {field}")
                return flask.jsonify(ApiResponse(
                            message = f"Missing required field: {field}"
                        ).to_dict()), HTTPStatus.BAD_REQUEST
        
        vm_id_list = cvm_spec_json['vm_id_list']
        if not isinstance(vm_id_list, list) or len(vm_id_list) == 0:
            g_logger.error("Invalid param: vm_id_list must be a non-empty list")
            return flask.jsonify(ApiResponse(
                        message = "vm_id_list must be a non-empty list"
                    ).to_dict()), HTTPStatus.BAD_REQUEST
        
        vm_spec_data = cvm_spec_json['vm_spec']
        if not isinstance(vm_spec_data, dict):
            g_logger.error("Invalid param: vm_spec must be a dictionary")
            return flask.jsonify(ApiResponse(
                        message = "vm_spec must be a dictionary"
                    ).to_dict()), HTTPStatus.BAD_REQUEST
        
        vm_iface = cvm_spec_json['vm_iface']
        if not isinstance(vm_iface, dict):
            g_logger.error("Invalid param: vm_iface must be a dictionary")
            return flask.jsonify(ApiResponse(
                        message = "vm_iface must be a dictionary"
                    ).to_dict()), HTTPStatus.BAD_REQUEST
        
        try:
            vm_spec = VmDeploySpec(**vm_spec_data)
            cvm_deploy_spec_internal = VmDeploySpecInternal(
                vm_id_list=vm_id_list, 
                vm_spec=vm_spec, 
                vm_iface=vm_iface
            )
            
            if not cvm_deploy_spec_internal.is_valid():
                g_logger.error("Invalid deployment specification")
                return flask.jsonify(ApiResponse( 
                        message = "Invalid deployment specification"
                    ).to_dict()), HTTPStatus.BAD_REQUEST
            
            deployed_cvms, deploy_err_msg = virt_service.deploy_cvm(cvm_deploy_spec_internal, server_config)
            if deployed_cvms is None or len(deployed_cvms) < len(vm_id_list):
                if deployed_cvms is None:
                    success_cvm_num = 0
                else:
                    success_cvm_num = len(deployed_cvms)
                error_msg = (
                    "Deploy cvm failed, "
                    "total %d cvms, "
                    "deployed %d, "
                    "reason: %s"
                ) % (len(vm_id_list), success_cvm_num, deploy_err_msg)
                g_logger.error(error_msg)
                return flask.jsonify(ApiResponse(
                        message = error_msg,
                        data = deployed_cvms).to_dict())
            
            g_logger.info("deploy all cvms success")
            return flask.jsonify(ApiResponse(data = deployed_cvms).to_dict())
        
        except Exception as e:
            g_logger.error(f"Unexpected error during deployment: {e}")
            return flask.jsonify(ApiResponse(
                    message = f"Unexpected error: {str(e)}"
                ).to_dict()), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route(constants.ROUTE_VM_UNDEPLOY_INTERNAL, methods=[constants.POST])
    def undeploy_cvm_internal():
        cvm_id_json = flask.request.get_json()
        if not cvm_id_json or not isinstance(cvm_id_json, list):
            g_logger.error("Invalid param")
            return flask.jsonify(ApiResponse(
                        message = "Content-Type must be application/json"
                    ).to_dict()), HTTPStatus.BAD_REQUEST
        g_logger.info("get cvm undeploy request: %s\n", cvm_id_json)
        failed_cvm = []
        for vm_id in cvm_id_json:
            result = virt_service.undeploy_cvm(vm_id, server_config)
            if result is False:
                failed_cvm.append(vm_id)
        if failed_cvm:
            return flask.jsonify(ApiResponse(
                    message = "some cvm destroy failed",
                    data = failed_cvm
                    ).to_dict())
        return flask.jsonify(ApiResponse().to_dict())

    @app.route(constants.ROUTE_VM_STOP_INTERNAL, methods=[constants.POST])
    def stop_cvm_internal():
        cvm_id_json = flask.request.get_json()
        if not cvm_id_json or not isinstance(cvm_id_json, list):
            g_logger.error("Invalid param: request body must be a list of VM IDs")
            return flask.jsonify(ApiResponse(
                        message = "Request body must be a non-empty list of VM IDs"
                    ).to_dict()), HTTPStatus.BAD_REQUEST
        g_logger.info("get cvm stop request: %s", cvm_id_json)
        failed_cvm = []
        for vm_id in cvm_id_json:
            success, err_msg = virt_service.stop_cvm(vm_id)
            if not success:
                failed_cvm.append({"vm_id": vm_id, "reason": err_msg})
                g_logger.error("Failed to stop VM %s: %s", vm_id, err_msg)
        if failed_cvm:
            return flask.jsonify(ApiResponse(
                    message = "some cvm stop failed",
                    data = {"failed_vms": failed_cvm}
                    ).to_dict())
        return flask.jsonify(ApiResponse().to_dict())

    @app.route(constants.ROUTE_VM_START_INTERNAL, methods=[constants.POST])
    def start_cvm_internal():
        cvm_id_json = flask.request.get_json()
        if not cvm_id_json or not isinstance(cvm_id_json, list):
            g_logger.error("Invalid param: request body must be a list of VM IDs")
            return flask.jsonify(ApiResponse(
                        message = "Request body must be a non-empty list of VM IDs"
                    ).to_dict()), HTTPStatus.BAD_REQUEST
        g_logger.info("get cvm start request: %s", cvm_id_json)
        failed_cvm = []
        for vm_id in cvm_id_json:
            success, err_msg = virt_service.start_cvm(vm_id)
            if not success:
                failed_cvm.append({"vm_id": vm_id, "reason": err_msg})
                g_logger.error("Failed to start VM %s: %s", vm_id, err_msg)
        if failed_cvm:
            return flask.jsonify(ApiResponse(
                    message = "some cvm start failed",
                    data = {"failed_vms": failed_cvm}
                    ).to_dict())
        return flask.jsonify(ApiResponse().to_dict())

    @app.route(constants.ROUTE_VM_LOG_COLLECT_INTERNAL, methods=[constants.GET])
    def get_cvm_log_internal(vm_id: str):
        cvm_log_file_path = os.path.join(constants.LIBVIRT_QEMU_LOG_PATH, f"{vm_id}.log")
        g_logger.info("collect cvm log request: %s", cvm_log_file_path)
        if not os.path.exists(cvm_log_file_path):
            g_logger.error("cvm log not found: %s", cvm_log_file_path)
            return flask.jsonify(ApiResponse(
                    message = "cvm log not found",
                    ).to_dict()), HTTPStatus.NOT_FOUND
        g_logger.info("collect cvm log request success: %s", cvm_log_file_path)
        response = flask.send_from_directory(constants.LIBVIRT_QEMU_LOG_PATH, f"{vm_id}.log", as_attachment=True)
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return response

    @app.route(constants.ROUTE_VM_SOFTWARE_INTERNAL, methods=[constants.POST])
    def upload_cvm_software_internal():
        if 'file' not in flask.request.files:
            return flask.jsonify(ApiResponse(
                    message = "No file part in request",
                    ).to_dict()), HTTPStatus.BAD_REQUEST

        upload_file = flask.request.files['file']
        if upload_file.filename == '':
            return flask.jsonify(ApiResponse(
                    message = "No selected file",
                    ).to_dict()), HTTPStatus.BAD_REQUEST

        g_logger.info("upload_cvm_software_internal: %s", flask.request.files)

        filename = os.path.basename(upload_file.filename)

        os.makedirs(constants.CVM_COMPUTE_SOFTWARE_PATH, exist_ok=True)
        filepath = os.path.join(constants.CVM_COMPUTE_SOFTWARE_PATH, filename)

        try:
            upload_file.save(filepath)
            return flask.jsonify(ApiResponse().to_dict())
        except Exception as e:
            g_logger.error("Error saving file: %s", e)
            return flask.jsonify(ApiResponse(
                        message = "Error saving file"
                    ).to_dict()), HTTPStatus.BAD_REQUEST

    return app


app = create_app()


def main():
    from gunicorn.app.base import BaseApplication

    class ComputeApp(BaseApplication):
        def load_config(self):
            self.cfg.set("bind", constants.NetworkConfig.COMPUTE_BIND)
            self.cfg.set("workers", constants.ServerConfig.WORKERS)
            self.cfg.set("worker_class", "gevent")
            self.cfg.set("timeout", constants.ServerConfig.TIMEOUT)
            self.cfg.set("certfile", f"{constants.PathConfig.CERT_DIR}/compute.crt")
            self.cfg.set("keyfile", f"{constants.PathConfig.CERT_DIR}/compute.key")

        def load(self):
            return app

    ComputeApp().run()


if __name__ == "__main__":
    main()
