#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from typing import List, Tuple, Optional, Dict, Set
import os
import re
import shutil
import ipaddress
import tempfile
import threading
import xml.etree.ElementTree as ET
from contextlib import contextmanager
import time
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

from flask import current_app
import libvirt
import subprocess

from virtcca_deploy.common.data_model import (
    VmDeploySpecInternal, VmDeploySpec, DeviceAllocReq, DeviceReleaseReq, SriovVfSetupResp, VmInterface
)
import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants
import virtcca_deploy.common.hardware as hardware
import virtcca_deploy.services.util_service as util_service
import virtcca_deploy.services.resource_allocator as resource_allocator

g_logger = config.g_logger
NET_CONFIG_PATH = "/etc/sysconfig/network-scripts"
VIRBR0_NETWORK_NAME = "default"
DHCP_CONFIG_DIR = "/var/lib/libvirt/dnsmasq"
MAC_OUI_PREFIX = "52:54:00"

_virbr0_config_lock = threading.Lock()


@dataclass
class DhcpEntryInfo:
    """DHCP entry information for cleanup"""
    mac_address: str = ""
    ip_address: str = ""


@dataclass
class CvmReclaimContext:
    """
    Structured parameter input for cvm_resource_reclaim

    Designed for extensibility: new fields can be added without changing
    the function signature, maintaining backward compatibility.
    """
    cvm_name: str = ""
    server_config: Optional[config] = None
    dhcp_entries: List[DhcpEntryInfo] = field(default_factory=list)
    network_name: str = ""


@dataclass
class Virbr0NetworkInfo:
    """virbr0 network configuration information"""
    network_name: str = ""
    bridge_name: str = ""
    ip_address: str = ""
    netmask: str = ""
    subnet_cidr: str = ""
    dhcp_start: str = ""
    dhcp_end: str = ""
    subnet_network: Optional[ipaddress.IPv4Network] = None
    existing_leases: List[Dict[str, str]] = field(default_factory=list)
    existing_macs: Set[str] = field(default_factory=set)
    existing_ips: Set[str] = field(default_factory=set)


@dataclass
class MacIpPair:
    """Generated MAC and IP address pair"""
    mac_address: str = ""
    ip_address: str = ""


@dataclass
class VmDeploymentContext:
    """Per-VM deployment context carrying state across phases"""
    cvm_name: str
    vm_spec: VmDeploySpec
    host_numa_id: int = -1
    device_dict: dict = field(default_factory=dict)
    ip_list: List[str] = field(default_factory=list)
    qcow2_path: str = ""
    data_disk_path: str = ""
    xml_config: str = ""
    error_message: str = ""
    success: bool = False
    network_check_result: Optional["NetworkCheckResult"] = None
    virtbr0_mac_addr: str = ""
    virtbr0_ip: str = ""


class DeploymentException(Exception):
    """Exception that carries VmDeploymentContext for resource cleanup"""
    def __init__(self, message: str, ctx: VmDeploymentContext):
        super().__init__(message)
        self.ctx = ctx


def handle_vm_id(root, value):
    name_node = root.find(".//name")
    if name_node is not None:
        name_node.text = str(value)
    else:
        raise Exception("CVM template xml is invalid!")

def handle_memory(root, value):
    memory_node = root.find(".//memory")
    if memory_node is not None:
        memory_node.text = str(value)
        memory_node.set('unit', 'MiB')
    else:
        raise Exception("CVM template xml is invalid!")

def handle_cputune(root, cpuset_start, cpu_num):
    cputune = ET.Element("cputune")
    for i in range(0, int(cpu_num)):
        ET.SubElement(cputune, "vcpupin", vcpu=str(i), cpuset=str(cpuset_start + i))

    ET.SubElement(cputune, "emulatorpin", cpuset=f"{cpuset_start}-{cpuset_start + i}")

    vcpu = root.find("vcpu")
    if vcpu is not None:
        index = list(root).index(vcpu)

    root.insert(index + 1, cputune)

def handle_numatune(root, host_numa_id, core_num, mem_size):
    numatune = ET.Element("numatune")
    ET.SubElement(numatune, "memnode", cellid='0', mode="strict", nodeset=str(host_numa_id))

    vcpu = root.find("vcpu")
    if vcpu is not None:
        index = list(root).index(vcpu)
    root.insert(index + 1, numatune)

    guest_numa = ET.Element("numa")
    ET.SubElement(guest_numa, "cell", id='0', cpus=f"0-{core_num-1}", memory=str(mem_size), unit="MiB")
    cpu = root.find("cpu")
    if cpu is not None:
        cpu.append(guest_numa)

def handle_topology(root, host_numa_id, core_num, mem_size):
    # The topology needs to be modified to be consistent with the CPU.
    topology_node = root.find(".//topology")
    if topology_node is not None:
        topology_node.set('cores', str(core_num))
    else:
        raise Exception("CVM template xml is invalid!")

    numa_info = hardware.get_numa_cpu_topology()
    cpuset_start = numa_info[host_numa_id][0]
    handle_cputune(root, cpuset_start, core_num)
    handle_numatune(root, host_numa_id, core_num, mem_size)

def handle_vcpu(root, cpu_num):
    vcpu_node = root.find(".//vcpu")
    if vcpu_node is not None:
        vcpu_node.text = str(cpu_num)
    else:
        raise Exception("CVM template xml is invalid!")

def handle_disk(root, qcow2_file):
    disk_element = root.find(".//disk[@type='file'][@device='disk']")

    if disk_element is not None:
        source_element = disk_element.find("source")
        if source_element is not None:
            source_element.set('file', qcow2_file)
            return
        else:
            g_logger.error("<source> element not found.")
    else:
        g_logger.error("<disk> element with the specified attributes not found.")
    raise Exception("CVM template xml is invalid!")

def handle_data_disk(root, data_disk_file: str):
    devices_node = root.find(".//devices")
    if devices_node is None:
        raise Exception("CVM template xml is invalid, unable to find element 'devices'!")

    new_disk = ET.SubElement(devices_node, "disk", type='file', device='disk')
    ET.SubElement(new_disk, "driver", name='qemu', type='qcow2', cache='none', queues='2', iommu='on')
    ET.SubElement(new_disk, "source", file=data_disk_file)
    ET.SubElement(new_disk, "target", dev='vdb', bus='virtio')
    ET.SubElement(new_disk, "address", type='pci', domain='0x0000', bus='0x03', slot='0x00', function='0x0')

    g_logger.info("Added data disk %s at bus 0x03", data_disk_file)

import xml.etree.ElementTree as ET
import logging

g_logger = logging.getLogger(__name__)

def handle_pci(root, pci_dict: dict):
    """
    Add PCI devices to the VM XML based on the mac_address: bdf dictionary.
    
    :param root: The root XML element of the VM configuration.
    :param pci_dict: Dictionary with mac_address as the key and bdf as the value.
    """
    device_node = root.find(".//devices")
    if device_node is not None:
        for mac_address, bdf in pci_dict.items():
            # Create the hostdev node for the PCI device
            hostdev_node = ET.SubElement(device_node, "hostdev", mode='subsystem', type='pci', managed='yes')
            ET.SubElement(hostdev_node, 'driver', name='vfio')
            source_node = ET.SubElement(hostdev_node, 'source')

            # Log the information
            g_logger.info("Adding PCI device with MAC: %s, BDF: %s", mac_address, bdf)
            
            # Parse the BDF to extract domain, bus, slot, and function
            try:
                domain, bus_slot_function = bdf.split(":", 1)
                bus, slot_function = bus_slot_function.split(":", 1)
                slot, function = slot_function.split(".") if "." in slot_function else (slot_function, None)

                if not domain or not bus or not slot or not function:
                    raise ValueError(f"Invalid PCI address: {bdf}. Components cannot be empty!")

                # Add the PCI address to the XML
                ET.SubElement(source_node, "address",
                              domain=f"0x{domain}",
                              bus=f"0x{bus}",
                              slot=f"0x{slot}",
                              function=f"0x{function}")

                # Optionally, add the MAC address as an additional attribute or element if needed
                # Example: Adding MAC as an attribute to the hostdev node (if you want this in XML)
                hostdev_node.set("mac", mac_address)
                
            except Exception as e:
                g_logger.error(f"Error while adding PCI device with MAC {mac_address} and BDF {bdf}: {e}")
                raise

    else:
        raise Exception("CVM template XML is invalid, unable to find element 'devices'!")


def handle_serial(root, cvm_name: str):
    """
    Add a serial device to the VM XML and configure the log output path for the serial device.

    :param root: The root XML element of the VM configuration.
    :param cvm_name: The name of the VM, used to set the log file path.
    """
    device_node = root.find(".//devices")
    
    if device_node is not None:
        # Create the serial device node
        serial_node = ET.SubElement(device_node, "serial", type="pty")
        
        # Add the target port to the serial node
        ET.SubElement(serial_node, "target", port="0")  # Port 0 can be adjusted as needed
        
        # Configure logging for the serial device
        log_file_path = f"/var/log/libvirt/qemu/{cvm_name}_serial.log"
        ET.SubElement(serial_node, "log", file=log_file_path)
        
        # Log the information
        g_logger.info(f"Adding serial device to VM {cvm_name} with log path: {log_file_path}")
        
    else:
        raise Exception("CVM template XML is invalid, unable to find element 'devices'!")

def handle_virbr0(root, mac_addr: str):
    devices_node = root.find(".//devices")
    if devices_node is None:
        raise Exception("CVM template xml is invalid, unable to find element 'devices'!")

    found = False
    for iface in devices_node.findall("interface"):
        source = iface.find("source")
        if source is not None and source.get("bridge") == "virbr0":
            mac_node = iface.find("mac")
            if mac_node is not None:
                mac_node.set("address", mac_addr)
            else:
                mac_node = ET.SubElement(iface, "mac", address=mac_addr)

            found = True
            break

    if not found:
        raise Exception("No interface with bridge 'virbr0' found in XML!")


def config_xml(ctx: VmDeploymentContext) -> str:
    """
    Modify the XML configuration and return the XML string.

    Args:
        cvm_name: Name of the CVM
        vm_deploy_spec: VmDeploySpec configuration object
        qcow2_file: Path to the QCOW2 file
        data_disk_file: Optional path to the data disk QCOW2 file
    
    Returns:
        The modified XML as a string, or "" if an error occurs
    """
    if not ctx.vm_spec or not ctx.vm_spec.is_valid():
        g_logger.error("Invalid VmDeploySpec configuration")
        return ""

    template_xml = constants.CVM_TEMPLATE_XML
    try:
        tree = ET.parse(template_xml)
        root = tree.getroot()
    except ET.ParseError as e:
        g_logger.error("XML parsing error occurred, %s", e)
        return ""
    except FileNotFoundError:
        g_logger.error("Template file not found: %s", template_xml)
        return ""
    except Exception as e:
        g_logger.error("Error reading template file %s", e)
        return ""

    try:
        handle_memory(root, ctx.vm_spec.memory)
        handle_vcpu(root, ctx.vm_spec.core_num)
        handle_topology(root, ctx.host_numa_id, ctx.vm_spec.core_num, ctx.vm_spec.memory)
        handle_disk(root, ctx.qcow2_path)
        handle_vm_id(root, ctx.cvm_name)
        handle_serial(root, ctx.cvm_name)
        handle_virbr0(root, ctx.virtbr0_mac_addr)
        if ctx.device_dict:
            handle_pci(root, ctx.device_dict)
        if ctx.data_disk_path:
            handle_data_disk(root, ctx.data_disk_path)
    except Exception as e:
        g_logger.error("Error during configuration of XML, %s", e)
        return ""

    return ET.tostring(root, encoding="unicode", method="xml")

def config_disk(cvm_name: str, file_path: str, ip_list: List[str], server_config: config, disk_size: int = 0) -> Tuple[str, Optional[str]]:
    base_qcow2 = constants.BASE_QCOW2
    file_name = f"{cvm_name}.qcow2"
    os.makedirs(file_path, exist_ok=True)
    new_qcow2_path = os.path.join(file_path, file_name)

    try:
        shutil.copy2(base_qcow2, new_qcow2_path)
        g_logger.info("Copied %s to %s", base_qcow2, new_qcow2_path)
    except FileNotFoundError:
        g_logger.error("Base QCOW2 file %s not found.", base_qcow2)
        return "", None
    except Exception as e:
        g_logger.error("Error while copying QCOW2 file: %s", e)
        return "", None

    data_disk_path = None
    if disk_size > 0:
        if disk_size < constants.MIN_DISK_SIZE_GB:
            g_logger.error("disk_size %d GB is below minimum %d GB", disk_size, constants.MIN_DISK_SIZE_GB)
            return "", None

        data_disk_name = f"{cvm_name}_data.qcow2"
        data_disk_path = os.path.join(file_path, data_disk_name)

        try:
            create_cmd = [
                "qemu-img", "create",
                "-f", "qcow2",
                data_disk_path,
                f"{disk_size}G"
            ]
            result = subprocess.run(
                create_cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                g_logger.error("Failed to create data disk: %s", result.stderr)
                return "", None

            g_logger.info("Created data disk %s with size %d GB", data_disk_path, disk_size)
        except subprocess.TimeoutExpired:
            g_logger.error("Timeout while creating data disk %s", data_disk_path)
            return "", None
        except FileNotFoundError:
            g_logger.error("qemu-img command not found")
            return "", None
        except Exception as e:
            g_logger.error("Error creating data disk: %s", e)
            return "", None

    return new_qcow2_path, data_disk_path

def config_net(ip_list: List[str], perfix: str):
    net_template = constants.PathConfig.IFCTL_TEMPLATE
    if not os.path.exists(net_template):
        raise FileNotFoundError(f"Template file not found: {net_template}")

    with open(net_template, 'r') as template_file:
        template_content = template_file.read()

    for i, ip in enumerate(ip_list):
        config_content = str(template_content)
        # Replace the placeholder in the template with the actual IP
        net_name =  f"eth{i+1}"
        config_content = config_content.replace("${IPADDR}", ip)
        config_content = config_content.replace("${DEVICE}", net_name)
        config_content = config_content.replace("${NAME}", net_name)
        config_content = config_content.replace("${PREFIX}", perfix)

        # Define the new network configuration file name
        net_file = f"{constants.MOUNT_PATH}/{NET_CONFIG_PATH}/ifcfg-{net_name}"

        # Write the modified content to the new network config file
        with open(net_file, 'w') as net_config_file:
            net_config_file.write(config_content)

        g_logger.info(f"Network config file created: {net_file} with IP {ip}")


def cvm_name_check(vm_id_list: List[str]) -> str:
    libvirt = libvirtDriver()
    vm_dict = libvirt.list_all_vm()
    for vm_id in vm_id_list:
        if vm_id in vm_dict:
            return f"CVM name '{vm_id}' is already exist"
    return None

def cvm_numa_check(core_num: int, mem_size: int, vm_num: int) -> Tuple[Optional[List[int]], str]:
    secure_numa_info = hardware.get_virtcca_info()
    non_secure_numa_info = hardware.get_numa_cpu_topology()

    if len(secure_numa_info) < vm_num:
        return None, (
            f"CVMs deploy failed, the number of secure NUMA nodes {len(secure_numa_info)} is "
            f"less than vm_num {vm_num}."
        )

    available_nodes = []
    for i in range(len(non_secure_numa_info)):
        if core_num <= len(non_secure_numa_info[i]) and mem_size <= secure_numa_info[i]["free"]:
            available_nodes.append(i)
        if len(available_nodes) == vm_num:
            break

    if len(available_nodes) < vm_num:
        return None, (
            f"CVMs deploy failed, the number of availabe nodes {len(available_nodes)} "
            f"is less than vm_num {vm_num}."
        )

    return available_nodes, None

def cvm_device_alloc(
    cvm_name: str,
    vm_spec: VmDeploySpec,
    server_config: config,
    iface_list: List[VmInterface]
) -> Tuple[dict, str]:
    if vm_spec.net_pf_num + vm_spec.net_vf_num == 0:
        return {}, None
    try:
        iface_mac = [iface.mac_address for iface in iface_list if iface and iface.mac_address]
        req = DeviceAllocReq(
            vm_id=cvm_name,
            pf_num=vm_spec.net_pf_num,
            vf_num=vm_spec.net_vf_num,
            iface=iface_mac
        )

        result = server_config.device_allocator.allocate(req)

    except Exception as e:
        err_msg = f"Device allocation exception for VM {cvm_name}: {e}"
        g_logger.error(err_msg)
        return {}, err_msg

    if result.success:
        return result.device_dict, None

    err_msg = (
        f"Device allocation failed for VM {cvm_name}: "
        f"need {vm_spec.net_pf_num} PF + {vm_spec.net_vf_num} VF"
    )
    g_logger.error(err_msg)
    return {}, err_msg

def cvm_net_check(ip_list: List[str], retries: int = 5, delay: int = 3) -> List[str]:
    """
    check cvm network by ping
    """
    g_logger.info("Test network for cvm, ip list: %s", ip_list)
    unreachable_ips = []

    for ip in ip_list:
        attempts = 0
        success = False

        while attempts < retries and not success:
            try:
                result = subprocess.run(
                    ['ping', '-c', '1', ip],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

                if result.returncode == 0:
                    success = True
                else:
                    attempts += 1
                    time.sleep(delay)
            except Exception as e:
                unreachable_ips.append(ip)
                break

        if not success:
            unreachable_ips.append(ip)

    return unreachable_ips

def _cleanup_dhcp_entry(network_name: str, mac_address: str, ip_address: str):
    """清理 DHCP 条目，失败时记录日志但不抛出异常"""
    try:
        driver = libvirtDriver()
        success, err_msg = driver.remove_dhcp_host_entry(network_name, mac_address, ip_address)
        if success:
            g_logger.info("DHCP entry removed: mac=%s, ip=%s", mac_address, ip_address)
        else:
            g_logger.warning("Failed to remove DHCP entry (non-fatal): %s", err_msg)
    except Exception as e:
        g_logger.error("Exception during DHCP cleanup (non-fatal): %s", e)


def _cleanup_vm_instance(cvm_name: str):
    """清理 VM 实例（销毁或取消定义）"""
    try:
        libvirt = libvirtDriver()
        if libvirt.is_vm_running(cvm_name):
            libvirt.destroy_cvm_by_name(cvm_name)
            g_logger.info("Destroyed running VM: %s", cvm_name)
        else:
            libvirt.undefine_cvm_by_name(cvm_name)
            g_logger.info("Undefined stopped VM: %s", cvm_name)
    except Exception as e:
        g_logger.error("Exception during VM instance cleanup (non-fatal): %s", e)


def _cleanup_disk_files(cvm_name: str, server_config: config):
    """清理磁盘镜像文件"""
    try:
        qcow2_dir = server_config.config.get("DEFAULT", "cvm_image_path")
        file_name = f"{cvm_name}.qcow2"
        qcow2_path = os.path.join(qcow2_dir, file_name)
        if os.path.exists(qcow2_path):
            os.remove(qcow2_path)
            g_logger.info("Removed system disk: %s", qcow2_path)

        data_disk_name = f"{cvm_name}_data.qcow2"
        data_disk_path = os.path.join(qcow2_dir, data_disk_name)
        if os.path.exists(data_disk_path):
            os.remove(data_disk_path)
            g_logger.info("Removed data disk: %s", data_disk_path)
    except Exception as e:
        g_logger.error("Exception during disk cleanup (non-fatal): %s", e)


def _cleanup_device_allocation(cvm_name: str, server_config: config):
    """释放设备分配"""
    try:
        server_config.device_allocator.release(DeviceReleaseReq(vm_id=cvm_name))
        g_logger.info("Released device allocation for: %s", cvm_name)
    except Exception as e:
        g_logger.error("Exception during device release (non-fatal): %s", e)


def _find_dhcp_entries_by_hostname(hostname: str, network_name: str = None) -> List[DhcpEntryInfo]:
    """
    根据主机名扫描 DHCP 条目，查找所有关联的 MAC/IP 地址

    支持虚拟机多网卡场景，返回所有匹配该主机名的 DHCP 条目。

    :param hostname: VM 主机名
    :param network_name: libvirt 网络名称
    :return: DhcpEntryInfo 列表，未找到返回空列表
    """
    if network_name is None:
        network_name = VIRBR0_NETWORK_NAME
    try:
        driver = libvirtDriver()
        network_info, err_msg = driver.query_virbr0_config(network_name)
        if err_msg or not network_info:
            g_logger.warning("Failed to query network config for hostname lookup: %s", err_msg)
            return []

        entries = []
        for lease in network_info.existing_leases:
            lease_hostname = lease.get("hostname", "")
            if lease_hostname == hostname:
                mac = lease.get("mac", "")
                ip = lease.get("ipaddr", "")
                if mac and ip:
                    entries.append(DhcpEntryInfo(mac_address=mac, ip_address=ip))

        if entries:
            g_logger.info(
                "Found %d DHCP entries for hostname '%s': %s",
                len(entries), hostname,
                [(e.mac_address, e.ip_address) for e in entries]
            )
        else:
            g_logger.info("No DHCP entry found for hostname '%s'", hostname)

        return entries

    except Exception as e:
        g_logger.error("Exception during DHCP entry lookup for '%s': %s", hostname, e)
        return []


def _find_dhcp_entry_by_hostname(hostname: str, network_name: str = None) -> Tuple[str, str]:
    """
    根据主机名扫描 DHCP 条目，查找对应的 MAC/IP 地址（向后兼容接口）

    :param hostname: VM 主机名
    :param network_name: libvirt 网络名称
    :return: (mac_address, ip_address) 元组，未找到返回 ("", "")
    """
    entries = _find_dhcp_entries_by_hostname(hostname, network_name)
    if entries:
        return entries[0].mac_address, entries[0].ip_address
    return "", ""


def _cleanup_dhcp_entries(network_name: str, dhcp_entries: List[DhcpEntryInfo]):
    """批量清理多个 DHCP 条目，失败时记录日志但不抛出异常"""
    if not dhcp_entries:
        return

    for entry in dhcp_entries:
        if entry.mac_address and entry.ip_address:
            _cleanup_dhcp_entry(network_name, entry.mac_address, entry.ip_address)


def cvm_resource_reclaim(
    cvm_name: str = "",
    server_config: config = None,
    mac_address: str = "",
    ip_address: str = "",
    network_name: str = None,
    reclaim_ctx: CvmReclaimContext = None,
):
    """
    清理 CVM 相关资源，包括：
    1. 删除 DHCP 主机条目（恢复 libvirt 网桥配置）
    2. 销毁或取消定义虚拟机
    3. 删除磁盘镜像文件
    4. 释放设备分配

    支持两种调用方式：
    - 向后兼容：使用独立参数 (cvm_name, server_config, mac_address, ip_address, network_name)
    - 结构化参数：使用 reclaim_ctx (CvmReclaimContext)，支持多 DHCP 条目和未来扩展

    采用"尽力清理"策略：单步失败不阻断后续清理
    """
    if reclaim_ctx is not None:
        cvm_name = reclaim_ctx.cvm_name or cvm_name
        server_config = reclaim_ctx.server_config or server_config
        network_name = reclaim_ctx.network_name or network_name
        dhcp_entries = reclaim_ctx.dhcp_entries
    else:
        if mac_address and ip_address:
            dhcp_entries = [DhcpEntryInfo(mac_address=mac_address, ip_address=ip_address)]
        else:
            dhcp_entries = []

    if network_name is None:
        network_name = VIRBR0_NETWORK_NAME

    g_logger.info("Clean up the resource of %s", cvm_name)

    _cleanup_dhcp_entries(network_name, dhcp_entries)

    _cleanup_vm_instance(cvm_name)

    _cleanup_disk_files(cvm_name, server_config)

    _cleanup_device_allocation(cvm_name, server_config)

def _ensure_sriov_vf_resources(
    device_allocator: resource_allocator.DeviceManagerAllocator,
    required_vf_count: int,
    total_vm_count: int,
) -> Optional[str]:
    """
    确保 SR-IOV VF 资源满足部署需求

    1. 查询当前可用 VF 数量
    2. 若不足，扫描可用 PF 并调用 setup_sriov_vf 创建 VF
    3. 创建后重新扫描设备并同步数据库，再次检查 VF 可用性

    :param device_allocator: 设备分配器实例
    :param required_vf_count: 每台 VM 所需的 VF 数量
    :param total_vm_count: 待部署的 VM 总数
    :return: 错误信息字符串，资源充足时返回 None
    """
    total_required = required_vf_count * total_vm_count

    available_vfs = device_allocator.get_available_devices(
        constants.DeviceTypeConfig.DEVICE_TYPE_NET_VF
    )
    available_vf_count = len(available_vfs)
    g_logger.info(
        f"SR-IOV VF resource check: required={total_required}, "
        f"available={available_vf_count}"
    )

    if available_vf_count >= total_required:
        g_logger.info("Sufficient SR-IOV VF resources available, no provisioning needed")
        return None

    shortage = total_required - available_vf_count
    g_logger.info(
        f"Insufficient VF resources (shortage={shortage}), "
        f"scanning for available PFs to provision VFs"
    )

    available_pfs = device_allocator.get_available_devices(
        constants.DeviceTypeConfig.DEVICE_TYPE_NET_PF
    )
    if not available_pfs:
        err_msg = (
            f"Insufficient SR-IOV VF/PF resources available for CVM deployment: "
            f"need {total_required} VF(s), have {available_vf_count} VF(s) "
            f"and no available PF(s) to provision"
        )
        g_logger.error(err_msg)
        return err_msg

    for pf in available_pfs:
        if shortage <= 0:
            break

        pf_device_name = pf.get("device_name")
        if not pf_device_name:
            g_logger.warning(
                f"PF device {pf['bdf']} has no device_name, skipping for SR-IOV setup"
            )
            continue

        vf_to_create = min(shortage, _get_pf_max_vf_capacity(pf_device_name))
        if vf_to_create <= 0:
            g_logger.warning(
                f"PF device {pf_device_name} reports zero VF capacity, skipping"
            )
            continue

        g_logger.info(
            f"Provisioning {vf_to_create} VF(s) on PF {pf_device_name} "
            f"(BDF={pf['bdf']})"
        )
        result: SriovVfSetupResp = device_allocator.setup_sriov_vf(
            pf_device_name, vf_to_create
        )
        if not result.success:
            g_logger.error(
                f"Failed to provision VF(s) on PF {pf_device_name}: {result.message}"
            )
            continue

        g_logger.info(
            f"Successfully provisioned {vf_to_create} VF(s) on PF {pf_device_name}"
        )
        shortage -= vf_to_create

    if shortage > 0:
        err_msg = (
            f"Insufficient SR-IOV VF/PF resources available for CVM deployment: "
            f"need {total_required} VF(s), still short {shortage} after provisioning"
        )
        g_logger.error(err_msg)
        return err_msg

    g_logger.info("Rescanning PCI devices after SR-IOV VF provisioning")
    device_allocator.find_device(
        vendor_id=constants.DeviceTypeConfig.HUAWEI_VENDOR_ID,
        device_id=constants.DeviceTypeConfig.HI1822_VF_DEVICE_ID,
        refresh=True,
    )
    device_allocator.sync_discovered_to_db()

    recheck_vfs = device_allocator.get_available_devices(
        constants.DeviceTypeConfig.DEVICE_TYPE_NET_VF
    )
    if len(recheck_vfs) < total_required:
        err_msg = (
            f"Insufficient SR-IOV VF/PF resources available for CVM deployment: "
            f"after provisioning, found {len(recheck_vfs)} VF(s) but need {total_required}"
        )
        g_logger.error(err_msg)
        return err_msg

    g_logger.info(
        f"SR-IOV VF resources confirmed: {len(recheck_vfs)} VF(s) available"
    )
    return None


def _get_pf_max_vf_capacity(pf_device_name: str) -> int:
    """
    读取 PF 设备支持的最大 VF 数量

    从 /sys/class/net/${pf_device_name}/device/sriov_totalvfs 读取

    :param pf_device_name: PF 网络接口名称
    :return: 最大 VF 数量，读取失败返回 0
    """
    totalvfs_path = os.path.join(
        "/sys/class/net", pf_device_name, "device/sriov_totalvfs"
    )
    try:
        with open(totalvfs_path, 'r') as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError) as e:
        g_logger.warning(
            f"Failed to read sriov_totalvfs for {pf_device_name}: {e}"
        )
        return 0


class NetworkCheckType(Enum):
    """Network check item types"""
    INTERFACE_STATUS = "interface_status"
    IP_CONFIGURATION = "ip_configuration"
    GATEWAY_REACHABILITY = "gateway_reachability"
    SERVICE_PORT_AVAILABILITY = "service_port_availability"
    EXTERNAL_CONNECTIVITY = "external_connectivity"


@dataclass
class NetworkCheckConfig:
    """Configuration for network connectivity checks"""
    init_wait_timeout: int = 300
    init_wait_interval: int = 10
    check_timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 5
    external_targets: List[str] = field(default_factory=list)
    service_ports: List[int] = field(default_factory=list)


@dataclass
class NetworkCheckItemResult:
    """Result of a single network check item"""
    check_type: NetworkCheckType
    success: bool
    message: str = ""
    details: str = ""
    attempts: int = 0
    duration_ms: int = 0


@dataclass
class NetworkCheckResult:
    """Aggregated result of all network checks for a VM"""
    cvm_name: str
    overall_success: bool = False
    check_items: List[NetworkCheckItemResult] = field(default_factory=list)
    total_duration_ms: int = 0
    error_message: str = ""


def _phase5_validate_network(
    ctx: VmDeploymentContext,
    server_config: config,
    check_config: Optional[NetworkCheckConfig] = None,
) -> VmDeploymentContext:
    """
    Phase 5: Network Connectivity Validation

    Execute comprehensive network checks after VM initialization:
    1. Interface status verification
    2. IP configuration validation
    3. Gateway reachability test
    4. Service port availability detection
    5. External network connectivity test

    Args:
        ctx: VM deployment context
        server_config: Server configuration
        check_config: Optional network check configuration

    Returns:
        Updated VmDeploymentContext with network check results
    """
    if ctx.error_message:
        return ctx

    if check_config is None:
        check_config = NetworkCheckConfig()

    g_logger.info(
        "Phase 5 (Network Validation) starting for %s", ctx.cvm_name
    )

    check_result = NetworkCheckResult(cvm_name=ctx.cvm_name)

    try:
        _wait_for_vm_initialization(ctx.cvm_name, check_config)

        check_items = [
            (NetworkCheckType.INTERFACE_STATUS, _check_interface_status),
            (NetworkCheckType.IP_CONFIGURATION, _check_ip_configuration),
            (NetworkCheckType.GATEWAY_REACHABILITY, _check_gateway_reachability),
            (NetworkCheckType.SERVICE_PORT_AVAILABILITY, _check_service_ports),
            (NetworkCheckType.EXTERNAL_CONNECTIVITY, _check_external_connectivity),
        ]

        for check_type, check_func in check_items:
            item_result = check_func(ctx, check_config)
            check_result.check_items.append(item_result)

            if not item_result.success:
                g_logger.warning(
                    "Network check '%s' failed for %s: %s",
                    check_type.value, ctx.cvm_name, item_result.message
                )

        check_result.overall_success = all(
            item.success for item in check_result.check_items
        )

    except Exception as e:
        check_result.error_message = str(e)
        g_logger.error(
            "Phase 5 (Network Validation) error for %s: %s",
            ctx.cvm_name, e
        )

    ctx.network_check_result = check_result

    g_logger.info(
        "Phase 5 (Network Validation) completed for %s: %s",
        ctx.cvm_name, "PASSED" if check_result.overall_success else "FAILED"
    )
    return ctx


def _wait_for_vm_initialization(
    cvm_name: str,
    check_config: NetworkCheckConfig,
) -> None:
    """
    Wait for VM to complete initialization before network checks.

    TODO: Implement VM initialization detection logic
    - Check VM running state via libvirt
    - Wait for guest agent to be ready
    - Monitor boot completion indicators
    """
    g_logger.info(
        "Waiting for %s initialization (timeout=%ds)",
        cvm_name, check_config.init_wait_timeout
    )
    pass


def _check_interface_status(
    ctx: VmDeploymentContext,
    config: NetworkCheckConfig,
) -> NetworkCheckItemResult:
    """
    Verify VM internal network interface status.

    TODO: Implement interface status check logic
    - List all network interfaces in VM
    - Verify interface state (UP/DOWN)
    - Check link status and MTU configuration
    - Validate expected interfaces are present
    """
    result = NetworkCheckItemResult(
        check_type=NetworkCheckType.INTERFACE_STATUS,
        success=False,
        message="Not implemented"
    )
    return result


def _check_ip_configuration(
    ctx: VmDeploymentContext,
    config: NetworkCheckConfig,
) -> NetworkCheckItemResult:
    """
    Confirm IP address configuration correctness.

    TODO: Implement IP configuration validation logic
    - Verify assigned IP addresses match expected values
    - Check subnet mask configuration
    - Validate IP address assignment method (DHCP/Static)
    - Detect IP conflicts or misconfigurations
    """
    result = NetworkCheckItemResult(
        check_type=NetworkCheckType.IP_CONFIGURATION,
        success=False,
        message="Not implemented"
    )
    return result


def _check_gateway_reachability(
    ctx: VmDeploymentContext,
    config: NetworkCheckConfig,
) -> NetworkCheckItemResult:
    """
    Test gateway reachability.

    TODO: Implement gateway reachability test logic
    - Ping default gateway
    - Verify ARP resolution
    - Test routing table correctness
    - Measure gateway latency
    """
    result = NetworkCheckItemResult(
        check_type=NetworkCheckType.GATEWAY_REACHABILITY,
        success=False,
        message="Not implemented"
    )
    return result


def _check_service_ports(
    ctx: VmDeploymentContext,
    config: NetworkCheckConfig,
) -> NetworkCheckItemResult:
    """
    Detect internal service port availability.

    TODO: Implement service port check logic
    - Verify configured ports are listening
    - Test port accessibility from VM
    - Check service process status
    - Validate firewall rules
    """
    result = NetworkCheckItemResult(
        check_type=NetworkCheckType.SERVICE_PORT_AVAILABILITY,
        success=False,
        message="Not implemented"
    )
    return result


def _check_external_connectivity(
    ctx: VmDeploymentContext,
    config: NetworkCheckConfig,
) -> NetworkCheckItemResult:
    """
    Test connectivity to external network resources.

    TODO: Implement external connectivity test logic
    - Ping external target hosts
    - Test DNS resolution
    - Verify HTTP/HTTPS connectivity
    - Measure external network latency
    """
    result = NetworkCheckItemResult(
        check_type=NetworkCheckType.EXTERNAL_CONNECTIVITY,
        success=False,
        message="Not implemented"
    )
    return result


def validate_vm_network(
    cvm_name: str,
    server_config: config,
    check_config: Optional[NetworkCheckConfig] = None,
) -> NetworkCheckResult:
    """
    Public interface for validating VM network connectivity.

    Provides a unified entry point for network validation that can be
    called independently after VM deployment.

    Args:
        cvm_name: VM name to validate
        server_config: Server configuration object
        check_config: Optional network check configuration

    Returns:
        NetworkCheckResult with comprehensive validation results
    """
    ctx = VmDeploymentContext(cvm_name=cvm_name, vm_spec=VmDeploySpec())
    ctx = _phase5_validate_network(ctx, server_config, check_config)
    return ctx.network_check_result or NetworkCheckResult(
        cvm_name=cvm_name,
        error_message="Network validation failed to execute"
    )


def _phase1_check_resources(
    vm_spec: VmDeploySpec,
    vm_id_list: List[str],
    vm_iface_map: Dict[str, List[VmInterface]],
    server_config: config,
) -> Tuple[Optional[List[int]], str]:
    """
    Phase 1: Resource Check

    Validate all prerequisite resources for deployment:
    - VM name uniqueness
    - NUMA node availability and capacity
    - SR-IOV VF resource sufficiency
    - Network interface resource availability (node, MAC, VLAN)

    Args:
        vm_spec: VM deployment specification
        vm_id_list: List of VM IDs to deploy
        vm_iface_map: Map of VM ID to network interface configurations
        server_config: Server configuration object

    Returns:
        Tuple of (available NUMA node IDs, error message)
        On success, error message is None
        On failure, available nodes is None
    """
    try:
        err_msg = cvm_name_check(vm_id_list)
        if err_msg:
            g_logger.error(err_msg)
            return None, err_msg
    except Exception as e:
        err_msg = f"VM name check exception: {e}"
        return None, err_msg

    available_nodes, err_msg = cvm_numa_check(vm_spec.core_num, vm_spec.memory, len(vm_id_list))
    if not available_nodes:
        g_logger.error(err_msg)
        return None, err_msg

    g_logger.info(
        "Phase 1 (Resource Check) passed: %d VMs, %d NUMA nodes available",
        len(vm_id_list), len(available_nodes)
    )

    return available_nodes, None


def _phase2_allocate_resources(
    cvm_name: str,
    vm_spec: VmDeploySpec,
    host_numa_id: int,
    iface_list: List[VmInterface],
    server_config: config,
) -> VmDeploymentContext:
    """
    Phase 2: Resource Allocation

    Allocate compute, network, and storage resources for a single VM:
    - Device allocation (PF/VF)
    - Network allocation (virbr0 MAC/IP via libvirt API)
    - Disk image creation (system + optional data disk)

    Returns:
        VmDeploymentContext with allocated resources
    """
    ctx = VmDeploymentContext(
        cvm_name=cvm_name,
        vm_spec=vm_spec,
        host_numa_id=host_numa_id,
    )

    device_dict, err_msg = cvm_device_alloc(
        cvm_name,
        vm_spec,
        server_config,
        iface_list
    )

    if err_msg:
        ctx.error_message = err_msg
        g_logger.error("Phase 2 (Resource Allocation) failed for %s: %s", cvm_name, err_msg)
        return ctx

    ctx.device_dict = device_dict

    driver = libvirtDriver()

    network_info, err_msg = driver.query_virbr0_config(VIRBR0_NETWORK_NAME)
    if err_msg or not network_info:
        ctx.error_message = f"Failed to query virbr0 network config: {err_msg}"
        g_logger.error("Phase 2 (Resource Allocation) failed for %s: %s", cvm_name, ctx.error_message)
        return ctx

    mac_ip_pair, err_msg = driver.generate_mac_ip_pair(network_info)
    if err_msg or not mac_ip_pair:
        ctx.error_message = f"Failed to generate MAC/IP pair: {err_msg}"
        g_logger.error("Phase 2 (Resource Allocation) failed for %s: %s", cvm_name, ctx.error_message)
        return ctx

    success, err_msg = driver.write_dhcp_host_entry(
        VIRBR0_NETWORK_NAME,
        mac_ip_pair.mac_address,
        mac_ip_pair.ip_address,
        cvm_name
    )
    if not success:
        ctx.error_message = f"Failed to write DHCP host entry: {err_msg}"
        g_logger.error("Phase 2 (Resource Allocation) failed for %s: %s", cvm_name, ctx.error_message)
        return ctx

    ctx.virtbr0_mac_addr = mac_ip_pair.mac_address
    ctx.virtbr0_ip = mac_ip_pair.ip_address

    g_logger.info(
        "Allocated network for %s: mac=%s, ip=%s",
        cvm_name, mac_ip_pair.mac_address, mac_ip_pair.ip_address
    )

    qcow2_dir = server_config.config.get("DEFAULT", "cvm_image_path")
    qcow2_path, data_disk_path = config_disk(
        cvm_name, qcow2_dir, [], server_config, vm_spec.disk_size
    )

    if not qcow2_path:
        ctx.error_message = f"Disk configuration failure for {cvm_name}"
        g_logger.error("Phase 2 (Resource Allocation) failed for %s: disk config", cvm_name)
        return ctx

    ctx.qcow2_path = qcow2_path
    ctx.data_disk_path = data_disk_path or ""

    g_logger.info(
        "Phase 2 (Resource Allocation) passed for %s: numa=%d, devices=%s, disk=%s, mac=%s, ip=%s",
        cvm_name, host_numa_id, device_dict, qcow2_path, ctx.virtbr0_mac_addr, ctx.virtbr0_ip
    )
    return ctx


def _phase3_configure_xml(
    ctx: VmDeploymentContext,
) -> VmDeploymentContext:
    """
    Phase 3: XML Configuration

    Generate the VM definition XML file based on allocated resources.

    Returns:
        Updated VmDeploymentContext with XML configuration
    """
    if ctx.error_message:
        return ctx

    output_xml = config_xml(ctx)
    if not output_xml:
        ctx.error_message = f"XML configuration failure for {ctx.cvm_name}"
        g_logger.error("Phase 3 (XML Configuration) failed for %s", ctx.cvm_name)
        return ctx

    ctx.xml_config = output_xml

    g_logger.info(
        "Phase 3 (XML Configuration) passed for %s", ctx.cvm_name
    )
    return ctx


def _phase4_execute_deployment(
    ctx: VmDeploymentContext,
    server_config: config,
) -> VmDeploymentContext:
    """
    Phase 4: Deployment Execution

    Start the VM using the generated XML configuration.

    Returns:
        Updated VmDeploymentContext with deployment result
    """
    if ctx.error_message:
        return ctx

    g_logger.info("config qcow2 success: %s", ctx.qcow2_path)
    if ctx.data_disk_path:
        g_logger.info("data disk configured: %s", ctx.data_disk_path)

    time.sleep(1)

    driver = libvirtDriver()
    if driver.start_vm_by_xml(ctx.xml_config):
        ctx.success = True
        g_logger.info("Phase 4 (Deployment Execution) passed: CVM %s started successfully", ctx.cvm_name)
    else:
        ctx.error_message = f"Failed to start VM {ctx.cvm_name}"
        g_logger.error("Phase 4 (Deployment Execution) failed for %s", ctx.cvm_name)

    return ctx


def _deploy_single_vm(
    cvm_name: str,
    vm_spec: VmDeploySpec,
    host_numa_id: int,
    iface_list: List[VmInterface],
    server_config: config,
    app
) -> VmDeploymentContext:
    """
    Execute the full four-phase deployment pipeline for a single VM.

    Phases:
        1. Resource Check (done at batch level, skipped here)
        2. Resource Allocation
        3. XML Configuration
        4. Deployment Execution

    Returns:
        VmDeploymentContext with final deployment state
    """
    with app.app_context():
        ctx = _phase2_allocate_resources(cvm_name, vm_spec, host_numa_id, iface_list, server_config)
        if ctx.error_message:
            return ctx

        ctx = _phase3_configure_xml(ctx)
        if ctx.error_message:
            return ctx

        try:
            ctx = _phase4_execute_deployment(ctx, server_config)
        except Exception as e:
            ctx.error_message = str(e)
            g_logger.error("Phase 4 (Deployment Execution) exception for %s: %s", cvm_name, e)
            raise DeploymentException(str(e), ctx)
        
        return ctx


def deploy_cvm(
    cvm_deploy_spec_internal: VmDeploySpecInternal,
    server_config: config,
) -> Tuple[List[str], str]:
    """
    Deploy multiple CVMs using a four-phase pipeline with concurrent execution.

    Phases:
        1. Resource Check: Validate all prerequisite resources
        2. Resource Allocation: Allocate compute, network, and storage per VM
        3. XML Configuration: Generate VM definition XML
        4. Deployment Execution: Start VMs

    Supports concurrent VM deployment via ThreadPoolExecutor.

    Args:
        cvm_deploy_spec_internal: Internal deployment specification
        server_config: Server configuration object

    Returns:
        Tuple of (successfully deployed VM names, error message)
    """
    vm_spec = cvm_deploy_spec_internal.vm_spec
    vm_id_list = cvm_deploy_spec_internal.vm_id_list
    successfully_deployed_vms = []

    g_logger.info(
        "Starting CVM deployment: %d VMs, spec: core_num=%d, memory=%d, disk_size=%d",
        len(vm_id_list), vm_spec.core_num, vm_spec.memory, vm_spec.disk_size
    )

    available_nodes, err_msg = _phase1_check_resources(
        vm_spec, vm_id_list, cvm_deploy_spec_internal.vm_iface, server_config
    )
    if available_nodes is None:
        return [], err_msg

    deployment_tasks = []
    for i, cvm_name in enumerate(vm_id_list):
        node_index = i % len(available_nodes)
        deployment_tasks.append({
            "cvm_name": cvm_name,
            "vm_spec": vm_spec,
            "host_numa_id": available_nodes[node_index],
            "iface_list": cvm_deploy_spec_internal.vm_iface.get(cvm_name, []),
        })

    max_workers = min(len(deployment_tasks), constants.MAX_CVM_NUM_PER_NODE)
    g_logger.info("Phase 2-4: Deploying %d VMs concurrently (max_workers=%d)", len(deployment_tasks), max_workers)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(
                _deploy_single_vm,
                task["cvm_name"],
                task["vm_spec"],
                task["host_numa_id"],
                task["iface_list"],
                server_config,
                current_app._get_current_object()
            ): task["cvm_name"]
            for task in deployment_tasks
        }

        for future in as_completed(future_to_task):
            cvm_name = future_to_task[future]
            try:
                ctx = future.result()
                if ctx.success:
                    successfully_deployed_vms.append(cvm_name)
                else:
                    g_logger.error(
                        "Deployment failed for %s: %s", cvm_name, ctx.error_message
                    )
                    dhcp_entries = []
                    if ctx.virtbr0_mac_addr and ctx.virtbr0_ip:
                        dhcp_entries.append(
                            DhcpEntryInfo(
                                mac_address=ctx.virtbr0_mac_addr,
                                ip_address=ctx.virtbr0_ip
                            )
                        )
                    cvm_resource_reclaim(
                        reclaim_ctx=CvmReclaimContext(
                            cvm_name=cvm_name,
                            server_config=server_config,
                            dhcp_entries=dhcp_entries
                        )
                    )
                    return successfully_deployed_vms, ctx.error_message
            except Exception as e:
                g_logger.error("Unexpected error deploying %s: %s", cvm_name, e)
                dhcp_entries = []
                
                if isinstance(e, DeploymentException):
                    ctx = e.ctx
                    if ctx.virtbr0_mac_addr and ctx.virtbr0_ip:
                        dhcp_entries.append(
                            DhcpEntryInfo(
                                mac_address=ctx.virtbr0_mac_addr,
                                ip_address=ctx.virtbr0_ip
                            )
                        )
                elif 'ctx' in locals() and ctx.virtbr0_mac_addr and ctx.virtbr0_ip:
                    dhcp_entries.append(
                        DhcpEntryInfo(
                            mac_address=ctx.virtbr0_mac_addr,
                            ip_address=ctx.virtbr0_ip
                        )
                    )
                
                cvm_resource_reclaim(
                    reclaim_ctx=CvmReclaimContext(
                        cvm_name=cvm_name,
                        server_config=server_config,
                        dhcp_entries=dhcp_entries
                    )
                )
                return successfully_deployed_vms, str(e)

    g_logger.info(
        "CVM deployment completed: %d/%d VMs deployed successfully",
        len(successfully_deployed_vms), len(vm_id_list)
    )
    return successfully_deployed_vms, None

def undeploy_cvm(vm_id: str, server_config: config) -> bool:
    libvirt = libvirtDriver()
    dhcp_entries = _find_dhcp_entries_by_hostname(vm_id)
    if libvirt.destroy_cvm_by_name(vm_id):
        g_logger.info('CVM %s destroy successfully!', vm_id)
        cvm_resource_reclaim(
            reclaim_ctx=CvmReclaimContext(
                cvm_name=vm_id,
                server_config=server_config,
                dhcp_entries=dhcp_entries
            )
        )
        return True
    else:
        g_logger.error("Failed to destroy VM %s.", vm_id)
        if dhcp_entries:
            cvm_resource_reclaim(
                reclaim_ctx=CvmReclaimContext(
                    cvm_name=vm_id,
                    server_config=server_config,
                    dhcp_entries=dhcp_entries
                )
            )
        return False

def stop_cvm(vm_id: str) -> Tuple[bool, str]:
    driver = libvirtDriver()
    return driver.destroy_vm(vm_id)

def start_cvm(vm_id: str) -> Tuple[bool, str]:
    driver = libvirtDriver()
    return driver.start_vm(vm_id)

def check_launch_security(xml_desc):
    root = ET.fromstring(xml_desc)
    launch_security = root.find(".//launchSecurity")
    if launch_security is not None and launch_security.get('type') == 'cvm':
        return True
    else:
        return False

class libvirtDriver:
    def start_vm_by_xml(self, xml: str) -> bool:
        """
        从 XML 定义并启动虚拟机

        :param xml: 虚拟机 XML 配置字符串
        :return: 成功返回 True，失败返回 False
        """
        with self._get_connection() as conn:
            try:
                domain = conn.defineXML(xml)
                domain.create()
                g_logger.info("VM defined and started from XML successfully")
            except libvirt.libvirtError as e:
                g_logger.error("Error defining/starting CVM from XML, %s", e)
                return False
        return True

    def list_running_vm(self):
        with self._get_connection() as conn:
            domains = conn.listAllDomains()
            running_vms = [domain.name() for domain in domains if domain.state()[0] == libvirt.VIR_DOMAIN_RUNNING]
            g_logger.info("running cvm: %s", running_vms)
            return running_vms

    def _get_state_string(self, state_code):
        """transfer libvirt state code to string"""
        state_dict = {
            libvirt.VIR_DOMAIN_RUNNING: "RUNNING",
            libvirt.VIR_DOMAIN_BLOCKED: "BLOCKED",
            libvirt.VIR_DOMAIN_PAUSED: "PAUSED",
            libvirt.VIR_DOMAIN_SHUTOFF: "SHUTOFF",
            libvirt.VIR_DOMAIN_CRASHED: "CRASHED",
            libvirt.VIR_DOMAIN_PMSUSPENDED: "SUSPENDED"
        }
        return state_dict.get(state_code, "UNKNOWN")

    def list_all_cvm(self) -> dict:
        with self._get_connection() as conn:
            cvm_statuses = {}
            domains = conn.listAllDomains()
            for domain in domains:
                xml_desc = domain.XMLDesc()
                if check_launch_security(xml_desc):
                    name = domain.name()
                    state, _ = domain.state()
                    cvm_statuses[name] = self._get_state_string(state)
            g_logger.info("cvm: %s", cvm_statuses)
            return cvm_statuses

    def list_all_vm(self) -> dict:
        with self._get_connection() as conn:
            cvm_statuses = {}
            domains = conn.listAllDomains()
            for domain in domains:
                name = domain.name()
                state, _ = domain.state()
                cvm_statuses[name] = self._get_state_string(state)
            return cvm_statuses

    def is_vm_running(self, vm_name: str) -> bool:
        with self._get_connection() as conn:
            domains = conn.listAllDomains()
            for domain in domains:
                if domain.name() == vm_name:
                    state, _ = domain.state()
                    if state == libvirt.VIR_DOMAIN_RUNNING:
                        return True
                    else:
                        return False
            return False

    def is_vm_exist(self, vm_name: str) -> bool:
        with self._get_connection() as conn:
            domains = conn.listAllDomains()
            for domain in domains:
                if domain.name() == vm_name:
                    return True
                else:
                    return False
            return False

    def destroy_cvm_by_name(self, vm_name) -> bool:
        """
        销毁虚拟机并移除其 XML 定义

        :param vm_name: 虚拟机名称
        :return: 成功返回 True，失败返回 False
        """
        with self._get_connection() as conn:
            try:
                domain = conn.lookupByName(vm_name)
                domain.destroy()
                g_logger.info("cvm '%s' has been destroyed", vm_name)
                domain.undefine()
                g_logger.info("cvm '%s' XML definition has been removed", vm_name)
                return True
            except libvirt.libvirtError as e:
                g_logger.error("unable to destroy/undefine cvm '%s': %s", vm_name, e)
                return False

    def undefine_cvm_by_name(self, vm_name) -> bool:
        """
        移除虚拟机 XML 定义

        :param vm_name: 虚拟机名称
        :return: 成功返回 True，失败返回 False
        """
        with self._get_connection() as conn:
            try:
                if not self.is_vm_exist(vm_name):
                    return False

                domain = conn.lookupByName(vm_name)
                domain.undefine()
                g_logger.info("cvm '%s' XML definition has been removed", vm_name)
                return True

            except libvirt.libvirtError as e:
                g_logger.error("unable to undefine cvm '%s': %s", vm_name, e)
                return False

    def start_vm(self, vm_name: str) -> Tuple[bool, str]:
        """
        启动已有持久化定义的虚拟机（停止/启动接口专用）

        :param vm_name: 虚拟机名称
        :return: (成功标志, 错误信息) 元组，成功时错误信息为空字符串
        """
        with self._get_connection() as conn:
            try:
                domain = conn.lookupByName(vm_name)
                state, _ = domain.state()
                if state == libvirt.VIR_DOMAIN_RUNNING:
                    g_logger.info("VM '%s' is already running", vm_name)
                    return True, f"VM '{vm_name}' is already running"
                domain.create()
                g_logger.info("VM '%s' started successfully", vm_name)
                return True, ""
            except libvirt.libvirtError as e:
                err_msg = f"Failed to start VM '{vm_name}': {e}"
                g_logger.error(err_msg)
                return False, err_msg

    def destroy_vm(self, vm_name: str) -> Tuple[bool, str]:
        """
        强制关闭虚拟机但保留其 XML 定义

        :param vm_name: 虚拟机名称
        :return: (成功标志, 错误信息) 元组，成功时错误信息为空字符串
        """
        with self._get_connection() as conn:
            try:
                domain = conn.lookupByName(vm_name)
                state, _ = domain.state()
                if state == libvirt.VIR_DOMAIN_SHUTOFF:
                    g_logger.info("VM '%s' is already stopped", vm_name)
                    return True, f"VM '{vm_name}' is already stopped"
                domain.destroy()
                g_logger.info("VM '%s' destroyed successfully", vm_name)
                return True, ""
            except libvirt.libvirtError as e:
                err_msg = f"Failed to destroy VM '{vm_name}': {e}"
                g_logger.error(err_msg)
                return False, err_msg

    def query_virbr0_config(self, network_name: str = VIRBR0_NETWORK_NAME) -> Tuple[Optional[Virbr0NetworkInfo], str]:
        """
        通过 libvirt API 查询 virbr0 网桥的网络配置信息

        :param network_name: libvirt 网络名称（默认: "default"）
        :return: (Virbr0NetworkInfo 或 None, 错误信息) 元组
        """
        try:
            with self._get_connection() as conn:
                network = conn.networkLookupByName(network_name)
                xml_desc = network.XMLDesc(0)

                g_logger.info("Retrieved network XML for '%s'", network_name)

                network_info = self._parse_network_xml(xml_desc, network_name)

                leases = self._get_dhcp_leases(network)
                network_info.existing_leases = leases

                for lease in leases:
                    mac = lease.get("mac", "").lower()
                    ip = lease.get("ipaddr", "")
                    if mac:
                        network_info.existing_macs.add(mac)
                    if ip:
                        network_info.existing_ips.add(ip)

                g_logger.info(
                    "Network '%s' info: subnet=%s, dhcp_range=[%s-%s], "
                    "existing_leases=%d, existing_macs=%d, existing_ips=%d",
                    network_name, network_info.subnet_cidr,
                    network_info.dhcp_start, network_info.dhcp_end,
                    len(leases), len(network_info.existing_macs),
                    len(network_info.existing_ips)
                )

                return network_info, ""

        except libvirt.libvirtError as e:
            err_msg = f"Failed to query network '{network_name}': {e}"
            g_logger.error(err_msg)
            return None, err_msg
        except Exception as e:
            err_msg = f"Unexpected error querying network config: {e}"
            g_logger.error(err_msg)
            return None, err_msg

    def _parse_network_xml(self, xml_desc: str, network_name: str) -> Virbr0NetworkInfo:
        """解析 libvirt 网络 XML 提取配置信息"""
        info = Virbr0NetworkInfo(network_name=network_name)

        try:
            root = ET.fromstring(xml_desc)

            bridge_elem = root.find(".//bridge")
            if bridge_elem is not None:
                info.bridge_name = bridge_elem.get("name", "")

            ip_elem = root.find(".//ip")
            if ip_elem is not None:
                info.ip_address = ip_elem.get("address", "")
                info.netmask = ip_elem.get("netmask", "")

                if info.ip_address and info.netmask:
                    network = ipaddress.IPv4Network(
                        f"{info.ip_address}/{info.netmask}", strict=False
                    )
                    info.subnet_cidr = str(network)
                    info.subnet_network = network

                dhcp_elem = ip_elem.find(".//dhcp")
                if dhcp_elem is not None:
                    range_elem = dhcp_elem.find(".//range")
                    if range_elem is not None:
                        info.dhcp_start = range_elem.get("start", "")
                        info.dhcp_end = range_elem.get("end", "")

            host_elems = root.findall(".//host")
            for host_elem in host_elems:
                mac = host_elem.get("mac", "").lower()
                ip = host_elem.get("ip", "")
                if mac:
                    info.existing_macs.add(mac)
                if ip:
                    info.existing_ips.add(ip)

        except ET.ParseError as e:
            g_logger.error("Failed to parse network XML: %s", e)
            raise
        except Exception as e:
            g_logger.error("Error parsing network XML: %s", e)
            raise

        return info

    def _get_dhcp_leases(self, network) -> List[Dict[str, str]]:
        """从 libvirt 网络获取当前 DHCP 租约"""
        try:
            leases = network.DHCPLeases()
            result = []
            for lease in leases:
                result.append({
                    "expirytime": lease.get("expirytime", ""),
                    "ipaddr": lease.get("ipaddr", ""),
                    "prefix": lease.get("prefix", ""),
                    "mac": lease.get("mac", "").lower(),
                    "iaid": lease.get("iaid", ""),
                    "hostname": lease.get("hostname", ""),
                })
            return result
        except libvirt.libvirtError as e:
            g_logger.warning("Failed to get DHCP leases: %s", e)
            return []
        except Exception as e:
            g_logger.warning("Unexpected error getting DHCP leases: %s", e)
            return []

    def generate_mac_address(self, existing_macs: Optional[Set[str]] = None) -> Tuple[str, str]:
        """
        生成不与现有设备 MAC 地址冲突的新 MAC 地址

        使用 libvirt 保留的 OUI 前缀 52:54:00 确保 MAC 地址在本地管理范围内。
        使用线程锁确保并发安全。

        :param existing_macs: 需要避免的现有 MAC 地址集合
        :return: (mac_address, error_message) 元组
        """
        with _virbr0_config_lock:
            return self._generate_mac_address_internal(existing_macs)

    def _generate_mac_address_internal(self, existing_macs: Optional[Set[str]] = None) -> Tuple[str, str]:
        """内部 MAC 地址生成方法，必须在持有 _virbr0_config_lock 时调用"""
        if existing_macs is None:
            existing_macs = set()

        existing_macs = {mac.lower() for mac in existing_macs}

        import random

        max_attempts = 100
        for attempt in range(max_attempts):
            octet4 = random.randint(0x00, 0xFF)
            octet5 = random.randint(0x00, 0xFF)
            octet6 = random.randint(0x00, 0xFF)

            mac = f"{MAC_OUI_PREFIX}:{octet4:02x}:{octet5:02x}:{octet6:02x}"

            if mac not in existing_macs:
                g_logger.info("Generated new MAC address: %s", mac)
                return mac, ""

        err_msg = f"Failed to generate unique MAC address after {max_attempts} attempts"
        g_logger.error(err_msg)
        return "", err_msg

    def generate_ip_address(
        self,
        network_info: Virbr0NetworkInfo,
        existing_ips: Optional[Set[str]] = None,
    ) -> Tuple[str, str]:
        """
        生成在 virbr0 子网范围内且不与当前 DHCP 分配记录冲突的 IP 地址

        使用线程锁确保并发安全。

        :param network_info: Virbr0NetworkInfo 包含子网和 DHCP 范围信息
        :param existing_ips: 需要避免的现有 IP 地址集合
        :return: (ip_address, error_message) 元组
        """
        with _virbr0_config_lock:
            return self._generate_ip_address_internal(network_info, existing_ips)

    def _generate_ip_address_internal(
        self,
        network_info: Virbr0NetworkInfo,
        existing_ips: Optional[Set[str]] = None,
    ) -> Tuple[str, str]:
        """内部 IP 地址生成方法，必须在持有 _virbr0_config_lock 时调用"""
        if existing_ips is None:
            existing_ips = set()

        if network_info.subnet_network is None:
            err_msg = "Network info does not contain valid subnet information"
            g_logger.error(err_msg)
            return "", err_msg

        dhcp_start = network_info.dhcp_start
        dhcp_end = network_info.dhcp_end

        if dhcp_start and dhcp_end:
            available_ips = self._get_dhcp_range_ips(
                network_info.subnet_network, dhcp_start, dhcp_end, existing_ips
            )
        else:
            available_ips = self._get_subnet_available_ips(
                network_info.subnet_network, existing_ips
            )

        if not available_ips:
            err_msg = "No available IP addresses in the DHCP range"
            g_logger.error(err_msg)
            return "", err_msg

        import random
        selected_ip = random.choice(list(available_ips))

        g_logger.info("Generated new IP address: %s", selected_ip)
        return str(selected_ip), ""

    def _get_dhcp_range_ips(
        self,
        network: ipaddress.IPv4Network,
        dhcp_start: str,
        dhcp_end: str,
        existing_ips: Set[str],
    ) -> Set[ipaddress.IPv4Address]:
        """获取 DHCP 范围内的可用 IP"""
        try:
            start_ip = ipaddress.IPv4Address(dhcp_start)
            end_ip = ipaddress.IPv4Address(dhcp_end)

            if start_ip not in network or end_ip not in network:
                g_logger.warning(
                    "DHCP range [%s-%s] is outside network %s",
                    dhcp_start, dhcp_end, network
                )
                return set()

            available = set()
            current = start_ip
            while current <= end_ip:
                if str(current) not in existing_ips:
                    available.add(current)
                current = current + 1

            return available

        except ValueError as e:
            g_logger.error("Invalid DHCP range [%s-%s]: %s", dhcp_start, dhcp_end, e)
            return set()

    def _get_subnet_available_ips(
        self,
        network: ipaddress.IPv4Network,
        existing_ips: Set[str],
    ) -> Set[ipaddress.IPv4Address]:
        """获取整个子网中的可用 IP"""
        available = set()

        for host in network.hosts():
            ip_str = str(host)
            if ip_str not in existing_ips:
                last_octet = int(ip_str.split(".")[-1])
                if 2 <= last_octet <= 254:
                    available.add(host)

        return available

    def generate_mac_ip_pair(
        self,
        network_info: Virbr0NetworkInfo,
        existing_macs: Optional[Set[str]] = None,
        existing_ips: Optional[Set[str]] = None,
    ) -> Tuple[Optional[MacIpPair], str]:
        """
        生成不冲突的 MAC 和 IP 地址对

        使用线程锁确保并发安全。

        :param network_info: Virbr0NetworkInfo 包含网络配置
        :param existing_macs: 需要避免的现有 MAC 地址集合
        :param existing_ips: 需要避免的现有 IP 地址集合
        :return: (MacIpPair 或 None, error_message) 元组
        """
        with _virbr0_config_lock:
            return self._generate_mac_ip_pair_internal(network_info, existing_macs, existing_ips)

    def _generate_mac_ip_pair_internal(
        self,
        network_info: Virbr0NetworkInfo,
        existing_macs: Optional[Set[str]] = None,
        existing_ips: Optional[Set[str]] = None,
    ) -> Tuple[Optional[MacIpPair], str]:
        """内部 MAC/IP 对生成方法，必须在持有 _virbr0_config_lock 时调用"""
        if existing_macs is None:
            existing_macs = set()
        if existing_ips is None:
            existing_ips = set()

        combined_macs = network_info.existing_macs | existing_macs
        combined_ips = network_info.existing_ips | existing_ips

        mac, err_msg = self._generate_mac_address_internal(combined_macs)
        if err_msg:
            return None, err_msg

        ip, err_msg = self._generate_ip_address_internal(network_info, combined_ips)
        if err_msg:
            return None, err_msg

        pair = MacIpPair(mac_address=mac, ip_address=ip)
        g_logger.info("Generated MAC-IP pair: %s -> %s", mac, ip)
        return pair, ""

    def write_dhcp_host_entry(
        self,
        network_name: str,
        mac_address: str,
        ip_address: str,
        hostname: str = "",
    ) -> Tuple[bool, str]:
        """
        将 DHCP 主机条目写入 libvirt 网络配置

        此方法更新 libvirt 网络 XML 以添加静态 DHCP 主机条目，
        这是添加 MAC/IP 绑定的推荐方式。
        使用线程锁确保并发安全。

        :param network_name: libvirt 网络名称
        :param mac_address: 要添加的 MAC 地址
        :param ip_address: 要分配的 IP 地址
        :param hostname: 条目的可选主机名
        :return: (success, error_message) 元组
        """
        if not self._validate_mac_address(mac_address):
            err_msg = f"Invalid MAC address format: {mac_address}"
            g_logger.error(err_msg)
            return False, err_msg

        if not self._validate_ip_address(ip_address):
            err_msg = f"Invalid IP address format: {ip_address}"
            g_logger.error(err_msg)
            return False, err_msg

        with _virbr0_config_lock:
            return self._write_dhcp_host_entry_internal(network_name, mac_address, ip_address, hostname)

    def _write_dhcp_host_entry_internal(
        self,
        network_name: str,
        mac_address: str,
        ip_address: str,
        hostname: str = "",
    ) -> Tuple[bool, str]:
        """内部 DHCP 主机条目写入方法，必须在持有 _virbr0_config_lock 时调用"""
        try:
            with self._get_connection() as conn:
                network = conn.networkLookupByName(network_name)

                network.update(
                    libvirt.VIR_NETWORK_UPDATE_COMMAND_ADD_LAST,
                    libvirt.VIR_NETWORK_SECTION_IP_DHCP_HOST,
                    -1,
                    f"<host mac='{mac_address}' ip='{ip_address}' name='{hostname}'/>",
                    libvirt.VIR_NETWORK_UPDATE_AFFECT_LIVE | libvirt.VIR_NETWORK_UPDATE_AFFECT_CONFIG,
                )

                g_logger.info(
                    "Added DHCP host entry: mac=%s, ip=%s, hostname=%s to network '%s'",
                    mac_address, ip_address, hostname, network_name
                )

                return True, ""

        except libvirt.libvirtError as e:
            err_msg = f"Failed to write DHCP host entry: {e}"
            g_logger.error(err_msg)
            return False, err_msg
        except Exception as e:
            err_msg = f"Unexpected error writing DHCP host entry: {e}"
            g_logger.error(err_msg)
            return False, err_msg

    def write_dhcp_config_file(
        self,
        mac_address: str,
        ip_address: str,
        hostname: str = "",
        config_dir: str = DHCP_CONFIG_DIR,
        network_name: str = VIRBR0_NETWORK_NAME,
    ) -> Tuple[bool, str]:
        """
        将 MAC/IP 对直接写入 dnsmasq 配置文件

        这是一种替代方法，直接写入 dnsmasq 主机配置文件。
        使用原子写入防止损坏。
        使用线程锁确保并发安全。

        :param mac_address: 要添加的 MAC 地址
        :param ip_address: 要分配的 IP 地址
        :param hostname: 可选主机名
        :param config_dir: dnsmasq 配置目录
        :param network_name: 用于文件命名的网络名称
        :return: (success, error_message) 元组
        """
        if not self._validate_mac_address(mac_address):
            err_msg = f"Invalid MAC address format: {mac_address}"
            g_logger.error(err_msg)
            return False, err_msg

        if not self._validate_ip_address(ip_address):
            err_msg = f"Invalid IP address format: {ip_address}"
            g_logger.error(err_msg)
            return False, err_msg

        with _virbr0_config_lock:
            return self._write_dhcp_config_file_internal(
                mac_address, ip_address, hostname, config_dir, network_name
            )

    def _write_dhcp_config_file_internal(
        self,
        mac_address: str,
        ip_address: str,
        hostname: str = "",
        config_dir: str = DHCP_CONFIG_DIR,
        network_name: str = VIRBR0_NETWORK_NAME,
    ) -> Tuple[bool, str]:
        """内部 DHCP 配置文件写入方法，必须在持有 _virbr0_config_lock 时调用"""
        config_file = os.path.join(config_dir, f"{network_name}.hosts")

        try:
            os.makedirs(config_dir, exist_ok=True)

            existing_content = ""
            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    existing_content = f.read()

            new_entry = self._format_dhcp_entry(mac_address, ip_address, hostname)

            if self._entry_exists(existing_content, mac_address, ip_address):
                g_logger.info(
                    "DHCP entry already exists: mac=%s, ip=%s", mac_address, ip_address
                )
                return True, ""

            updated_content = existing_content.rstrip("\n") + "\n" + new_entry + "\n"

            self._atomic_write(config_file, updated_content)

            g_logger.info(
                "Wrote DHCP entry to %s: mac=%s, ip=%s", config_file, mac_address, ip_address
            )

            return True, ""

        except PermissionError as e:
            err_msg = f"Permission denied writing to {config_file}: {e}"
            g_logger.error(err_msg)
            return False, err_msg
        except OSError as e:
            err_msg = f"OS error writing to {config_file}: {e}"
            g_logger.error(err_msg)
            return False, err_msg
        except Exception as e:
            err_msg = f"Unexpected error writing DHCP config: {e}"
            g_logger.error(err_msg)
            return False, err_msg

    def _format_dhcp_entry(self, mac_address: str, ip_address: str, hostname: str="") -> str:
        """格式化 dnsmasq 主机文件条目"""
        if hostname:
            return f"{ip_address} {hostname} {mac_address}"
        return f"{ip_address} {mac_address}"

    def _entry_exists(self, content: str, mac_address: str, ip_address: str) -> bool:
        """检查 MAC/IP 条目是否已存在于配置文件中"""
        mac_normalized = mac_address.lower().replace("-", ":")

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()

            if len(parts) >= 2:
                file_ip = parts[0]
                file_mac = parts[-1].lower().replace("-", ":")

                if file_mac == mac_normalized or file_ip == ip_address:
                    return True

        return False

    def _atomic_write(self, filepath: str, content: str):
        """
        原子性地写入内容到文件

        使用先写入临时文件再重命名的策略确保原子性，
        防止断电或崩溃时文件损坏。
        """
        dir_name = os.path.dirname(filepath)

        fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_dhcp_")
        try:
            with os.fdopen(fd, "w") as tmp_file:
                tmp_file.write(content)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

            shutil.move(tmp_path, filepath)

        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    def _validate_mac_address(self, mac_address: str) -> bool:
        """验证 MAC 地址格式"""
        if not mac_address:
            return False

        mac_pattern = re.compile(
            r"^([0-9A-Fa-f]{2}[:]){5}([0-9A-Fa-f]{2})$"
        )
        return bool(mac_pattern.match(mac_address))

    def _validate_ip_address(self, ip_address: str) -> bool:
        """验证 IPv4 地址格式"""
        if not ip_address:
            return False

        try:
            ipaddress.IPv4Address(ip_address)
            return True
        except (ipaddress.AddressValueError, ValueError):
            return False

    def remove_dhcp_host_entry(
        self,
        network_name: str,
        mac_address: str,
        ip_address: str,
    ) -> Tuple[bool, str]:
        """
        从 libvirt 网络配置中删除 DHCP 主机条目

        使用线程锁确保并发安全。

        :param network_name: libvirt 网络名称
        :param mac_address: 要删除的 MAC 地址
        :param ip_address: 要删除的 IP 地址
        :return: (success, error_message) 元组
        """
        with _virbr0_config_lock:
            return self._remove_dhcp_host_entry_internal(network_name, mac_address, ip_address)

    def _remove_dhcp_host_entry_internal(
        self,
        network_name: str,
        mac_address: str,
        ip_address: str,
    ) -> Tuple[bool, str]:
        """内部 DHCP 主机条目删除方法，必须在持有 _virbr0_config_lock 时调用"""
        try:
            with self._get_connection() as conn:
                network = conn.networkLookupByName(network_name)

                network.update(
                    libvirt.VIR_NETWORK_UPDATE_COMMAND_DELETE,
                    libvirt.VIR_NETWORK_SECTION_IP_DHCP_HOST,
                    -1,
                    f"<host mac='{mac_address}' ip='{ip_address}'/>",
                    libvirt.VIR_NETWORK_UPDATE_AFFECT_LIVE | libvirt.VIR_NETWORK_UPDATE_AFFECT_CONFIG,
                )

                g_logger.info(
                    "Removed DHCP host entry: mac=%s, ip=%s from network '%s'",
                    mac_address, ip_address, network_name
                )

                return True, ""

        except libvirt.libvirtError as e:
            err_msg = f"Failed to remove DHCP host entry: {e}"
            g_logger.error(err_msg)
            return False, err_msg
        except Exception as e:
            err_msg = f"Unexpected error removing DHCP host entry: {e}"
            g_logger.error(err_msg)
            return False, err_msg

    def batch_allocate_mac_ip_pairs(
        self,
        network_info: Virbr0NetworkInfo,
        count: int,
    ) -> Tuple[List[MacIpPair], str]:
        """
        批量分配多个不冲突的 MAC/IP 对

        使用线程锁确保整个批量分配的原子性。

        :param network_info: Virbr0NetworkInfo 包含网络配置
        :param count: 要生成的对数
        :return: (MacIpPair 列表, error_message) 元组
        """
        if count <= 0:
            return [], "Count must be a positive integer"

        with _virbr0_config_lock:
            return self._batch_allocate_mac_ip_pairs_internal(network_info, count)

    def _batch_allocate_mac_ip_pairs_internal(
        self,
        network_info: Virbr0NetworkInfo,
        count: int,
    ) -> Tuple[List[MacIpPair], str]:
        """内部批量分配方法，必须在持有 _virbr0_config_lock 时调用"""
        pairs = []
        used_macs = set()
        used_ips = set()

        for i in range(count):
            pair, err_msg = self._generate_mac_ip_pair_internal(
                network_info, used_macs, used_ips
            )
            if err_msg:
                return pairs, f"Failed to generate pair {i+1}: {err_msg}"

            pairs.append(pair)
            used_macs.add(pair.mac_address.lower())
            used_ips.add(pair.ip_address)

        g_logger.info("Batch allocated %d MAC/IP pairs", count)
        return pairs, ""

    def batch_write_dhcp_entries(
        self,
        network_name: str,
        pairs: List[MacIpPair],
    ) -> Tuple[bool, str]:
        """
        批量写入多个 MAC/IP 对到 DHCP 配置

        :param network_name: libvirt 网络名称
        :param pairs: 要写入的 MacIpPair 列表
        :return: (success, error_message) 元组
        """
        if not pairs:
            return True, ""

        for i, pair in enumerate(pairs):
            success, err_msg = self.write_dhcp_host_entry(
                network_name, pair.mac_address, pair.ip_address
            )
            if not success:
                return False, f"Failed to write entry {i+1} ({pair.mac_address}): {err_msg}"

        g_logger.info("Batch wrote %d DHCP entries", len(pairs))
        return True, ""

    @contextmanager
    def _get_connection(self):
        """
        Ensuring the connection is closed when done.
        """
        conn = None
        try:
            conn = libvirt.open(constants.NetworkConfig.LIBVIRT_URI)
            if conn is None:
                raise ConnectionError('Unable to connect to the libvirt')
            yield conn
        except Exception as e:
            g_logger.error("failed to connect to the libvirt: %s", e)
            raise
        finally:
            if conn:
                conn.close()