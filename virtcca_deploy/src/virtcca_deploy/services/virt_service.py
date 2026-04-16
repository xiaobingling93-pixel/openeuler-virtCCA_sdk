#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from typing import List, Tuple, Optional
import os
import shutil
import xml.etree.ElementTree as ET
from contextlib import contextmanager
import time

import libvirt
import subprocess

from virtcca_deploy.common.data_model import (
    VmDeploySpecInternal, VmDeploySpec, DeviceAllocReq, DeviceReleaseReq, SriovVfSetupResp
)
import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants
import virtcca_deploy.common.hardware as hardware
import virtcca_deploy.services.util_service as util_service
import virtcca_deploy.services.resource_allocator as resource_allocator

g_logger = config.g_logger
NET_CONFIG_PATH = "/etc/sysconfig/network-scripts"

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

def handle_pci(root, pci_list: List[str]):
    device_node = root.find(".//devices")
    if device_node is not None:
        for pci_addr in pci_list:
            hostdev_node = ET.SubElement(device_node, "hostdev", mode='subsystem', type='pci', managed='yes')
            ET.SubElement(hostdev_node, 'driver', name='vfio')
            source_node = ET.SubElement(hostdev_node, 'source')
            g_logger.info("Adding PCI device: %s", pci_addr)
            domain, bus_slot_function = pci_addr.split(":", 1)
            bus, slot_function = bus_slot_function.split(":", 1)
            slot, function = slot_function.split(".") if "." in slot_function else (slot_function, None)

            if not domain or not bus or not slot or not function:
                raise ValueError(f"Invalid PCI address: {pci_addr}. Components cannot be empty!")

            ET.SubElement(source_node, "address",
                          domain=f"0x{domain}",
                          bus=f"0x{bus}",
                          slot=f"0x{slot}",
                          function=f"0x{function}")
    else:
        raise Exception("CVM template xml is invalid, unable to find element 'devices'!")

def config_xml(cvm_name: str, vm_spec: VmDeploySpec, qcow2_file: str, host_numa_id: int, device_list: List[str]) -> str:
    """
    Modify the XML configuration and return the XML string.

    Args:
        cvm_name: Name of the CVM
        vm_deploy_spec: VmDeploySpecInternal configuration object
        qcow2_file: Path to the QCOW2 file
    
    Returns:
        The modified XML as a string, or "" if an error occurs
    """
    if not vm_spec or not vm_spec.is_valid():
        g_logger.error("Invalid VmDeploySpecInternal configuration")
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
        handle_memory(root, vm_spec.memory)
        handle_vcpu(root, vm_spec.core_num)
        handle_topology(root, host_numa_id, vm_spec.core_num, vm_spec.memory)
        handle_disk(root, qcow2_file)
        handle_vm_id(root, cvm_name)
        if device_list:
            handle_pci(root, device_list)
    except Exception as e:
        g_logger.error("Error during configuration of XML, %s", e)
        return ""

    return ET.tostring(root, encoding="unicode", method="xml")

def config_disk(cvm_name: str, file_path: str, ip_list: List[str], server_config: config,) -> str:
    base_qcow2 = constants.BASE_QCOW2
    file_name = f"{cvm_name}.qcow2"
    os.makedirs(file_path, exist_ok=True)
    new_qcow2_path = os.path.join(file_path, file_name)

    try:
        shutil.copy2(base_qcow2, new_qcow2_path)
        g_logger.info("Copied %s to %s", base_qcow2, new_qcow2_path)
    except FileNotFoundError:
        g_logger.error("Base QCOW2 file %s not found.", base_qcow2)
        return ""
    except Exception as e:
        g_logger.error("Error while copying QCOW2 file: {}".format(e))
        return ""

    return new_qcow2_path

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

def config_startup_script():
    dest_dir = f"{constants.MOUNT_PATH}/{constants.GUEST_SCRIPT_PATH}"
    src_dir = constants.CVM_COMPUTE_SOFTWARE_PATH
    os.makedirs(src_dir, exist_ok=True)
    guest_rc_local_path = f"{constants.MOUNT_PATH}/etc/rc.local"
    os.makedirs(dest_dir, exist_ok=True)
    scripts = [f for f in os.listdir(src_dir)]

    for script in scripts:
        src_path = os.path.join(src_dir, script)
        dest_path = os.path.join(dest_dir, script)

        shutil.copy2(src_path, dest_path)
        os.chmod(dest_path, 0o755)
        g_logger.info(f" {script}  {dest_dir}")

    if not os.path.exists(guest_rc_local_path):
        g_logger.info(f"{guest_rc_local_path} ")
        return

    with open(guest_rc_local_path, 'a') as rc_local:
        #  rc.local 
        for script in scripts:
            rc_local.write(f"\nsh {constants.GUEST_SCRIPT_PATH}/{script} &\n")
            g_logger.info(f" {script}  {guest_rc_local_path} ")
        os.chmod(guest_rc_local_path, 0o755)

def cvm_name_check(base_vm_name: str, vm_num: int) -> str:
    libvirt = libvirtDriver()
    vm_dict = libvirt.list_all_vm()
    for i in range(vm_num):
        cvm_name = f"{base_vm_name}-{i + 1}"
        if cvm_name in vm_dict:
            return f"CVM name '{cvm_name}' is already exist"
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

def cvm_device_check(
    cvm_name: str,
    device_allocator: resource_allocator.DeviceManagerAllocator,
    pf_num: int,
    vf_num: int,
) -> Tuple[List[str], str]:
    if pf_num + vf_num == 0:
        return [], None

    req = DeviceAllocReq(vm_id=cvm_name, pf_num=pf_num, vf_num=vf_num)
    result = device_allocator.allocate(req)

    if result.success:
        return result.device_list, None

    err_msg = (
        f"Device allocation failed for VM {cvm_name}: "
        f"need {pf_num} PF + {vf_num} VF"
    )
    g_logger.error(err_msg)
    return [], err_msg

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

def cvm_resource_reclaim(cvm_name: str, server_config: config):
    g_logger.info("Clean up the resource of %s", cvm_name)
    libvirt = libvirtDriver()
    if libvirt.is_vm_running(cvm_name):
        libvirt.destroy_cvm_by_name(cvm_name)
    file_name = f"{cvm_name}.qcow2"
    qcow2_path = os.path.join(server_config.config.get("DEFAULT", "cvm_image_path"), file_name)
    if os.path.exists(qcow2_path):
        os.remove(qcow2_path)
    server_config.device_allocator.release(DeviceReleaseReq(vm_id=cvm_name))

def _execute_deploy_cvm(
    cvm_name: str,
    cvm_spec: VmDeploySpec,
    host_numa_id: int,
    device_list: List[str],
    ip_list: List[str],
    server_config: config,
    ) -> str:
    qcow2_path = server_config.config.get("DEFAULT", "cvm_image_path")
    qcow2 = config_disk(cvm_name, qcow2_path, ip_list, server_config)
    if not qcow2:
        err_msg = f"Skipping VM {cvm_name} due to disk configuration failure."
        g_logger.error(err_msg)
        return err_msg

    output_xml = config_xml(cvm_name, cvm_spec, qcow2, host_numa_id, device_list)
    if not output_xml:
        err_msg = f"Skipping VM {cvm_name} due to XML configuration failure."
        g_logger.error(err_msg)
        return err_msg

    g_logger.info("config qcow2 success: %s", qcow2)
    time.sleep(1)
    libvirt = libvirtDriver()
    if libvirt.start_vm_by_xml(output_xml):
        g_logger.info('CVM %s started successfully!', cvm_name)
    else:
        err_msg = f"Failed to start VM {cvm_name}"
        g_logger.error(err_msg)
        return err_msg
    return None

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


def deploy_cvm(cvm_deploy_spec_internal: VmDeploySpecInternal, server_config: config) -> Tuple[List[str], str]:
    vm_spec = cvm_deploy_spec_internal.vm_spec
    successfully_deployed_vms = []
    device_list = []

    available_nodes, err_msg = cvm_numa_check(vm_spec.core_num, vm_spec.memory, vm_spec.max_vm_num)
    if not available_nodes:
        g_logger.error(err_msg)
        return None, err_msg

    if vm_spec.net_vf_num > 0:
        err_msg = _ensure_sriov_vf_resources(
            server_config.device_allocator,
            vm_spec.net_vf_num,
            vm_spec.max_vm_num,
        )
        if err_msg:
            g_logger.error(err_msg)
            return None, err_msg

    for i, cvm_name in enumerate(cvm_deploy_spec_internal.vm_id_list):
        device_list = []
        device_list, err_msg = cvm_device_check(cvm_name,
                                                server_config.device_allocator,
                                                vm_spec.net_pf_num,
                                                vm_spec.net_vf_num)
        if err_msg:
            g_logger.error(err_msg)
            cvm_resource_reclaim(cvm_name, server_config)
            return successfully_deployed_vms, err_msg

        node_index = i % len(available_nodes)
        err_msg = _execute_deploy_cvm(cvm_name,
                                      vm_spec, available_nodes[node_index],
                                      device_list,
                                      cvm_deploy_spec_internal.vm_ip_dict.get(cvm_name, []),
                                      server_config)
        if err_msg:
            cvm_resource_reclaim(cvm_name, server_config)
            return successfully_deployed_vms, err_msg

        successfully_deployed_vms.append(cvm_name)

    return successfully_deployed_vms, None

def undeploy_cvm(vm_id: str, server_config: config) -> bool:
    libvirt = libvirtDriver()
    if libvirt.destroy_cvm_by_name(vm_id):
        g_logger.info('CVM %s destroy successfully!', vm_id)
        cvm_resource_reclaim(vm_id, server_config)
        return True
    else:
        g_logger.error("Failed to destroy VM %s.", vm_id)
        return False

def check_launch_security(xml_desc):
    root = ET.fromstring(xml_desc)
    launch_security = root.find(".//launchSecurity")
    if launch_security is not None and launch_security.get('type') == 'cvm':
        return True
    else:
        return False

class libvirtDriver:
    def start_vm_by_xml(self, xml: str) -> bool:
        with self._get_connection() as conn:
            try:
                conn.createXML(xml, 0)
            except libvirt.libvirtError as e:
                g_logger.error("Error starting CVM, %s", e)
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

    def destroy_cvm_by_name(self, vm_name) -> bool:
        with self._get_connection() as conn:
            try:
                domain = conn.lookupByName(vm_name)
                domain.destroy()
                g_logger.info("cvm '%s' has been destroy", vm_name)
                return True
            except libvirt.libvirtError as e:
                g_logger.error("unable to destroy cvm '%s': %s", vm_name, e)
                return False

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