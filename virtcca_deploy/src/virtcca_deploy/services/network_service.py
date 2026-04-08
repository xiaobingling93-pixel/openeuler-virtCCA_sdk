#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
from typing import List

import requests
import virtcca_deploy.common.constants as constants
from virtcca_deploy.common.constants import HTTPStatusCodes, OperationCodes
import virtcca_deploy.common.config as config

g_logger = config.g_logger


class NetworkService:
    def __init__(self, domain, port, ssl_verify, ssl_verify_path=None):
        self.ssl_verify = ssl_verify
        self.ssl_verify_path = ssl_verify_path
        if ssl_verify:
            self.base_url = f"https://{domain}:{port}"
        else:
            self.base_url = f"http://{domain}:{port}"

    def make_request(self, url, method=constants.GET, headers=None, params=None, json_data=None, files=None):
        g_logger.debug("request url: %s\nheaders: %s\nparams: %s\n json_data: %s",
                    url, headers, params, json_data)
        if self.ssl_verify:
            verify_path = self.ssl_verify_path
        else:
            verify_path = None
        try:
            if method.upper() == constants.GET:
                response = requests.get(url, verify=verify_path, headers=headers, params=params)
            elif method.upper() == constants.POST:
                response = requests.post(url, verify=verify_path, headers=headers, params=params, json=json_data, files=files)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            return response
        except requests.RequestException as e:
            raise Exception("Error during request: {}".format(e))

    def node_register(self, node_info):
        register_url = f"{self.base_url}/{constants.ROUTE_NODE_REGISTRY_INTERNAL}"
        return self.make_request(register_url, method=constants.POST, json_data=node_info)

    def query_node_info(self):
        query_url = f"{self.base_url}/{constants.ROUTE_NODE_INFO_INTERNAL}"
        try:
            response = self.make_request(query_url, method=constants.GET)
            if response.status_code == HTTPStatusCodes.OK:
                return response.json()
            else:
                g_logger.error("Failed to retrieve data, status code: %s", response.status_code)
                return {
                        "status": OperationCodes.INTERNAL_EXCEPTION,
                        "message": f"Request failed with status code {response.status_code}",
                        "data": None
                    }

        except Exception as e:
            g_logger.error(f"Error occurred while querying node info: {e}")
            return {
                "status": OperationCodes.INTERNAL_EXCEPTION,
                "message": f"Error occurred: {str(e)}",
                "data": None
            }

    def vm_deploy(self, vm_config):
        vm_deploy_url = f"{self.base_url}/{constants.ROUTE_VM_DEPLOY_INTERNAL}"
        try:
            response = self.make_request(vm_deploy_url, method=constants.POST, json_data=vm_config)

            if response.status_code == HTTPStatusCodes.OK:
                return response.json()
            else:
                g_logger.error("Failed to deploy cvm, status code: %s", response.status_code)
                return {
                        "status": OperationCodes.INTERNAL_EXCEPTION,
                        "message": response.json(),
                        "data": None
                    }

        except Exception as e:
            g_logger.error(f"Error occurred while deploy vm: {e}")
            return {
                "status": OperationCodes.INTERNAL_EXCEPTION,
                "message": f"Error occurred: {str(e)}",
                "data": None
            }

    def vm_undeploy(self, vm_id: List[str]):
        vm_undeploy_url = f"{self.base_url}/{constants.ROUTE_VM_UNDEPLOY_INTERNAL}"
        try:
            response = self.make_request(vm_undeploy_url, method=constants.POST, json_data=vm_id)
            if response.status_code == HTTPStatusCodes.OK:
                return response.json()
            else:
                g_logger.error("Failed to undeploy cvm, status code: %s", response.status_code)
                return {
                        "status": OperationCodes.INTERNAL_EXCEPTION,
                        "message": response.json(),
                        "data": None
                }

        except Exception as e:
            g_logger.error(f"Error occurred while undeploy vm: {e}")
            return None

    def query_cvm_state(self):
        query_cvm_url = f"{self.base_url}/{constants.ROUTE_VM_STATE_INTERNAL}"
        try:
            return self.make_request(query_cvm_url, method=constants.GET)
        except Exception as e:
            g_logger.error(f"Error occurred while query cvm state: {e}")
            return None

    def collect_cvm_log(self, vm_name: str):
        log_collect_base_url = constants.ROUTE_VM_LOG_COLLECT_INTERNAL.replace("<vm_name>", vm_name)
        log_collect_url = f"{self.base_url}/{log_collect_base_url}"
        try:
            return self.make_request(log_collect_url, method=constants.GET)
        except Exception as e:
            g_logger.error(f"Error downloading file from {log_collect_url}: {e}")
            return None

    def upload_cvm_software(self, file_path):
        upload_cvm_software_url = f"{self.base_url}/{constants.ROUTE_VM_SOFTWARE_INTERNAL}"

        try:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                response = self.make_request(upload_cvm_software_url, method=constants.POST, files=files)
                if response.status_code == HTTPStatusCodes.OK:
                    return response.json()
                else:
                    g_logger.error("Failed to unload software, status code: %s", response.status_code)
                    return {
                            "status": OperationCodes.INTERNAL_EXCEPTION,
                            "message": response.json(),
                            "data": None
                    }
        except Exception as e:
            g_logger.error(f"Error upload file to {upload_cvm_software_url}: {e}")
            return None