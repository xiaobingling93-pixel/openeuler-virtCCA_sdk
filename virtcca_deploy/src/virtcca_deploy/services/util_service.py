#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import virtcca_deploy.common.hardware as hardware


class UtilService:

    @staticmethod
    def get_hardware_info():
        return hardware.get_hardware_info()

    @staticmethod
    def get_node_info():
        hardware_info = hardware.get_hardware_info()
        virtcca_info = hardware.get_virtcca_info()

        secure_memory = 0
        secure_memory_free = 0
        secure_numa_topology = {}
        if virtcca_info:
            for node_id, info in virtcca_info.items():
                size = info["size"]
                free = info["free"]

                secure_memory += size
                secure_memory_free += free

                secure_numa_topology[node_id] = {
                    "size": size,
                    "free": free
                }

        hardware_info["secure_memory"] = secure_memory
        hardware_info["secure_memory_free"] = secure_memory_free
        hardware_info["secure_numa_topology"] = secure_numa_topology

        return hardware_info