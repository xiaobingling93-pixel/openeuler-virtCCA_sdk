#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import os
import configparser
import logging
import json
import ast
import ipaddress
from typing import List, Dict

LOG_DIR = "/var/log/virtcca_deploy"
DEVICE_STATUS_FILE = "/var/lib/virtcca_deploy/device_status.json"
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
        self.vlan_pool_manager = None

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

    def configure_device(self):
        net_list = self._load_net_list()
        self.device_manager = DeviceManager(net_list)

        return

    def configure_vlan_pool(self):
        self.vlan_pool_manager = VlanPoolManager()


class DeviceManager:
    def __init__(self, devices, status_file=DEVICE_STATUS_FILE):
        self.devices = devices
        self.status_file = status_file
        self.device_status = {}
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
        for device in self.device_status:
            status_info = self.device_status[device]
            if status_info["cvm_id"] == cvm_id:
                status_info["cvm_id"] = None
        self._save_device_status()


class IPPoolManager:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.network = ipaddress.IPv4Network(prefix, strict=False)
        self.ip_pool = list(self.network.hosts())
        self.vm_ip_mapping = {}

    def allocate_ips(self, node_ip: str, vm_name: str) -> str:
        """
        Assigns a specified number of IP addresses to a specified VM.
        :param vm_name: VM name
        :param num_ips: Number of IP addresses to be assigned
        :return: List of IP addresses assigned to the VM
        """
        ip = self.ip_pool.pop(0)
        ip_key = f"{node_ip}-{vm_name}"
        self.vm_ip_mapping[ip_key] = self.vm_ip_mapping.get(ip_key, []) + [str(ip)]

        return str(ip)

    def release_ips(self, node_ip: str, vm_name: str) -> None:
        """
        Release all IP addresses of a VM.
        :param vm_name: VM name
        """
        ip_key = f"{node_ip}-{vm_name}"
        if ip_key not in self.vm_ip_mapping:
            raise ValueError(f"VM {vm_name} on node {node_ip} not found in mapping.")

        for ip in self.vm_ip_mapping[ip_key]:
            self.ip_pool.append(ipaddress.IPv4Address(ip))

        del self.vm_ip_mapping[ip_key]


class VlanPoolManager:
    """
    manager IP pool based on VLAN ID
    """
    def __init__(self):
        self.vlan_ip_pool_map: Dict[int, IPPoolManager] = {}

    def add_vlan_pool(self, vlan_id: int, base_ip: str, prefix: int):
        """
        Creates and initializes an IP address pool for a VLAN ID.
        :param vlan_id: VLAN ID
        :param prefix: IP address prefix, for example, "192.168.1.0/24".
        :param initial_ips: (Optional) List of initial IP addresses.
        """
        if vlan_id in self.vlan_ip_pool_map:
            return

        ip_int = int(ipaddress.IPv4Address(base_ip))
        ip_bin = format(ip_int, '032b')
        vlan_bits = format(vlan_id % 256, '08b')
        ip_bin = ip_bin[:16] + vlan_bits + ip_bin[24:]
        vlan_ip = ipaddress.IPv4Address(int(ip_bin, 2))

        self.vlan_ip_pool_map[vlan_id] = IPPoolManager(f"{vlan_ip}/{prefix}")

    def allocate_vlan_ips(self, vlan_id: int, node_ip: str, vm_name: str) -> str:
        """
        Assigns IP addresses to VMs in a specified VLAN.
        :param vlan_id: VLAN ID
        :param vm_name: VM name
        :param num_ips: Number of IP addresses to be assigned
        :return: List of IP addresses assigned to the VMs
        """
        if vlan_id not in self.vlan_ip_pool_map:
            raise ValueError(f"VLAN {vlan_id} IP")

        ip_pool_manager = self.vlan_ip_pool_map[vlan_id]
        return ip_pool_manager.allocate_ips(node_ip, vm_name)

    def release_ips_for_vm(self, node_ip: str, vm_id: str) -> None:
        """
        Releases all IP addresses of a specified VM in all VLANs.
        :param vm_id: VM ID
        """
        for _, ip_pool_manager in self.vlan_ip_pool_map.items():
            ip_pool_manager.release_ips(node_ip, vm_id)
            g_logger.info("release IPs for CVM %s on %s", vm_id, node_ip)