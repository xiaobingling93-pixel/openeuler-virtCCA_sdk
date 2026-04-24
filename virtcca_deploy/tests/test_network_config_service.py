#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
Unit tests for network configuration service and database-based IP allocation
"""

import os
import sys
import json
import io
import tempfile
import pytest
from unittest import mock

from virtcca_deploy.services.network_config_service import NetworkConfigService


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


VALID_YAML_CONTENT = """
nodes:
  - node_name: "compute01"
    node_ip: "192.168.1.100"
    interfaces:
      - mac_address: "00:11:22:33:44:55"
        vlan_id: 100
        ip_address: "192.168.100.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:56"
        vlan_id: 200
        ip_address: "192.168.200.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"

      - mac_address: "00:11:22:33:44:57"
        vlan_id: 100
        ip_address: "192.168.100.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:58"
        vlan_id: 200
        ip_address: "192.168.200.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"

  - node_name: "compute02"
    node_ip: "192.168.1.101"
    interfaces:
      - mac_address: "00:11:22:33:44:59"
        vlan_id: 100
        ip_address: "192.168.110.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"
"""

INVALID_YAML_MISSING_NODES = """
some_key: "some_value"
"""

INVALID_YAML_MISSING_INTERFACES = """
nodes:
  - node_name: "compute01"
    node_ip: "192.168.1.100"
"""

INVALID_YAML_BAD_FORMAT = """
nodes:
  - node_name: "compute01"
    node_ip: "192.168.1.100"
    interfaces:
      "invalid-mac":
        vlan_id: 100
        ip_address: "192.168.100.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"
"""


@pytest.fixture
def yaml_config_file():
    """Create a temporary YAML config file"""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.yaml', delete=False
    ) as f:
        f.write(VALID_YAML_CONTENT)
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def app():
    """Create test Flask app with in-memory SQLite"""
    import tempfile as tmp
    from virtcca_deploy.services.db_service import db
    from virtcca_deploy.manager import manager
    from conftest import TestConfig

    main_temp_dir = tmp.mkdtemp(prefix="virtcca_net_test_")

    with mock.patch.multiple('virtcca_deploy.common.constants',
        DEFAULT_CONFIG_PATH=main_temp_dir,
        MANAGER_DB_PATH=main_temp_dir,
        MANAGER_DB='sqlite:///:memory:',
        CVM_COLLECT_LOG_PATH=os.path.join(main_temp_dir, "logs"),
        CVM_MANAGER_SOFTWARE_PATH=os.path.join(main_temp_dir, "software")):

        test_config = TestConfig()

        with mock.patch('virtcca_deploy.common.config.Config', return_value=test_config):
            app = manager.create_app()

            app.config.update({
                'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                'SQLALCHEMY_TRACK_MODIFICATIONS': False,
                'TESTING': True,
            })

            with app.app_context():
                db.create_all()

            yield app

            try:
                import shutil
                if os.path.exists(main_temp_dir):
                    shutil.rmtree(main_temp_dir)
            except:
                pass


class TestNetworkConfigService:
    """Test network configuration service"""

    def test_validate_and_store_yaml_success(self, app, yaml_config_file):
        """Test successful YAML validation and storage"""
        from virtcca_deploy.services.db_service import NetworkConfig

        with app.app_context():
            service = NetworkConfigService()
            success, error_msg = service.validate_and_store_yaml(yaml_config_file)

            assert success is True
            assert error_msg == ""

            configs = NetworkConfig.query.all()
            assert len(configs) == 5

            for config in configs:
                assert config.status == NetworkConfig.STATUS_UNUSED

    def test_validate_and_store_yaml_invalid_format(self, app):
        """Test YAML validation with invalid format"""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write(INVALID_YAML_BAD_FORMAT)
            f.flush()
            temp_file = f.name

        try:
            with app.app_context():
                service = NetworkConfigService()
                success, error_msg = service.validate_and_store_yaml(temp_file)

                assert success is False
                assert "invalid MAC address" in error_msg.lower() or "validation failed" in error_msg.lower()
        finally:
            os.unlink(temp_file)

    def test_validate_and_store_yaml_missing_nodes(self, app):
        """Test YAML validation with missing nodes key"""

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write(INVALID_YAML_MISSING_NODES)
            f.flush()
            temp_file = f.name

        try:
            with app.app_context():
                service = NetworkConfigService()
                success, error_msg = service.validate_and_store_yaml(temp_file)

                assert success is False
                assert "nodes" in error_msg.lower() or "validation failed" in error_msg.lower()
        finally:
            os.unlink(temp_file)

    def test_validate_and_store_yaml_rejects_when_used(self, app, yaml_config_file):
        """Test that update is rejected when configs are in 'used' status"""
        from virtcca_deploy.services.db_service import NetworkConfig

        with app.app_context():
            service = NetworkConfigService()

            success, _ = service.validate_and_store_yaml(yaml_config_file)
            assert success is True

            config = NetworkConfig.query.first()
            config.status = NetworkConfig.STATUS_USED
            from virtcca_deploy.services.db_service import db
            db.session.commit()

            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.yaml', delete=False
            ) as f:
                f.write(VALID_YAML_CONTENT)
                f.flush()
                new_file = f.name

            try:
                success, error_msg = service.validate_and_store_yaml(new_file)
                assert success is False
                assert "active network resources are in use" in error_msg
            finally:
                os.unlink(new_file)

    def test_allocate_ips_success(self, app, yaml_config_file):
        """Test successful IP allocation"""
        from virtcca_deploy.services.db_service import NetworkConfig

        with app.app_context():
            service = NetworkConfigService()
            service.validate_and_store_yaml(yaml_config_file)

            success, vm_ip_map, vm_iface_map, error_msg = (
                service.allocate_ips_for_deployment(
                    node_name="compute01",
                    pf_num=1,
                    vm_id_list=["compute01-1", "compute01-2"]
                )
            )

            assert success is True
            assert error_msg == ""
            assert len(vm_ip_map) == 2
            assert "compute01-1" in vm_ip_map
            assert "compute01-2" in vm_ip_map

            used_configs = NetworkConfig.query.filter_by(
                status=NetworkConfig.STATUS_USED
            ).all()
            assert len(used_configs) == 2

            vm_id_set = {config.vm_id for config in used_configs}
            assert "compute01-1" in vm_id_set
            assert "compute01-2" in vm_id_set

    def test_allocate_ips_node_not_found(self, app, yaml_config_file):
        """Test IP allocation with non-existent node"""
        

        with app.app_context():
            service = NetworkConfigService()
            service.validate_and_store_yaml(yaml_config_file)

            success, vm_ip_map, vm_iface_map, error_msg = (
                service.allocate_ips_for_deployment(
                    node_name="nonexistent_node",
                    pf_num=1,
                    vm_id_list=["vm-1"]
                )
            )

            assert success is False
            assert "No network configuration found for node 'nonexistent_node'" in error_msg

    def test_allocate_ips_insufficient_interfaces(self, app, yaml_config_file):
        """Test IP allocation with insufficient interfaces"""

        with app.app_context():
            service = NetworkConfigService()
            service.validate_and_store_yaml(yaml_config_file)

            success, vm_ip_map, vm_iface_map, error_msg = (
                service.allocate_ips_for_deployment(
                    node_name="compute01",
                    pf_num=3,
                    vm_id_list=["compute01-1", "compute01-2"]
                )
            )

            assert success is False
            assert "Insufficient interfaces" in error_msg
            assert "required 6" in error_msg
            assert "available 4" in error_msg

    def test_release_ips_success(self, app, yaml_config_file):
        """Test successful IP release"""
        from virtcca_deploy.services.db_service import NetworkConfig, VmInstance
        from virtcca_deploy.services.db_service import db

        with app.app_context():
            service = NetworkConfigService()
            service.validate_and_store_yaml(yaml_config_file)

            service.allocate_ips_for_deployment(
                node_name="compute01",
                pf_num=1,
                vm_id_list=["compute01-1"]
            )

            vm = VmInstance(
                vm_id="compute01-1",
                host_ip="192.168.1.100",
                host_name="compute01",
                vm_spec_uuid="test-uuid",
                iface_list=json.dumps([{
                    "node_name": "compute01",
                    "mac_address": "00:11:22:33:44:55",
                    "vlan_id": 100,
                    "ip_address": "192.168.100.10",
                    "subnet_mask": "255.255.255.0",
                    "gateway": "192.168.100.1"
                }]),
                os_version="openEuler-2403LTS-SP2"
            )
            db.session.add(vm)
            db.session.commit()

            success, error_msg = service.release_ips_for_vms(["compute01-1"])

            assert success is True
            assert error_msg == ""

            config = NetworkConfig.query.filter_by(
                mac_address="00:11:22:33:44:55"
            ).first()
            assert config.status == NetworkConfig.STATUS_UNUSED


class TestIpAllocator:
    """Test database-based IP allocator"""

    def test_allocate_from_database(self, app, yaml_config_file):
        """Test IP allocation from database"""
        from virtcca_deploy.services.resource_allocator import IpAllocator
        from virtcca_deploy.common.data_model import NetAllocReq
        from virtcca_deploy.services.db_service import ComputeNode, NetworkConfig, db

        with app.app_context():
            node = ComputeNode(
                nodename="compute01",
                ip="192.168.1.100",
                physical_cpu=8,
                memory=16384,
                memory_free=8192,
                secure_memory=4096,
                secure_memory_free=2048
            )
            db.session.add(node)

            iface_configs = [
                NetworkConfig(
                    node_name="compute01",
                    mac_address="00:11:22:33:44:55",
                    vlan_id=100,
                    ip_address="192.168.100.10",
                    subnet_mask="255.255.255.0",
                    gateway="192.168.100.1",
                    status=NetworkConfig.STATUS_UNUSED
                ),
                NetworkConfig(
                    node_name="compute01",
                    mac_address="00:11:22:33:44:56",
                    vlan_id=100,
                    ip_address="192.168.200.10",
                    subnet_mask="255.255.255.0",
                    gateway="192.168.200.1",
                    status=NetworkConfig.STATUS_UNUSED
                ),
            ]
            for config in iface_configs:
                db.session.add(config)

            db.session.commit()

            allocator = IpAllocator()

            request = NetAllocReq(
                vm_id_list=["compute01-1", "compute01-2"],
                vlan_id=100,
                pf_num=1,
                vf_num=0,
                node_ip="192.168.1.100"
            )

            response = allocator.allocate(request)

            assert response.success is True
            assert len(response.vm_iface_map) == 2
            assert len(response.failed_vms) == 0

    def test_allocate_node_not_in_database(self, app, yaml_config_file):
        """Test IP allocation when node not in database"""
        from virtcca_deploy.services.resource_allocator import IpAllocator
        from virtcca_deploy.common.data_model import NetAllocReq

        with app.app_context():
            allocator = IpAllocator()

            request = NetAllocReq(
                vm_id_list=["vm-1"],
                vlan_id=100,
                pf_num=1,
                vf_num=0,
                node_ip="192.168.99.99"
            )

            response = allocator.allocate(request)

            assert response.success is False
            assert len(response.failed_vms) == 1

    def test_release_ips(self, app, yaml_config_file):
        """Test IP release"""
        from virtcca_deploy.services.resource_allocator import IpAllocator
        from virtcca_deploy.common.data_model import NetAllocReq, NetReleaseReq
        from virtcca_deploy.services.db_service import ComputeNode, NetworkConfig, VmInstance, db

        with app.app_context():
            node = ComputeNode(
                nodename="compute01",
                ip="192.168.1.100",
                physical_cpu=8,
                memory=16384,
                memory_free=8192,
                secure_memory=4096,
                secure_memory_free=2048
            )
            db.session.add(node)

            iface_configs = [
                NetworkConfig(
                    node_name="compute01",
                    mac_address="00:11:22:33:44:55",
                    vlan_id=100,
                    ip_address="192.168.100.10",
                    subnet_mask="255.255.255.0",
                    gateway="192.168.100.1",
                    status=NetworkConfig.STATUS_UNUSED
                ),
            ]
            for config in iface_configs:
                db.session.add(config)

            db.session.commit()

            allocator = IpAllocator()

            alloc_request = NetAllocReq(
                vm_id_list=["compute01-1"],
                vlan_id=100,
                pf_num=1,
                vf_num=0,
                node_ip="192.168.1.100"
            )
            alloc_response = allocator.allocate(alloc_request)
            assert alloc_response.success is True

            vm = VmInstance(
                vm_id="compute01-1",
                host_ip="192.168.1.100",
                host_name="compute01",
                vm_spec_uuid="test-uuid",
                iface_list=json.dumps([{
                    "mac_address": "00:11:22:33:44:55",
                    "vlan_id": 100,
                    "ip_address": "192.168.100.10",
                    "subnet_mask": "255.255.255.0",
                    "gateway": "192.168.100.1"
                }]),
                os_version="openEuler-2403LTS-SP2"
            )
            db.session.add(vm)
            db.session.commit()

            release_request = NetReleaseReq(vm_id_list=["compute01-1"])
            release_response = allocator.release(release_request)

            assert release_response.success is True
            assert "compute01-1" in release_response.released_vms



class TestNetworkConfigUpload:
    """Test network config upload via API"""

    def test_upload_network_config_success(self, app, authenticated_client, yaml_config_file):
        """Test successful network config upload"""
        from virtcca_deploy.services.db_service import db

        with app.app_context():
            with open(yaml_config_file, 'rb') as f:
                file_content = f.read()

            import hashlib
            file_hash = "sha256:" + hashlib.sha256(file_content).hexdigest()

            data = {
                'file': (io.BytesIO(file_content), 'network_config.yaml'),
                'file_name': 'network_config.yaml',
                'file_hash': file_hash,
                'file_size': str(len(file_content))
            }

            response = authenticated_client.post(
                '/api/v1/vm/software',
                data=data,
                content_type='multipart/form-data'
            )

            assert response.status_code == 200
            response_data = response.get_json()

    def test_upload_network_config_invalid_yaml(self, app, authenticated_client):
        """Test upload of invalid YAML config"""
        import io

        invalid_yaml = b"""
nodes:
  - node_name: "compute01"
    node_ip: "192.168.1.100"
    interfaces:
      "invalid-mac-format":
        vlan_id: 100
        ip_address: "192.168.100.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"
"""

        data = {
            'file': (io.BytesIO(invalid_yaml), 'network_config.yaml'),
            'file_name': 'network_config.yaml',
            'file_hash': 'sha256:dummy',
            'file_size': str(len(invalid_yaml))
        }

        response = authenticated_client.post(
            '/api/v1/vm/software',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 400
        response_data = response.get_json()
        assert 'message' in response_data

    def test_has_used_configs_returns_false_when_all_unused(self, app, yaml_config_file):
        """Test has_used_configs returns False when all configs are unused"""

        with app.app_context():
            service = NetworkConfigService()
            service.validate_and_store_yaml(yaml_config_file)

            assert service.has_used_configs() is False

    def test_has_used_configs_returns_true_when_any_used(self, app, yaml_config_file):
        """Test has_used_configs returns True when any config is used"""
        from virtcca_deploy.services.db_service import NetworkConfig, db

        with app.app_context():
            service = NetworkConfigService()
            service.validate_and_store_yaml(yaml_config_file)

            config = NetworkConfig.query.first()
            config.status = NetworkConfig.STATUS_USED
            db.session.commit()

            assert service.has_used_configs() is True

    def test_has_used_configs_returns_false_when_empty(self, app):
        """Test has_used_configs returns False when no configs exist"""
        with app.app_context():
            service = NetworkConfigService()

            assert service.has_used_configs() is False


class TestVlanGroupingAllocation:
    """Test VLAN ID grouping allocation mechanism"""

    def test_vlan_grouping_single_vlan_single_pf(self, app):
        """Test allocation with single VLAN ID and pf_num=1"""
        yaml_content = """
nodes:
  - node_name: "compute01"
    node_ip: "192.168.1.100"
    interfaces:
      - mac_address: "00:11:22:33:44:55"
        vlan_id: 100
        ip_address: "192.168.100.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:56"
        vlan_id: 100
        ip_address: "192.168.100.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:57"
        vlan_id: 100
        ip_address: "192.168.100.12"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            temp_file = f.name

        try:
            with app.app_context():
                service = NetworkConfigService()
                service.validate_and_store_yaml(temp_file)

                success, vm_ip_map, vm_iface_map, error_msg = (
                    service.allocate_ips_for_deployment(
                        node_name="compute01",
                        pf_num=1,
                        vm_id_list=["vm-1", "vm-2", "vm-3"]
                    )
                )

                assert success is True
                assert error_msg == ""
                assert len(vm_ip_map) == 3

                for vm_id in ["vm-1", "vm-2", "vm-3"]:
                    assert vm_id in vm_iface_map
                    assert len(vm_iface_map[vm_id]) == 1
                    assert vm_iface_map[vm_id][0]["vlan_id"] == 100
        finally:
            os.unlink(temp_file)

    def test_vlan_grouping_multiple_vlans(self, app):
        """Test allocation with multiple VLANs - each VM gets different VLAN per interface"""
        yaml_content = """
nodes:
  - node_name: "compute01"
    node_ip: "192.168.1.100"
    interfaces:
      - mac_address: "00:11:22:33:44:55"
        vlan_id: 100
        ip_address: "192.168.100.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:56"
        vlan_id: 100
        ip_address: "192.168.100.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:57"
        vlan_id: 200
        ip_address: "192.168.200.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"

      - mac_address: "00:11:22:33:44:58"
        vlan_id: 200
        ip_address: "192.168.200.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            temp_file = f.name

        try:
            with app.app_context():
                service = NetworkConfigService()
                service.validate_and_store_yaml(temp_file)

                success, vm_ip_map, vm_iface_map, error_msg = (
                    service.allocate_ips_for_deployment(
                        node_name="compute01",
                        pf_num=2,
                        vm_id_list=["vm-1", "vm-2"]
                    )
                )

                assert success is True
                assert error_msg == ""

                for vm_id in ["vm-1", "vm-2"]:
                    assert vm_id in vm_iface_map
                    assert len(vm_iface_map[vm_id]) == 2
                    
                    vm_vlan_ids = [iface["vlan_id"] for iface in vm_iface_map[vm_id]]
                    
                    assert len(set(vm_vlan_ids)) == 2, (
                        f"VM {vm_id} 的接口 VLAN ID 不唯一: {vm_vlan_ids}"
                    )
                    
                    assert sorted(vm_vlan_ids) == [100, 200], (
                        f"VM {vm_id} 的 VLAN ID 集合错误: {vm_vlan_ids}"
                    )
        finally:
            os.unlink(temp_file)

    def test_vlan_grouping_insufficient_vlan_count(self, app):
        """Test allocation fails when VLAN count < pf_num"""
        yaml_content = """
nodes:
  - node_name: "compute01"
    node_ip: "192.168.1.100"
    interfaces:
      - mac_address: "00:11:22:33:44:55"
        vlan_id: 100
        ip_address: "192.168.100.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:56"
        vlan_id: 100
        ip_address: "192.168.100.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:57"
        vlan_id: 200
        ip_address: "192.168.200.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            temp_file = f.name

        try:
            with app.app_context():
                service = NetworkConfigService()
                service.validate_and_store_yaml(temp_file)

                success, vm_ip_map, vm_iface_map, error_msg = (
                    service.allocate_ips_for_deployment(
                        node_name="compute01",
                        pf_num=3,
                        vm_id_list=["vm-1"]
                    )
                )
                assert "Insufficient VLAN IDs" in error_msg
                assert "need 3 different VLAN IDs" in error_msg
                assert "only has 2 VLAN IDs" in error_msg
        finally:
            os.unlink(temp_file)

    def test_vlan_grouping_insufficient_interfaces_per_vlan(self, app):
        """Test allocation fails when specific VLAN lacks sufficient interfaces"""

        yaml_content = """
nodes:
  - node_name: "compute01"
    node_ip: "192.168.1.100"
    interfaces:
      - mac_address: "00:11:22:33:44:55"
        vlan_id: 100
        ip_address: "192.168.100.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:56"
        vlan_id: 100
        ip_address: "192.168.100.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:57"
        vlan_id: 200
        ip_address: "192.168.200.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            temp_file = f.name

        try:
            with app.app_context():
                service = NetworkConfigService()
                service.validate_and_store_yaml(temp_file)

                success, vm_ip_map, vm_iface_map, error_msg = (
                    service.allocate_ips_for_deployment(
                        node_name="compute01",
                        pf_num=2,
                        vm_id_list=["vm-1", "vm-2"]
                    )
                )

                assert success is False
                assert "Insufficient interfaces: required 4, available 3" in error_msg

        finally:
            os.unlink(temp_file)

    def test_vlan_grouping_consistency_across_vms(self, app):
        """Test that all VMs receive identical VLAN ID sets"""

        yaml_content = """
nodes:
  - node_name: "compute01"
    node_ip: "192.168.1.100"
    interfaces:
      - mac_address: "00:11:22:33:44:55"
        vlan_id: 100
        ip_address: "192.168.100.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:56"
        vlan_id: 100
        ip_address: "192.168.100.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:57"
        vlan_id: 200
        ip_address: "192.168.200.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"

      - mac_address: "00:11:22:33:44:58"
        vlan_id: 200
        ip_address: "192.168.200.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"

      - mac_address: "00:11:22:33:44:59"
        vlan_id: 300
        ip_address: "192.168.110.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.110.1"

      - mac_address: "00:11:22:33:44:60"
        vlan_id: 300
        ip_address: "192.168.110.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.110.1"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            temp_file = f.name

        try:
            with app.app_context():
                service = NetworkConfigService()
                service.validate_and_store_yaml(temp_file)

                success, vm_ip_map, vm_iface_map, error_msg = (
                    service.allocate_ips_for_deployment(
                        node_name="compute01",
                        pf_num=2,
                        vm_id_list=["vm-1", "vm-2"]
                    )
                )

                assert success is True

                vm1_vlans = sorted([iface["vlan_id"] for iface in vm_iface_map["vm-1"]])
                vm2_vlans = sorted([iface["vlan_id"] for iface in vm_iface_map["vm-2"]])

                assert vm1_vlans == vm2_vlans, (
                    f"VLAN 不一致: vm-1 有 {vm1_vlans}, vm-2 有 {vm2_vlans}"
                )

                assert len(vm_iface_map["vm-1"]) == 2
                assert len(vm_iface_map["vm-2"]) == 2

                for vm_id in ["vm-1", "vm-2"]:
                    vm_vlan_ids = [iface["vlan_id"] for iface in vm_iface_map[vm_id]]
                    assert len(set(vm_vlan_ids)) == 2, (
                        f"VM {vm_id} 的接口 VLAN ID 不唯一: {vm_vlan_ids}"
                    )
        finally:
            os.unlink(temp_file)

    def test_group_configs_by_vlan_method(self, app):
        """Test the _group_configs_by_vlan helper method"""
        from virtcca_deploy.services.db_service import NetworkConfig

        with app.app_context():
            service = NetworkConfigService()

            configs = [
                NetworkConfig(
                    node_name="test",
                    mac_address="00:11:22:33:44:55",
                    vlan_id=100,
                    ip_address="192.168.100.10",
                    subnet_mask="255.255.255.0",
                    gateway="192.168.100.1",
                    status=NetworkConfig.STATUS_UNUSED
                ),
                NetworkConfig(
                    node_name="test",
                    mac_address="00:11:22:33:44:56",
                    vlan_id=200,
                    ip_address="192.168.200.10",
                    subnet_mask="255.255.255.0",
                    gateway="192.168.200.1",
                    status=NetworkConfig.STATUS_UNUSED
                ),
                NetworkConfig(
                    node_name="test",
                    mac_address="00:11:22:33:44:57",
                    vlan_id=100,
                    ip_address="192.168.100.11",
                    subnet_mask="255.255.255.0",
                    gateway="192.168.100.1",
                    status=NetworkConfig.STATUS_UNUSED
                ),
            ]

            vlan_groups = service._group_configs_by_vlan(configs)

            assert len(vlan_groups) == 2
            assert 100 in vlan_groups
            assert 200 in vlan_groups
            assert len(vlan_groups[100]) == 2
            assert len(vlan_groups[200]) == 1

    def test_vlan_grouping_three_vms_three_vlans(self, app):
        """Test allocation with 3 VMs and 3 VLANs"""
        yaml_content = """
nodes:
  - node_name: "compute01"
    node_ip: "192.168.1.100"
    interfaces:
      - mac_address: "00:11:22:33:44:55"
        vlan_id: 100
        ip_address: "192.168.100.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:56"
        vlan_id: 100
        ip_address: "192.168.100.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:57"
        vlan_id: 100
        ip_address: "192.168.100.12"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.100.1"

      - mac_address: "00:11:22:33:44:58"
        vlan_id: 200
        ip_address: "192.168.200.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"

      - mac_address: "00:11:22:33:44:59"
        vlan_id: 200
        ip_address: "192.168.200.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"

      - mac_address: "00:11:22:33:44:60"
        vlan_id: 200
        ip_address: "192.168.200.12"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.200.1"

      - mac_address: "00:11:22:33:44:61"
        vlan_id: 300
        ip_address: "192.168.110.10"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.110.1"

      - mac_address: "00:11:22:33:44:62"
        vlan_id: 300
        ip_address: "192.168.110.11"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.110.1"

      - mac_address: "00:11:22:33:44:63"
        vlan_id: 300
        ip_address: "192.168.110.12"
        subnet_mask: "255.255.255.0"
        gateway: "192.168.110.1"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            temp_file = f.name

        try:
            with app.app_context():
                service = NetworkConfigService()
                service.validate_and_store_yaml(temp_file)

                success, vm_ip_map, vm_iface_map, error_msg = (
                    service.allocate_ips_for_deployment(
                        node_name="compute01",
                        pf_num=3,
                        vm_id_list=["vm-1", "vm-2", "vm-3"]
                    )
                )

                assert success is True

                for vm_id in ["vm-1", "vm-2", "vm-3"]:
                    assert vm_id in vm_iface_map
                    assert len(vm_iface_map[vm_id]) == 3
                    
                    vm_vlan_ids = [iface["vlan_id"] for iface in vm_iface_map[vm_id]]
                    
                    assert len(set(vm_vlan_ids)) == 3, (
                        f"VM {vm_id} 的接口 VLAN ID 不唯一: {vm_vlan_ids}"
                    )
                    
                    assert sorted(vm_vlan_ids) == [100, 200, 300], (
                        f"VM {vm_id} 的 VLAN ID 集合错误: {vm_vlan_ids}"
                    )
        finally:
            os.unlink(temp_file)
