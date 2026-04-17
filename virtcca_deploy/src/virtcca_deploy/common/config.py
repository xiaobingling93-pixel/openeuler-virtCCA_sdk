#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import os
import configparser
import logging
from typing import List, Dict

from virtcca_deploy.common import constants

LOG_DIR = constants.PathConfig.LOG_DIR
g_logger = logging.getLogger("virtcca_deploy")


class Config:
    def __init__(self, config_path):
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"can not found {config_path} !")

        self.config = configparser.ConfigParser()
        self.config.read(config_path)
        self.logger = None
        self.ssl_cert = None
        self.device_allocator = None

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
        self.jwt_expiration_minutes = constants.DEFAULT_JWT_EXPIRATION_MINUTES
        self.max_login_attempts = constants.DEFAULT_MAX_LOGIN_ATTEMPTS
        self.lockout_duration_minutes = constants.DEFAULT_LOCKOUT_DURATION_MINUTES
