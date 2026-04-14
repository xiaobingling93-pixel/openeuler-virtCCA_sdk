#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import os
import configparser
import logging
import json
import ast
import gevent
import gevent.lock
from typing import List, Dict

from virtcca_deploy.common import constants

LOG_DIR = constants.PathConfig.LOG_DIR
DEVICE_STATUS_FILE = constants.PathConfig.DEVICE_STATUS_FILE
g_logger = logging.getLogger("virtcca_deploy")


class Config:
    def __init__(self, config_path):
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"can not found {config_path} !")

        self.config = configparser.ConfigParser()
        self.config.read(config_path)
        self.logger = None
        self.ssl_cert = None    # ca cert
        self.device_manager = None

    def configure_log(self, log_name):
        if self.logger is not None:
            return self.logger

        log_dir = os.path.abspath(LOG_DIR)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        log_file = os.path.join(log_dir, log_name)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )

        self.logger = g_logger
        return self.logger

    def configure_ssl(self):
        ssl_cert = self.config.get('DEFAULT', 'ca_cert').strip().strip('"').strip("'")
        self.ssl_cert = os.path.abspath(ssl_cert)

        return
    def _load_net_list(self):
        if 'PCI' not in self.config:
            raise KeyError("PCI section not found in the configuration file.")

        pf_whitelist_str = self.config['PCI'].get('pf_whitelist', '[]')
        vf_whitelist_str = self.config['PCI'].get('vf_whitelist', '[]')
        net_list = [None, None]

        try:
            pf_list = ast.literal_eval(pf_whitelist_str)
            if not isinstance(pf_list, list):
                raise ValueError(f"pf_whitelist should be a list, got {type(pf_list).__name__}")

            vf_list = ast.literal_eval(vf_whitelist_str)
            if not isinstance(vf_list, list):
                raise ValueError(f"vf_whitelist should be a list, got {type(vf_list).__name__}")

            net_list[0] = pf_list
            net_list[1] = vf_list
            return net_list

        except (SyntaxError, ValueError) as e:
            raise ValueError(f"Error parsing PCI whitelist: {e}")
        except Exception as e:
            raise ValueError(f"Unexpected error while parsing PCI whitelist: {e}")

    def configure_auth(self):
        """配置认证相关参数，自动生成和管理JWT密钥"""
        import secrets
        import stat
        from virtcca_deploy.common import constants
        
        # 优先使用密钥文件
        jwt_secret_key_file = constants.JWT_SECRET_KEY_FILE
        self.jwt_secret_key = None
        
        # 检查密钥文件是否存在
        if os.path.exists(jwt_secret_key_file):
            try:
                # 读取密钥文件
                with open(jwt_secret_key_file, 'r') as f:
                    self.jwt_secret_key = f.read().strip()
                
                # 检查文件权限（应为600）
                file_mode = oct(os.stat(jwt_secret_key_file).st_mode)[-3:]
                if file_mode != '600':
                    g_logger.warning(f"JWT secret key file has insecure permissions ({file_mode}), setting to 600")
                    # 设置正确的权限
                    os.chmod(jwt_secret_key_file, stat.S_IRUSR | stat.S_IWUSR)  # 600权限
            except Exception as e:
                g_logger.error(f"Failed to read JWT secret key file: {e}")
        
        # 如果密钥文件不存在或读取失败，生成新密钥
        if not self.jwt_secret_key:
            g_logger.info(f"JWT secret key file not found or invalid, generating new key")
            # 生成强随机密钥
            self.jwt_secret_key = secrets.token_hex(64)
            
            try:
                os.makedirs(os.path.dirname(jwt_secret_key_file), exist_ok=True)
                
                # 写入密钥文件，设置600权限
                with open(jwt_secret_key_file, 'w') as f:
                    f.write(self.jwt_secret_key)
                
                # 设置权限
                os.chmod(jwt_secret_key_file, stat.S_IRUSR | stat.S_IWUSR)  # 600权限
                g_logger.info(f"Generated new JWT secret key and saved to {jwt_secret_key_file}")
            except Exception as e:
                g_logger.error(f"Failed to save JWT secret key: {e}")
                # 如果保存失败，使用临时密钥
                g_logger.warning("Using temporary JWT secret key (not persisted)")
        
        # 从配置文件读取其他认证参数
        self.jwt_expiration_minutes = self.config.getint('AUTH', 'jwt_expiration_minutes',
                                                         fallback=constants.DEFAULT_JWT_EXPIRATION_MINUTES)
        self.max_login_attempts = self.config.getint('AUTH', 'max_login_attempts',
                                                     fallback=constants.DEFAULT_MAX_LOGIN_ATTEMPTS)
        self.lockout_duration_minutes = self.config.getint('AUTH', 'lockout_duration_minutes',
                                                           fallback=constants.DEFAULT_LOCKOUT_DURATION_MINUTES)

    def configure_device(self):
        net_list = self._load_net_list()
        self.device_manager = DeviceManager(net_list)

        return


class DeviceManager:
    def __init__(self, devices, status_file=DEVICE_STATUS_FILE):
        self.devices = devices
        self.status_file = status_file
        self.device_status = {}
        self._lock = gevent.lock.RLock()
        all_devices = devices[0] + devices[1]

        if not os.path.exists(self.status_file):
            for device in all_devices:
                numa_node = self.get_device_numa_node(device)
                self.device_status[device] = {
                    "cvm_id": None,  # not in use
                    "numa_node": numa_node,
                    "type": "PF" if device in devices[0] else "VF"
                }
            self._save_device_status()
        else:
            self._load_device_status()

    def get_device_numa_node(self, device_id):
        try:
            numa_node_file = f"/sys/bus/pci/devices/{device_id}/numa_node"
            with open(numa_node_file, 'r') as f:
                numa_node = f.read().strip()
            return int(numa_node) if numa_node != 'invalid' else None  #  NUMA 
        except FileNotFoundError:
            g_logger.warn("Cannot find device %s numa file", device_id)
            return None
        except Exception as e:
            g_logger.warn("Failed to read device %s numa file: %s", device_id, e)
            return None

    def _load_device_status(self):
        with open(self.status_file, "r") as f:
            self.device_status = json.load(f)

    def _save_device_status(self):
        with open(self.status_file, "w") as f:
            json.dump(self.device_status, f, indent=4)

    def use_device(self, device_id: str, cvm_id: str):
        with self._lock:
            if device_id not in self.device_status:
                g_logger.error("Device %s is not exist!", device_id)
                return False

            device = self.device_status[device_id]
            if device["cvm_id"]:
                g_logger.error("Device %s is in use!", device_id)
                return False
            else:
                device["cvm_id"] = cvm_id
                self._save_device_status()
                g_logger.info("Device %s has been successfully used.", device_id)
                return True

    def get_available_device(self, device_type: str, numa_node: int = None):
        with self._lock:
            if device_type not in ["PF", "VF"]:
                g_logger.error("Invalid device type. Please specify 'PF' or 'VF'.")
                return None

            available_devices = []
            for device in self.device_status:
                status_info = self.device_status[device]
                if status_info["type"] != device_type or status_info["cvm_id"]:
                    continue
                if numa_node is not None and status_info["numa_node"] != numa_node:
                    continue
                available_devices.append(device)

            return available_devices

    def release_device_by_cvm_id(self, cvm_id: str):
        with self._lock:
            for device in self.device_status:
                status_info = self.device_status[device]
                if status_info["cvm_id"] == cvm_id:
                    status_info["cvm_id"] = None
            self._save_device_status()
