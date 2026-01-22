#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import os
import configparser
import logging

LOG_DIR = "/var/log/virtcca_deploy"
g_logger = logging.getLogger("virtcca_deploy")


class Config:
    def __init__(self, config_path):
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"can not found {config_path} !")

        self.config = configparser.ConfigParser()
        self.config.read(config_path)
        self.logger = None
        self.ssl_cert = None    # manager cert

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
        ssl_cert = self.config.get('DEFAULT', 'manager_cert').strip().strip('"').strip("'")
        self.ssl_cert = os.path.abspath(ssl_cert)

        return