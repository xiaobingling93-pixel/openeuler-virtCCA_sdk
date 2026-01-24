#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from typing import List
from pathlib import Path
import xml.etree.ElementTree as ET
from contextlib import contextmanager

import libvirt

from virtcca_deploy.common.data_model import VmDeploySpecInternal
import virtcca_deploy.common.config as config

g_logger = config.g_logger
output_xml_path = "/etc/virtcca_deploy/xml/"


def handle_vm_id(root, value):
    name_node = root.find(".//name")
    if name_node is not None:
        name_node.text = str(value)


def handle_memory(root, value):
    """
    XML <memory> 
    """
    memory_node = root.find(".//memory")
    if memory_node is not None:
        # 
        memory_node.text = str(value)
        memory_node.set('unit', 'MiB')  # 


def handle_topology(root, value):
    topology_node = root.find(".//topology")
    if topology_node is not None:
        topology_node.set('cores', str(value))


def handle_vcpu(root, value):
    vcpu_node = root.find(".//vcpu")
    if vcpu_node is not None:
        vcpu_node.text = str(value)

    # The topology needs to be modified to be consistent with the CPU.
    handle_topology(root, value)


def config_xml(template_xml: str, vm_deploy_spec: VmDeploySpecInternal) -> List[str]:
    """
    Modify the XML file based on the VmDeploySpecInternal configuration and save to specified path.
    
    Args:
        template_xml: Template XML file path
        vm_deploy_spec: VmDeploySpecInternal configuration object
        output_xml_path: Output directory path for XML files
    
    Returns:
        List of generated XML file paths
    """
    if not vm_deploy_spec or not vm_deploy_spec.is_valid():
        g_logger.error("Invalid VmDeploySpecInternal configuration")
        return []

    try:
        tree = ET.parse(template_xml)
        root = tree.getroot()
    except ET.ParseError as e:
        g_logger.error(f"XML parsing error: {e}")
        return []
    except FileNotFoundError:
        g_logger.error(f"Template file not found: {template_xml}")
        return []
    except Exception as e:
        g_logger.error(f"Error reading template file: {e}")
        return []

    vm_spec = vm_deploy_spec.vm_spec
    if hasattr(vm_spec, 'memory'):
        handle_memory(root, vm_spec.memory)

    if hasattr(vm_spec, 'core_num'):
        handle_vcpu(root, vm_spec.core_num)

    output_dir = Path(output_xml_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_vm_name = vm_deploy_spec.vm_id
    vm_num = vm_spec.vm_num

    generated_files = []
    for i in range(vm_num):
        vm_name = f"{base_vm_name}-{i + 1}"
        vm_file = output_dir / f"{vm_name}.xml"

        # Create a copy of the tree for each VM to avoid modifying the original
        vm_tree = ET.ElementTree(ET.fromstring(ET.tostring(root)))
        vm_root = vm_tree.getroot()
        
        # Set unique VM name for each file
        handle_vm_id(vm_root, vm_name)

        try:
            vm_tree.write(vm_file, encoding="UTF-8", xml_declaration=True)
            generated_files.append(str(vm_file))
        except Exception as e:
            g_logger.error(f"Error saving file {vm_file}: {e}")

    return generated_files


def check_launch_security(xml_desc):
    root = ET.fromstring(xml_desc)
    launch_security = root.find(".//launchSecurity")
    if launch_security is not None and launch_security.get('type') == 'cvm':
        return True
    else:
        return False


class libvirtDriver:
    @staticmethod
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

    def start_vm_by_xml(self, xml):
        with self._get_connection() as conn:
            try:
                conn.createXML(xml, 0)
                g_logger.info('cvm start success!')
            except libvirt.libvirtError as e:
                g_logger.error("cvm start error: %s", e)

    def list_running_vm(self):
        with self._get_connection() as conn:
            running_vms = [domain.name() for domain in domains if domain.state()[0] == libvirt.VIR_DOMAIN_RUNNING]
            running_vms = [domain.name() for domain in domains]
            g_logger.info("running cvm: %s", running_vms)
            return running_vms

    def list_all_cvm(self):
        with self._get_connection() as conn:
            cvm_statuses = []
            domains = conn.listAllDomains()
            for domain in domains:
                xml_desc = domain.XMLDesc()
                if check_launch_security(xml_desc):
                    name = domain.name()
                    state, reason = domain.state()
                    state_str = self._get_state_string(state)
                    cvm_statuses.append((name, state_str))

            g_logger.info("cvm: %s", cvm_statuses)
            return cvm_statuses

    def destroy_cvm_by_name(self, vm_name):
        with self._get_connection() as conn:
            try:
                domain = conn.lookupByName(vm_name)
                if check_launch_security(xml_desc):
                    domain.destroy()
                    g_logger.info("cvm '%s' has been destroy", vm_name)
                else:
                    g_logger.warning("vm '%s' is not a confidential vm", vm_name)
            except libvirt.libvirtError as e:
                g_logger.error("unable to destroy cvm '%s': %s", vm_name, e)

    @contextmanager
    def _get_connection(self):
        """
        Ensuring the connection is closed when done.
        """
        try:
            conn = libvirt.open('qemu:///system')
            if conn is None:
                raise ConnectionError('Unable to connect to the libvirt')
            yield conn
        except Exception as e:
            g_logger.error("failed to connect to the libvirt: %s", e)
            raise
        finally:
            if conn:
                conn.close()