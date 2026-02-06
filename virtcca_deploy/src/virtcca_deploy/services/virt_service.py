#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from typing import List
from pathlib import Path
import os
import shutil
import xml.etree.ElementTree as ET
from contextlib import contextmanager

import libvirt

from virtcca_deploy.common.data_model import VmDeploySpecInternal
import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants

g_logger = config.g_logger
output_xml_path = "/etc/virtcca_deploy/xml/"


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

def handle_topology(root, value):
    topology_node = root.find(".//topology")
    if topology_node is not None:
        topology_node.set('cores', str(value))
    else:
        raise Exception("CVM template xml is invalid!")

def handle_vcpu(root, value):
    vcpu_node = root.find(".//vcpu")
    if vcpu_node is not None:
        vcpu_node.text = str(value)
        # The topology needs to be modified to be consistent with the CPU.
        handle_topology(root, value)
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

def config_xml(cvm_name: str, vm_deploy_spec: VmDeploySpecInternal, qcow2_file: str) -> str:
    """
    Modify the XML configuration and return the XML string.

    Args:
        cvm_name: Name of the CVM
        vm_deploy_spec: VmDeploySpecInternal configuration object
        qcow2_file: Path to the QCOW2 file
    
    Returns:
        The modified XML as a string, or "" if an error occurs
    """
    if not vm_deploy_spec or not vm_deploy_spec.is_valid():
        g_logger.error("Invalid VmDeploySpecInternal configuration")
        return ""

    template_xml = constants.CVM_TEMPLATE_XML

    try:
        tree = ET.parse(template_xml)
        root = tree.getroot()
    except ET.ParseError as e:
        g_logger.error("XML parsing error occurred", exc_info=e)
        return ""
    except FileNotFoundError:
        g_logger.error("Template file not found: %s", template_xml)
        return ""
    except Exception as e:
        g_logger.error("Error reading template file", exc_info=e)
        return ""

    vm_spec = vm_deploy_spec.vm_spec

    try:
        handle_memory(root, vm_spec.memory)
        handle_vcpu(root, vm_spec.core_num)
        handle_disk(root, qcow2_file)
        handle_vm_id(root, cvm_name)
    except Exception as e:
        g_logger.error("Error during configuration of XML", exc_info=e)
        return ""

    return ET.tostring(root, encoding="unicode", method="xml")

def config_disk(cvm_name: str, file_path: str) -> str:
    base_qcow2 = constants.BASE_QCOW2
    file_name = f"{cvm_name}.qcow2"
    new_file_path = os.path.join(file_path, file_name)

    try:
        shutil.copy2(base_qcow2, new_file_path)
        g_logger.info("Copied %s to %s", base_qcow2, new_file_path)
    except FileNotFoundError:
        g_logger.error("Base QCOW2 file %s not found.", base_qcow2)
        return ""
    except Exception as e:
        g_logger.error("Error while copying QCOW2 file: %s", exc_info=e)
        return ""

    return new_file_path

def deploy_cvm(cvm_deploy_spec: VmDeploySpecInternal, server_config: config) -> List[str]:
    vm_num = cvm_deploy_spec.vm_spec.vm_num
    base_vm_name = cvm_deploy_spec.vm_id
    successfully_deployed_vms = []

    for i in range(vm_num):
        cvm_name = f"{base_vm_name}-{i + 1}"

        qcow2 = config_disk(cvm_name, server_config.config.get("DEFAULT", "cvm_image_path"))
        if not qcow2:
            g_logger.error("Skipping VM %s due to disk configuration failure.", cvm_name)
            break

        output_xml = config_xml(cvm_name, cvm_deploy_spec, qcow2)
        if not output_xml:
            g_logger.error("Skipping VM %s due to XML configuration failure.", cvm_name)
            break

        libvirt = libvirtDriver()
        if libvirt.start_vm_by_xml(output_xml):
            successfully_deployed_vms.append(cvm_name)
            g_logger.info('CVM %s started successfully!', cvm_name)
        else:
            g_logger.error("Failed to start VM %s.", cvm_name)
            break

    return successfully_deployed_vms

def undeploy_cvm(vm_id: str) -> bool:
    libvirt = libvirtDriver()
    if libvirt.destroy_cvm_by_name(vm_id):
        g_logger.info('CVM %s destroy successfully!', vm_id)
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

    def start_vm_by_xml(self, xml: str) -> bool:
        with self._get_connection() as conn:
            try:
                conn.createXML(xml, 0)
            except libvirt.libvirtError as e:
                g_logger.error("Error starting CVM", exc_info=e)
                return False
        return True

    def list_running_vm(self):
        with self._get_connection() as conn:
            running_vms = [domain.name() for domain in domains if domain.state()[0] == libvirt.VIR_DOMAIN_RUNNING]
            running_vms = [domain.name() for domain in domains]
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