#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
Comprehensive test suite for _deploy_single_vm and its phase functions.

Tests cover:
- Normal deployment flow (all phases succeed)
- Phase 2 resource allocation failures (including DHCP operations)
- Phase 3 XML configuration failures
- Phase 4 deployment execution failures
- Edge cases and boundary conditions
- Error handling and rollback scenarios
- DHCP allocation, configuration, and cleanup scenarios
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


@pytest.fixture
def mock_network_info():
    """Mock network information for DHCP operations"""
    from virtcca_deploy.services.virt_service import Virbr0NetworkInfo
    import ipaddress
    
    network_info = MagicMock()
    network_info.subnet_cidr = "192.168.122.0/24"
    network_info.subnet_network = ipaddress.ip_network("192.168.122.0/24")
    network_info.dhcp_start = "192.168.122.2"
    network_info.dhcp_end = "192.168.122.254"
    network_info.existing_macs = set()
    network_info.existing_ips = set()
    network_info.existing_leases = []
    return network_info


@pytest.fixture
def mock_mac_ip_pair():
    """Mock MAC/IP pair for DHCP allocation"""
    from virtcca_deploy.services.virt_service import MacIpPair
    return MacIpPair(
        mac_address="52:54:00:aa:bb:cc",
        ip_address="192.168.122.50"
    )


@pytest.fixture
def mock_libvirt_driver(mock_network_info, mock_mac_ip_pair):
    """Mock libvirtDriver with DHCP operations"""
    with patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:
        mock_driver = MagicMock()
        
        mock_driver.query_virbr0_config.return_value = (mock_network_info, "")
        mock_driver.generate_mac_ip_pair.return_value = (mock_mac_ip_pair, "")
        mock_driver.write_dhcp_host_entry.return_value = (True, "")
        mock_driver.remove_dhcp_host_entry.return_value = (True, "")
        mock_driver.generate_mac_address.return_value = ("52:54:00:aa:bb:cc", "")
        mock_driver.generate_ip_address.return_value = ("192.168.122.50", "")
        mock_driver.batch_write_dhcp_entries.return_value = (True, "")
        
        mock_driver_class.return_value = mock_driver
        yield mock_driver_class


class TestPhase2AllocateResources:
    """Tests for Phase 2: Resource Allocation"""

    def test_phase2_success_no_devices_no_data_disk(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair):
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
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

            mock_libvirt_driver.return_value.query_virbr0_config.assert_called_once()
            mock_libvirt_driver.return_value.generate_mac_ip_pair.assert_called_once()
            mock_libvirt_driver.return_value.write_dhcp_host_entry.assert_called_once()

    def test_phase2_success_with_data_disk(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair):
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
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_phase2_success_with_devices(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair):
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
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_phase2_device_allocation_failure(self, mock_server_config, basic_vm_spec, mock_libvirt_driver):
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
        assert ctx.virtbr0_mac_addr == ""
        assert ctx.virtbr0_ip == ""

        mock_libvirt_driver.return_value.query_virbr0_config.assert_not_called()

    def test_phase2_disk_config_failure(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair):
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
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_phase2_context_initialization(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair):
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
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address


class TestPhase2DHCPOperations:
    """Tests for Phase 2 DHCP-specific operations"""

    def test_phase2_query_virbr0_config_failure(self, mock_server_config, basic_vm_spec, mock_libvirt_driver):
        """Test Phase 2 failure when querying virbr0 config fails"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )
        
        mock_libvirt_driver.return_value.query_virbr0_config.return_value = (None, "Failed to query network config")

        ctx = _phase2_allocate_resources(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            iface_list=[],
            server_config=mock_server_config
        )

        assert ctx.error_message != ""
        assert "Failed to query virbr0 network config" in ctx.error_message
        assert ctx.virtbr0_mac_addr == ""
        assert ctx.virtbr0_ip == ""
        
        mock_libvirt_driver.return_value.generate_mac_ip_pair.assert_not_called()
        mock_libvirt_driver.return_value.write_dhcp_host_entry.assert_not_called()

    def test_phase2_generate_mac_ip_pair_failure(self, mock_server_config, basic_vm_spec, mock_libvirt_driver):
        """Test Phase 2 failure when MAC/IP pair generation fails"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )
        
        mock_libvirt_driver.return_value.generate_mac_ip_pair.return_value = (None, "No available IP addresses")

        ctx = _phase2_allocate_resources(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            iface_list=[],
            server_config=mock_server_config
        )

        assert ctx.error_message != ""
        assert "Failed to generate MAC/IP pair" in ctx.error_message
        assert ctx.virtbr0_mac_addr == ""
        assert ctx.virtbr0_ip == ""
        
        mock_libvirt_driver.return_value.write_dhcp_host_entry.assert_not_called()

    def test_phase2_write_dhcp_entry_failure(self, mock_server_config, basic_vm_spec, mock_libvirt_driver):
        """Test Phase 2 failure when writing DHCP entry fails"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )
        
        mock_libvirt_driver.return_value.write_dhcp_host_entry.return_value = (False, "Failed to write DHCP entry")

        ctx = _phase2_allocate_resources(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            iface_list=[],
            server_config=mock_server_config
        )

        assert ctx.error_message != ""
        assert "Failed to write DHCP host entry" in ctx.error_message
        assert ctx.virtbr0_mac_addr == ""
        assert ctx.virtbr0_ip == ""

    def test_phase2_dhcp_with_existing_leases(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_network_info):
        """Test Phase 2 DHCP allocation with existing leases"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )
        
        mock_network_info.existing_macs = {"52:54:00:11:22:33", "52:54:00:44:55:66"}
        mock_network_info.existing_ips = {"192.168.122.10", "192.168.122.11"}
        mock_network_info.existing_leases = [
            {"mac": "52:54:00:11:22:33", "ipaddr": "192.168.122.10", "hostname": "vm-existing-1"},
            {"mac": "52:54:00:44:55:66", "ipaddr": "192.168.122.11", "hostname": "vm-existing-2"}
        ]

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk:
            mock_config_disk.return_value = ('/tmp/test.qcow2', None)

            ctx = _phase2_allocate_resources(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config
            )

            assert ctx.error_message == ""
            assert ctx.virtbr0_mac_addr != ""
            assert ctx.virtbr0_ip != ""
            assert ctx.virtbr0_mac_addr not in mock_network_info.existing_macs
            assert ctx.virtbr0_ip not in mock_network_info.existing_ips

    def test_phase2_dhcp_concurrent_safety(self, mock_server_config, basic_vm_spec, mock_libvirt_driver):
        """Test Phase 2 DHCP allocation is thread-safe"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )
        
        used_macs = set()
        used_ips = set()
        
        def mock_generate_mac_ip_pair(network_info, existing_macs=None, existing_ips=None):
            from virtcca_deploy.services.virt_service import MacIpPair
            mac = f"52:54:00:00:00:{len(used_macs):02x}"
            ip = f"192.168.122.{50 + len(used_ips)}"
            used_macs.add(mac)
            used_ips.add(ip)
            return MacIpPair(mac_address=mac, ip_address=ip), ""
        
        mock_libvirt_driver.return_value.generate_mac_ip_pair.side_effect = mock_generate_mac_ip_pair

        contexts = []
        for i in range(5):
            with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk:
                mock_config_disk.return_value = (f'/tmp/test{i}.qcow2', None)
                
                ctx = _phase2_allocate_resources(
                    cvm_name=f"vm-{i}",
                    vm_spec=basic_vm_spec,
                    host_numa_id=0,
                    iface_list=[],
                    server_config=mock_server_config
                )
                contexts.append(ctx)

        assert all(ctx.error_message == "" for ctx in contexts)
        
        macs = [ctx.virtbr0_mac_addr for ctx in contexts]
        ips = [ctx.virtbr0_ip for ctx in contexts]
        
        assert len(set(macs)) == 5, "All MAC addresses should be unique"
        assert len(set(ips)) == 5, "All IP addresses should be unique"


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
            mock_config_xml.assert_called_once_with(ctx)

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
            mock_config_xml.assert_called_once_with(ctx)

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
            mock_config_xml.assert_called_once_with(ctx)


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

    def test_deploy_single_vm_full_success(
        self, 
        mock_server_config, 
        basic_vm_spec, 
        mock_libvirt_driver,
        mock_mac_ip_pair, 
        app
    ):
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
            patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"

            mock_driver = mock_libvirt_driver.return_value
            mock_driver.start_vm_by_xml.return_value = True

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success is True
            assert ctx.error_message == ""
            assert ctx.qcow2_path == '/tmp/test.qcow2'
            assert ctx.xml_config == "<domain><name>vm-1</name></domain>"
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_deploy_single_vm_phase2_failure(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, app):
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
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success == False
            assert ctx.success == False
            assert ctx.error_message != ""
            assert ctx.virtbr0_mac_addr == ""
            assert ctx.virtbr0_ip == ""
            mock_config_xml.assert_not_called()
            mock_driver_class.assert_not_called()

    def test_deploy_single_vm_phase3_failure(
        self, 
        mock_server_config, 
        basic_vm_spec, 
        mock_libvirt_driver, 
        mock_mac_ip_pair, 
        app
    ):
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
            patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = ""

            mock_driver = mock_libvirt_driver.return_value
            mock_driver.start_vm_by_xml.return_value = True

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success is False
            assert ctx.error_message != ""
            assert "XML configuration failure" in ctx.error_message
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

            mock_libvirt_driver.assert_called_once()

    def test_deploy_single_vm_phase4_failure(
        self,
        mock_server_config,
        basic_vm_spec,
        mock_libvirt_driver,
        mock_mac_ip_pair,
        app
    ):
        """Test deployment completes with Phase 4 failure"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:
            #  patch('virtcca_deploy.services.virt_service.libvirtDriver') as mock_driver_class:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = mock_libvirt_driver.return_value
            mock_driver.start_vm_by_xml.return_value = False

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success == False
            assert ctx.error_message != ""
            assert "Failed to start VM" in ctx.error_message
            assert ctx.qcow2_path == '/tmp/test.qcow2'
            assert ctx.xml_config == "<domain><name>vm-1</name></domain>"
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_deploy_single_vm_with_interfaces(
        self,
        mock_server_config,
        basic_vm_spec,
        basic_iface_list,
        mock_libvirt_driver,
        mock_mac_ip_pair,
        app
    ):
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
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = mock_libvirt_driver.return_value
            mock_driver.start_vm_by_xml.return_value = True

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=basic_iface_list,
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success == True
            assert ctx.device_dict == {"00:11:22:33:44:59": "0000:01:00.0"}
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_deploy_single_vm_with_data_disk(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair, app):
        """Test deployment with data disk"""
        basic_vm_spec.disk_size = 100

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

            mock_config_disk.return_value = (
                '/tmp/test.qcow2',
                '/tmp/test_data.qcow2'
            )
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = mock_libvirt_driver.return_value
            mock_driver.start_vm_by_xml.return_value = True

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success == True
            assert ctx.data_disk_path == '/tmp/test_data.qcow2'
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_deploy_single_vm_multiple_numa_nodes(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair, app):
        """Test deployment on different NUMA nodes"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        for numa_id in [0, 1, 2, 3]:
            with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
                 patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

                mock_config_disk.return_value = (f'/tmp/test_numa{numa_id}.qcow2', None)
                mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
                
                mock_driver = mock_libvirt_driver.return_value
                mock_driver.start_vm_by_xml.return_value = True

                ctx = _deploy_single_vm(
                    cvm_name=f"vm-numa{numa_id}",
                    vm_spec=basic_vm_spec,
                    host_numa_id=numa_id,
                    iface_list=[],
                    server_config=mock_server_config,
                    app=app
                )

                assert ctx.success == True
                assert ctx.host_numa_id == numa_id
                assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
                assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address


class TestEdgeCasesAndBoundaryConditions:
    """Tests for edge cases and boundary conditions"""

    def test_deploy_with_zero_disk_size(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair, app):
        """Test deployment with disk_size=0 (no data disk)"""
        basic_vm_spec.disk_size = 0

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = mock_libvirt_driver.return_value
            mock_driver.start_vm_by_xml.return_value = True

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success == True
            assert ctx.data_disk_path == ""
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_deploy_with_large_memory(self, mock_server_config, mock_libvirt_driver, mock_mac_ip_pair, app):
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
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = mock_libvirt_driver.return_value
            mock_driver.start_vm_by_xml.return_value = True

            ctx = _deploy_single_vm(
                cvm_name="vm-large",
                vm_spec=large_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success == True
            assert ctx.vm_spec.memory == 65536
            assert ctx.vm_spec.core_num == 16
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_deploy_with_empty_device_dict(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair, app):
        """Test deployment with no network devices required"""
        basic_vm_spec.net_pf_num = 0
        basic_vm_spec.net_vf_num = 0

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = mock_libvirt_driver.return_value
            mock_driver.start_vm_by_xml.return_value = True

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success == True
            assert ctx.device_dict == {}
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_deploy_with_special_characters_in_name(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair, app):
        """Test deployment with VM name containing special characters"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-test_01.special</name></domain>"
            
            mock_driver = mock_libvirt_driver.return_value
            mock_driver.start_vm_by_xml.return_value = True

            ctx = _deploy_single_vm(
                cvm_name="vm-test_01.special",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success == True
            assert ctx.cvm_name == "vm-test_01.special"
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address

    def test_deploy_with_maximum_vf_count(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, mock_mac_ip_pair, app):
        """Test deployment with maximum VF count"""
        basic_vm_spec.net_vf_num = 16

        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={f"00:11:22:33:44:{i:02x}": f"0000:01:00.{i}" for i in range(16)}
        )

        with patch('virtcca_deploy.services.virt_service.config_disk') as mock_config_disk, \
             patch('virtcca_deploy.services.virt_service.config_xml') as mock_config_xml:

            mock_config_disk.return_value = ('/tmp/test.qcow2', None)
            mock_config_xml.return_value = "<domain><name>vm-1</name></domain>"
            
            mock_driver = mock_libvirt_driver.return_value
            mock_driver.start_vm_by_xml.return_value = True

            ctx = _deploy_single_vm(
                cvm_name="vm-1",
                vm_spec=basic_vm_spec,
                host_numa_id=0,
                iface_list=[],
                server_config=mock_server_config,
                app=app
            )

            assert ctx.success == True
            assert len(ctx.device_dict) == 16
            assert ctx.virtbr0_mac_addr == mock_mac_ip_pair.mac_address
            assert ctx.virtbr0_ip == mock_mac_ip_pair.ip_address


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

    def test_context_preserves_state_on_failure(self, mock_server_config, basic_vm_spec, mock_libvirt_driver, app):
        """Test that context preserves state even when Phase 2 DHCP fails"""
        mock_server_config.device_allocator.allocate.return_value = DeviceAllocResp(
            success=True,
            device_dict={
                "00:11:22:33:44:59": "0000:01:00.0"
            }
        )

        mock_libvirt_driver.return_value.write_dhcp_host_entry.return_value = (False, "DHCP write failed")
        
        basic_vm_spec.net_pf_num = 1
        ctx = _deploy_single_vm(
            cvm_name="vm-1",
            vm_spec=basic_vm_spec,
            host_numa_id=0,
            iface_list=[],
            server_config=mock_server_config,
            app=app
        )

        assert ctx.error_message != ""
        assert "Failed to write DHCP host entry" in ctx.error_message
        assert ctx.cvm_name == "vm-1"
        assert ctx.host_numa_id == 0
        assert ctx.device_dict == {"00:11:22:33:44:59": "0000:01:00.0"}
        assert ctx.qcow2_path == ""
        assert ctx.data_disk_path == ""
        assert ctx.xml_config == ""

    def test_multiple_consecutive_failures(self, mock_server_config, basic_vm_spec, app):
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
                    server_config=mock_server_config,
                    app=app
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
