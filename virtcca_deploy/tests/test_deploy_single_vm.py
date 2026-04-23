#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
Comprehensive test suite for _deploy_single_vm and its phase functions.

Tests cover:
- Normal deployment flow (all phases succeed)
- Phase 2 resource allocation failures
- Phase 3 XML configuration failures
- Phase 4 deployment execution failures
- Edge cases and boundary conditions
- Error handling and rollback scenarios
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(PROJECT_ROOT, 'src')
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

import pytest
from unittest.mock import patch, MagicMock, call
from virtcca_deploy.services.virt_service import (
    _deploy_single_vm,
    _phase2_allocate_resources,
    _phase3_configure_xml,
    _phase4_execute_deployment,
    VmDeploymentContext,
    cvm_device_alloc,
    config_disk,
    config_xml,
)
from virtcca_deploy.common.data_model import VmDeploySpec, VmInterface, DeviceAllocResp
import virtcca_deploy.common.config as config


class MockServerConfig:
    """Mock server configuration for testing"""
    def __init__(self):
        class MockConfigParser:
            def get(self, section, option):
                if section == 'DEFAULT' and option == 'cvm_image_path':
                    return '/tmp/test_qcow2'
                raise KeyError(f"Option {option} not found in section {section}")
        
        self.config = MockConfigParser()
        self.device_allocator = MagicMock()


@pytest.fixture
def mock_server_config():
    return MockServerConfig()


@pytest.fixture
def basic_vm_spec():
    return VmDeploySpec(
        max_vm_num=1,
        memory=4096,
        core_num=2,
        vlan_id=100,
        net_pf_num=0,
        net_vf_num=0,
        disk_size=0
    )


@pytest.fixture
def basic_iface_list():
    return [
        VmInterface(
            node_name="compute01",
            mac_address="00:11:22:33:44:55",
            vlan_id=100,
            ip_address="192.168.1.10",
            subnet_mask="255.255.255.0",
            gateway="192.168.1.1"
        )
    ]


class TestPhase2AllocateResources:
    """Tests for Phase 2: Resource Allocation"""

    def test_phase2_success_no_devices_no_data_disk(self, mock_server_config, basic_vm_spec):
        """Test successful resource allocation without devices or data disk"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk:
            mock_config_disk.return_value = ('/tmp/test_qcow2/vm1.qcow2', None)

            ctx = _phase2_allocate_resources(
                cvm_name="compute01-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.error_message == ""
            assert ctx.cvm_name == "compute01-1"
            assert ctx.host_numa_id == 0
            assert ctx.qcow2_path == '/tmp/test_qcow2/vm1.qcow2'
            assert ctx.data_disk_path == ""
            assert ctx.device_dict == {}

    def test_phase2_success_with_data_disk(self, mock_server_config, basic_vm_spec):
        """Test successful resource allocation with data disk"""
        basic_vm_spec.disk_size = 50

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk:
            mock_config_disk.return_value = (
                '/tmp/test_qcow2/vm1.qcow2',
                '/tmp/test_qcow2/vm1_data.qcow2'
            )

            ctx = _phase2_allocate_resources(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=1,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.error_message == ""
            assert ctx.qcow2_path == '/tmp/test_qcow2/vm1.qcow2'
            assert ctx.data_disk_path == '/tmp/test_qcow2/vm1_data.qcow2'

    def test_phase2_success_with_devices(self, mock_server_config, basic_vm_spec):
        """Test successful resource allocation with network devices"""
        basic_vm_spec.net_pf_num = 1
        basic_vm_spec.net_vf_num = 2

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={
                "00:11:22:33:44:59": "0000:01:00.0",
                "00:11:22:33:44:5a": "0000:01:00.1"
            }
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk:
            mock_config_disk.return_value = ('/tmp/test_qcow2/vm1.qcow2', None)

            ctx = _phase2_allocate_resources(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.error_message == ""
            assert ctx.device_dict == {
                "00:11:22:33:44:59": "0000:01:00.0",
                "00:11:22:33:44:5a": "0000:01:00.1"
            }

    def test_phase2_device_allocation_failure(self, mock_server_config, basic_vm_spec):
        """Test Phase 2 failure when device allocation fails"""
        basic_vm_spec.net_pf_num = 1

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=False,
            device_dict={},
        )

        ctx = _phase2_allocate_resources(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            iface_list=[],
            server_config=mock_server_config
        )

        assert ctx.error_message != ""
        assert "Device allocation failed" in ctx.error_message
        assert ctx.qcow2_path == ""

    def test_phase2_disk_config_failure(self, mock_server_config, basic_vm_spec):
        """Test Phase 2 failure when disk configuration fails"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk:
            mock_config_disk.return_value = ('', None)

            ctx = _phase2_allocate_resources(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.error_message != ""
            assert "Disk configuration failure" in ctx.error_message

    def test_phase2_context_initialization(self, mock_server_config, basic_vm_spec):
        """Test that VmDeploymentContext is properly initialized in Phase 2"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk:
            mock_config_disk.return_value = ('/tmp/test.qcow2', '/tmp/test_data.qcow2')

            ctx = _phase2_allocate_resources(
                cvm_name="test-vm",
                vm_spec=basic_vm_spec,
                host_numa_id=2,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.cvm_name == "test-vm"
            assert ctx.vm_spec == basic_vm_spec
            assert ctx.host_numa_id == 2
            assert ctx.success == False
            assert ctx.xml_config == ""
            assert ctx.ip_list == []


class TestPhase3ConfigureXml:
    """Tests for Phase 3: XML Configuration"""

    def test_phase3_success(self, basic_vm_spec):
        """Test successful XML configuration"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            qcow2_path="/tmp/test.qcow2",
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"

            result = _phase3_configure_xml(ctx)

            assert result.error_message == ""
            assert result.xml_config == "<domain><name>vm-1</name></domain>"
            mock_config_xml.assert_called_once_with(
                "vm-1",
                basic_vm_spec,
                "/tmp/test.qcow2",
                0,
                {},
                None
            )

    def test_phase3_success_with_data_disk(self, basic_vm_spec):
        """Test XML configuration with data disk path"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            qcow2_path="/tmp/test.qcow2",
            data_disk_path="/tmp/test_data.qcow2",
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"

            result = _phase3_configure_xml(ctx)

            assert result.error_message == ""
            mock_config_xml.assert_called_once_with(
                "vm-1",
                basic_vm_spec,
                "/tmp/test.qcow2",
                0,
                {},
                "/tmp/test_data.qcow2"
            )

    def test_phase3_config_xml_returns_empty(self, basic_vm_spec):
        """Test Phase 3 failure when config_xml returns empty string"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            qcow2_path="/tmp/test.qcow2",
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:
            mock_config_xml.return_value = ""

            result = _phase3_configure_xml(ctx)

            assert result.error_message != ""
            assert "XML configuration failure" in result.error_message
            assert result.xml_config == ""

    def test_phase3_skipped_if_previous_error(self, basic_vm_spec):
        """Test Phase 3 is skipped if there's an error from previous phase"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            error_message="Previous phase error"
        )

        with patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:
            result = _phase3_configure_xml(ctx)

            assert result.error_message == "Previous phase error"
            mock_config_xml.assert_not_called()

    def test_phase3_with_devices(self, basic_vm_spec):
        """Test XML configuration with PCI devices"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            qcow2_path="/tmp/test.qcow2",
            device_dict={
                "00:11:22:33:44:59": "0000:01:00.0",
                "00:11:22:33:44:5a": "0000:01:00.1"
            }
        )

        with patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"

            result = _phase3_configure_xml(ctx)

            assert result.error_message == ""
            mock_config_xml.assert_called_once_with(
                "vm-1",
                basic_vm_spec,
                "/tmp/test.qcow2",
                0,
                {
                    "00:11:22:33:44:59": "0000:01:00.0",
                    "00:11:22:33:44:5a": "0000:01:00.1"
                },
                None
            )


class TestPhase4ExecuteDeployment:
    """Tests for Phase 4: Deployment Execution"""

    def test_phase4_success(self, basic_vm_spec):
        """Test successful VM deployment"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            qcow2_path="/tmp/test.qcow2",
            xml_config="<domain><name>vm-1</name></domain>"
        )

        mock_server_config = MockServerConfig()

        with patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True
            mock_driver_class.return_value = mock_driver

            result = _phase4_execute_deployment(ctx, mock_server_config)

            assert result.success == True
            assert result.error_message == ""
            mock_driver.start_vm_by_xml.assert_called_once_with(
                "<domain><name>vm-1</name></domain>"
            )

    def test_phase4_vm_start_failure(self, basic_vm_spec):
        """Test Phase 4 failure when VM start fails"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            qcow2_path="/tmp/test.qcow2",
            xml_config="<domain><name>vm-1</name></domain>"
        )

        mock_server_config = MockServerConfig()

        with patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = False
            mock_driver_class.return_value = mock_driver

            result = _phase4_execute_deployment(ctx, mock_server_config)

            assert result.success == False
            assert result.error_message != ""
            assert "Failed to start VM" in result.error_message

    def test_phase4_skipped_if_previous_error(self, basic_vm_spec):
        """Test Phase 4 is skipped if there's an error from previous phase"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            error_message="XML configuration failure"
        )

        mock_server_config = MockServerConfig()

        with patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:
            result = _phase4_execute_deployment(ctx, mock_server_config)

            assert result.error_message == "XML configuration failure"
            mock_driver_class.assert_not_called()

    def test_phase4_with_data_disk_logging(self, basic_vm_spec):
        """Test Phase 4 logs data disk path when present"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            qcow2_path="/tmp/test.qcow2",
            data_disk_path="/tmp/test_data.qcow2",
            xml_config="<domain><name>vm-1</name></domain>"
        )

        mock_server_config = MockServerConfig()

        with patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True
            mock_driver_class.return_value = mock_driver

            with patch('virtcca_deploy.services.virt_service.g_logger') as mock_logger:
                result = _phase4_execute_deployment(ctx, mock_server_config)

                assert result.success == True
                assert mock_logger.info.call_count >= 2

    def test_phase4_libvirt_driver_exception(self, basic_vm_spec):
        """Test Phase 4 handles libvirt driver exceptions"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            qcow2_path="/tmp/test.qcow2",
            xml_config="<domain><name>vm-1</name></domain>"
        )

        mock_server_config = MockServerConfig()

        with patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:
            mock_driver_class.side_effect = Exception("libvirt connection failed")

            with pytest.raises(Exception):
                _phase4_execute_deployment(ctx, mock_server_config)


class TestDeploySingleVm:
    """Tests for the full _deploy_single_vm pipeline"""

    def test_deploy_single_vm_full_success(self, mock_server_config, basic_vm_spec):
        """Test complete successful deployment through all phases"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True
            mock_driver_class.return_value = mock_driver

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.success == True
            assert ctx.error_message == ""
            assert ctx.qcow2_path == '/tmp/test.qcow2'
            assert ctx.xml_config == "<domain><name>vm-1</name></domain>"

    def test_deploy_single_vm_phase2_failure(self, mock_server_config, basic_vm_spec):
        """Test deployment stops at Phase 2 failure"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=False,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:
            basic_vm_spec.net_pf_num = 1
            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.success == False
            assert ctx.success == False
            assert ctx.error_message != ""
            mock_config_xml.assert_not_called()
            mock_driver_class.assert_not_called()

    def test_deploy_single_vm_phase3_failure(self, mock_server_config, basic_vm_spec):
        """Test deployment stops at Phase 3 failure"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = ""

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.success == False
            assert ctx.error_message != ""
            assert "XML configuration failure" in ctx.error_message
            mock_driver_class.assert_not_called()

    def test_deploy_single_vm_phase4_failure(self, mock_server_config, basic_vm_spec):
        """Test deployment completes with Phase 4 failure"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = False
            mock_driver_class.return_value = mock_driver

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.success == False
            assert ctx.error_message != ""
            assert "Failed to start VM" in ctx.error_message
            assert ctx.qcow2_path == '/tmp/test.qcow2'
            assert ctx.xml_config == "<domain><name>vm-1</name></domain>"

    def test_deploy_single_vm_with_interfaces(self, mock_server_config, basic_vm_spec, basic_iface_list):
        """Test deployment with network interfaces"""
        basic_vm_spec.net_pf_num = 1
        basic_vm_spec.net_vf_num = 1

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={
                "00:11:22:33:44:59": "0000:01:00.0"
            }
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True
            mock_driver_class.return_value = mock_driver

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=basic_iface_list,
                server_config=mock_server_config
            )

            assert ctx.success == True
            assert ctx.device_dict == {"00:11:22:33:44:59": "0000:01:00.0"}

    def test_deploy_single_vm_with_data_disk(self, mock_server_config, basic_vm_spec):
        """Test deployment with data disk"""
        basic_vm_spec.disk_size = 100

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = (
                '/tmp/test.qcow2',
                '/tmp/test_data.qcow2'
            )
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True
            mock_driver_class.return_value = mock_driver

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.success == True
            assert ctx.data_disk_path == '/tmp/test_data.qcow2'

    def test_deploy_single_vm_multiple_numa_nodes(self, mock_server_config, basic_vm_spec):
        """Test deployment on different NUMA nodes"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        for numa_id in [0, 1, 2, 3]:
            with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
                 patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
                 patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

                mock_config_disk.return_value = (f'/tmp/test_numa{numa_id}.qcow2', None)
                mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
                
                mock_driver = MagicMock()
                mock_driver.start_vm_by_xml.return_value = True
                mock_driver_class.return_value = mock_driver

                ctx = _deploy_single_vm(
                    cvm_name=f"vm-numa{numa_id}",
                    vm_spec=basic_vm_spec,
                    host_numa_id=numa_id,
                    iface_list=[],
                    server_config=mock_server_config
                )

                assert ctx.success == True
                assert ctx.host_numa_id == numa_id


class TestEdgeCasesAndBoundaryConditions:
    """Tests for edge cases and boundary conditions"""

    def test_deploy_with_zero_disk_size(self, mock_server_config, basic_vm_spec):
        """Test deployment with disk_size=0 (no data disk)"""
        basic_vm_spec.disk_size = 0

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True
            mock_driver_class.return_value = mock_driver

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.success == True
            assert ctx.data_disk_path == ""

    def test_deploy_with_large_memory(self, mock_server_config):
        """Test deployment with large memory allocation"""
        large_vm_spec = VmDeploySpec(
            max_vm_num=1,
            memory=65536,
            core_num=16,
            vlan_id=100,
            disk_size=0
        )

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True
            mock_driver_class.return_value = mock_driver

            ctx = _deploy_single_vm(
                cvm_name="vm-large",
                vm_spec=large_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.success == True
            assert ctx.vm_spec.memory == 65536
            assert ctx.vm_spec.core_num == 16

    def test_deploy_with_empty_device_dict(self, mock_server_config, basic_vm_spec):
        """Test deployment with no network devices required"""
        basic_vm_spec.net_pf_num = 0
        basic_vm_spec.net_vf_num = 0

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True
            mock_driver_class.return_value = mock_driver

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.success == True
            assert ctx.device_dict == {}

    def test_deploy_with_special_characters_in_name(self, mock_server_config, basic_vm_spec):
        """Test deployment with VM name containing special characters"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-test_01.special</name></domain>"
            
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True
            mock_driver_class.return_value = mock_driver

            ctx = _deploy_single_vm(
                cvm_name="vm-test_01.special",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.success == True
            assert ctx.cvm_name == "vm-test_01.special"

    def test_deploy_with_maximum_vf_count(self, mock_server_config, basic_vm_spec):
        """Test deployment with maximum VF count"""
        basic_vm_spec.net_vf_num = 16

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={f"00:11:22:33:44:{i:02x}": f"0000:01:00.{i}" for i in range(16)}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml, \
             patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True
            mock_driver_class.return_value = mock_driver

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.success == True
            assert len(ctx.device_dict) == 16


class TestErrorHandlingAndRecovery:
    """Tests for error handling and recovery mechanisms"""

    def test_phase2_exception_handling(self, mock_server_config, basic_vm_spec):
        mock_server_config.device_allocator.allocate.side_effect = Exception("Unexpected error")
        basic_vm_spec.net_pf_num = 1
        device_dict, err_msg = cvm_device_alloc(
            "vm-1",
            basic_vm_spec,
            mock_server_config,
            []
        )

        assert device_dict == {}
        assert "Unexpected error" in err_msg

    def test_phase3_exception_handling(self, basic_vm_spec):
        """Test Phase 3 handles exceptions gracefully"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            qcow2_path="/tmp/test.qcow2",
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:
            mock_config_xml.side_effect = Exception("XML parsing error")

            with pytest.raises(Exception):
                _phase3_configure_xml(ctx)

    def test_context_preserves_state_on_failure(self, mock_server_config, basic_vm_spec):
        """Test that context preserves state even when deployment fails"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={
                "00:11:22:33:44:59": "0000:01:00.0"
            }
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

            mock_config_disk.return_value = ('/tmp/test.qcow2', '/tmp/test_data.qcow2')
            mock_config_xml.return_value = ""
            basic_vm_spec.net_pf_num = 1
            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.error_message != ""
            assert ctx.cvm_name == "vm-1"
            assert ctx.host_numa_id == 0
            assert ctx.qcow2_path == '/tmp/test.qcow2'
            assert ctx.data_disk_path == '/tmp/test_data.qcow2'
            assert ctx.device_dict == {"00:11:22:33:44:59": "0000:01:00.0"}

    def test_multiple_consecutive_failures(self, mock_server_config, basic_vm_spec):
        """Test handling of multiple consecutive deployment failures"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=False,
            device_dict={}
        )
        with patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_driver = MagicMock()
            mock_driver.start_vm_by_xml.return_value = True

            mock_driver_class.return_value = mock_driver
            for i in range(3):
                basic_vm_spec.net_pf_num = 1
                ctx = _deploy_single_vm(
                    cvm_name=f"vm-{i}",
                    vm_spec=basic_vm_spec,
                    host_numa_id=i,
                    iface_list=[],
                    server_config=mock_server_config
                )

                assert ctx.success == False
                assert ctx.error_message != ""


class TestVmDeploymentContext:
    """Tests for VmDeploymentContext data class"""

    def test_context_default_values(self):
        """Test VmDeploymentContext default values"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=VmDeploySpec()
        )

        assert ctx.host_numa_id == -1
        assert ctx.device_dict == {}
        assert ctx.ip_list == []
        assert ctx.qcow2_path == ""
        assert ctx.data_disk_path == ""
        assert ctx.xml_config == ""
        assert ctx.error_message == ""
        assert ctx.success == False
        assert ctx.network_check_result is None

    def test_context_with_all_fields(self, basic_vm_spec):
        """Test VmDeploymentContext with all fields populated"""
        ctx = VmDeploymentContext(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            device_dict={
                "00:11:22:33:44:59": "0000:01:00.0"
            },
            ip_list=["192.168.1.10"],
            qcow2_path="/tmp/test.qcow2",
            data_disk_path="/tmp/test_data.qcow2",
            xml_config="<domain></domain>",
            success=True
        )

        assert ctx.cvm_name == "vm-1"
        assert ctx.vm_spec == basic_vm_spec
        assert ctx.host_numa_id == 0
        assert ctx.device_dict=={"00:11:22:33:44:59": "0000:01:00.0"}
        assert ctx.ip_list == ["192.168.1.10"]
        assert ctx.qcow2_path == "/tmp/test.qcow2"
        assert ctx.data_disk_path == "/tmp/test_data.qcow2"
        assert ctx.xml_config == "<domain></domain>"
        assert ctx.success == True
        assert ctx.error_message == ""
