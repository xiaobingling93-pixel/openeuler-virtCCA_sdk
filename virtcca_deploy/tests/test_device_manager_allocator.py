#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from gevent import monkey
monkey.patch_all()

import pytest
from unittest import mock
from unittest.mock import mock_open, patch, MagicMock

from virtcca_deploy.common.constants import ValidationError, DeviceTypeConfig
from virtcca_deploy.common.data_model import DeviceAllocReq, DeviceReleaseReq, SriovVfSetupResp
from virtcca_deploy.services.resource_allocator import DeviceManagerAllocator
from virtcca_deploy.services.db_service import db, DeviceAllocation


def _mock_lspci_output(lines):
    result = mock.MagicMock()
    result.returncode = 0
    result.stdout = "\n".join(lines) + "\n"
    return result

LSPCI_SAMPLE = [
    "0000:3b:00.0 0200: 19e5:1822 (rev 10)",
    "0000:3b:00.1 0200: 19e5:1821 (rev 10)",
    "0000:3b:01.0 0200: 19e5:0200 (rev 10)",
    "0000:3b:01.1 0200: 19e5:0201 (rev 10)",
    "0000:00:1f.0 0200: 8086:1234 (rev 10)",
    "0000:00:02.0 0200: 8086:5916 (rev 10)",
]

@pytest.fixture
def allocator():
    return DeviceManagerAllocator()


# ========== 参数验证测试 ==========

class TestValidatePciIds:

    def test_valid_ids(self, allocator):
        allocator._validate_pci_ids(0x19e5, 0x1822)

    def test_zero_ids(self, allocator):
        allocator._validate_pci_ids(0x0000, 0x0000)

    def test_max_ids(self, allocator):
        allocator._validate_pci_ids(0xFFFF, 0xFFFF)

    def test_vendor_id_not_int(self, allocator):
        with pytest.raises(ValidationError, match="vendor_id must be int"):
            allocator._validate_pci_ids("0x19e5", 0x1822)

    def test_device_id_not_int(self, allocator):
        with pytest.raises(ValidationError, match="device_id must be int"):
            allocator._validate_pci_ids(0x19e5, "0x1822")

    def test_vendor_id_negative(self, allocator):
        with pytest.raises(ValidationError, match="vendor_id out of range"):
            allocator._validate_pci_ids(-1, 0x1822)

    def test_vendor_id_overflow(self, allocator):
        with pytest.raises(ValidationError, match="vendor_id out of range"):
            allocator._validate_pci_ids(0x10000, 0x1822)

    def test_device_id_negative(self, allocator):
        with pytest.raises(ValidationError, match="device_id out of range"):
            allocator._validate_pci_ids(0x19e5, -1)

    def test_device_id_overflow(self, allocator):
        with pytest.raises(ValidationError, match="device_id out of range"):
            allocator._validate_pci_ids(0x19e5, 0x10000)


# ========== NUMA 节点读取测试 ==========

class TestReadNumaNode:

    @patch('builtins.open', mock_open(read_data='0\n'))
    def test_read_valid_numa_node(self, allocator):
        result = allocator._read_numa_node("0000:3b:00.0")
        assert result == 0

    @patch('builtins.open', mock_open(read_data='1\n'))
    def test_read_numa_node_1(self, allocator):
        result = allocator._read_numa_node("0000:3b:01.0")
        assert result == 1

    @patch('builtins.open', mock_open(read_data='-1\n'))
    def test_read_numa_node_minus1(self, allocator):
        result = allocator._read_numa_node("0000:00:1f.0")
        assert result == -1

    @patch('builtins.open', side_effect=FileNotFoundError)
    def test_numa_node_file_not_found(self, mock_file, allocator):
        result = allocator._read_numa_node("0000:ff:ff.0")
        assert result == -1

    @patch('builtins.open', mock_open(read_data='invalid\n'))
    def test_numa_node_invalid_value(self, allocator):
        result = allocator._read_numa_node("0000:3b:00.0")
        assert result == -1

    @patch('builtins.open', side_effect=OSError("permission denied"))
    def test_numa_node_os_error(self, mock_file, allocator):
        result = allocator._read_numa_node("0000:3b:00.0")
        assert result == -1


# ========== 设备发现测试 ==========

class TestFindDeviceWithLspci:

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_find_single_device(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        results = allocator.find_device(0x19e5, 0x1822)

        assert len(results) == 1
        assert results[0]['bdf'] == "0000:3b:00.0"
        assert results[0]['vendor_id'] == 0x19e5
        assert results[0]['device_id'] == 0x1822
        assert 'numa_node' in results[0]

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_find_no_match(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        results = allocator.find_device(0x10de, 0x9999)

        assert len(results) == 0

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_find_multiple_devices_same_vendor(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        results = allocator.find_device(0x8086, 0x1234)

        assert len(results) == 1
        assert results[0]['bdf'] == "0000:00:1f.0"

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_find_vf_device(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        results = allocator.find_device(0x19e5, 0x1821)

        assert len(results) == 1
        assert results[0]['bdf'] == "0000:3b:00.1"

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_find_with_bdf_filter(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        results = allocator.find_device(0x19e5, 0x1822, bdf="0000:3b:00.0")

        assert len(results) == 1
        assert results[0]['bdf'] == "0000:3b:00.0"

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_find_with_bdf_filter_no_match(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        results = allocator.find_device(0x19e5, 0x1822, bdf="0000:ff:ff.0")

        assert len(results) == 0

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    @mock.patch.object(DeviceManagerAllocator, '_read_numa_node', return_value=0)
    def test_find_with_numa_node_filter(self, mock_numa, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        results = allocator.find_device(0x19e5, 0x1822, numa_node=0)

        assert len(results) == 1
        assert results[0]['numa_node'] == 0

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    @mock.patch.object(DeviceManagerAllocator, '_read_numa_node', return_value=-1)
    def test_find_with_numa_node_filter_no_match(self, mock_numa, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        results = allocator.find_device(0x19e5, 0x1822, numa_node=1)

        assert len(results) == 0

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_find_with_refresh_forces_rescan(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        allocator.find_device(0x19e5, 0x1822)
        assert mock_run.call_count == 1

        allocator.find_device(0x19e5, 0x1822, refresh=True)
        assert mock_run.call_count == 2

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_find_empty_lspci_output(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output([])

        results = allocator.find_device(0x19e5, 0x1822)

        assert len(results) == 0


# ========== 缓存测试 ==========

class TestFindDeviceCache:

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_cache_hit_avoids_rescan(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        allocator.find_device(0x19e5, 0x1822)
        allocator.find_device(0x19e5, 0x1822)

        assert mock_run.call_count == 1

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_cache_miss_different_device_triggers_scan(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        allocator.find_device(0x19e5, 0x1822)
        allocator.find_device(0x19e5, 0x1821)

        assert mock_run.call_count == 1


# ========== lspci 错误处理测试 ==========

class TestFindDeviceLspciErrors:

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_lspci_command_not_found(self, mock_run, allocator):
        mock_run.side_effect = FileNotFoundError("lspci not found")

        results = allocator.find_device(0x19e5, 0x1822)

        assert len(results) == 0

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_lspci_timeout(self, mock_run, allocator):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='lspci', timeout=10)

        results = allocator.find_device(0x19e5, 0x1822)

        assert len(results) == 0

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_lspci_nonzero_exit(self, mock_run, allocator):
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"
        mock_run.return_value = mock_result

        results = allocator.find_device(0x19e5, 0x1822)

        assert len(results) == 0


# ========== PCI 设备枚举测试 ==========

class TestEnumeratePciDevices:

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_parse_standard_output(self, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(LSPCI_SAMPLE)

        devices = allocator._enumerate_pci_devices()

        assert devices is not None
        assert len(devices) == 6

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    def test_malformed_line_skipped(self, mock_run, allocator):
        lines = [
            "0000:3b:00.0 0200: 19e5:1822",
            "malformed line without pattern",
            "0000:00:1f.0 0200: 8086:1234",
        ]
        mock_run.return_value = _mock_lspci_output(lines)

        devices = allocator._enumerate_pci_devices()

        assert devices is not None
        assert len(devices) == 2

    @mock.patch('virtcca_deploy.services.resource_allocator.subprocess.run')
    @mock.patch.object(DeviceManagerAllocator, '_read_numa_node', return_value=1)
    def test_numa_node_in_enumerated_devices(self, mock_numa, mock_run, allocator):
        mock_run.return_value = _mock_lspci_output(["0000:3b:00.0 0200: 19e5:1822"])

        devices = allocator._enumerate_pci_devices()

        assert devices[0]['numa_node'] == 1


# ========== Hi1822 设备发现测试 ==========

class TestDiscoverHi1822Devices:

    @mock.patch.object(DeviceManagerAllocator, 'find_device')
    def test_discover_calls_find_device_for_each_id(self, mock_find, allocator):
        mock_find.return_value = [{"bdf": "0000:3b:00.0", "vendor_id": 0x19e5,
                                   "device_id": 0x1822, "numa_node": 0}]

        results = allocator.discover_hi1822_devices()

        assert mock_find.call_count == len(DeviceManagerAllocator.HI1822_DEVICE_IDS)
        assert len(results) == len(DeviceManagerAllocator.HI1822_DEVICE_IDS)

    @mock.patch.object(DeviceManagerAllocator, 'find_device')
    def test_discover_with_custom_vendor(self, mock_find, allocator):
        mock_find.return_value = []

        allocator.discover_hi1822_devices(vendor_id=0x8086)

        for call in mock_find.call_args_list:
            assert call[0][0] == 0x8086

    @mock.patch.object(DeviceManagerAllocator, 'find_device')
    def test_discover_with_custom_device_ids(self, mock_find, allocator):
        mock_find.return_value = []

        allocator.discover_hi1822_devices(device_ids=[0x1822])

        mock_find.assert_called_once_with(0x19e5, 0x1822)

    @mock.patch.object(DeviceManagerAllocator, 'find_device')
    def test_discover_continues_on_error(self, mock_find, allocator):
        mock_find.side_effect = [
            ValidationError("invalid"),
            [{"bdf": "0000:3b:00.1", "vendor_id": 0x19e5,
              "device_id": 0x1821, "numa_node": 0}],
            ValidationError("invalid"),
            ValidationError("invalid"),
        ]

        results = allocator.discover_hi1822_devices()

        assert len(results) == 1
        assert results[0]['device_id'] == 0x1821


# ========== 缓存去重测试 ==========

class TestUpdateDiscoveredCache:

    def test_cache_dedup_by_bdf(self, allocator):
        allocator._discovered_devices = [
            {"bdf": "0000:3b:00.0", "vendor_id": 0x19e5, "device_id": 0x1822}
        ]

        new_devices = [
            {"bdf": "0000:3b:00.0", "vendor_id": 0x19e5, "device_id": 0x1822},
            {"bdf": "0000:3b:00.1", "vendor_id": 0x19e5, "device_id": 0x1821},
        ]

        allocator._update_discovered_cache(new_devices)

        assert len(allocator._discovered_devices) == 2
        bdfs = [d['bdf'] for d in allocator._discovered_devices]
        assert "0000:3b:00.0" in bdfs
        assert "0000:3b:00.1" in bdfs


# ========== 设备类型推断测试 ==========

class TestInferDeviceType:

    def test_net_pf_device_id(self):
        dev_info = {"vendor_id": 0x19e5, "device_id": 0x0222}
        assert DeviceManagerAllocator._infer_device_type(dev_info) == DeviceTypeConfig.DEVICE_TYPE_NET_PF

    def test_net_vf_device_id(self):
        dev_info = {"vendor_id": 0x19e5, "device_id": 0x375f}
        assert DeviceManagerAllocator._infer_device_type(dev_info) == DeviceTypeConfig.DEVICE_TYPE_NET_VF

    def test_unknown_device_id(self):
        dev_info = {"vendor_id": 0x19e5, "device_id": 0x9999}
        assert DeviceManagerAllocator._infer_device_type(dev_info) == DeviceTypeConfig.DEVICE_TYPE_PCI


# ========== 数据库 CRUD 集成测试 ==========

class TestDeviceAllocationCRUD:
    """使用 mock 的 SQLAlchemy session 测试数据库 CRUD 操作"""

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_allocate_pf_device(self, mock_db, allocator):
        mock_device = MagicMock()
        mock_device.bdf = "0000:3b:00.0"
        mock_device.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
        mock_device.device_type = DeviceTypeConfig.DEVICE_TYPE_NET_PF

        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_device]
        mock_db.session.query.return_value = mock_query

        mock_db.session.query = MagicMock(return_value=mock_query)
        DeviceAllocation.query = mock_query

        req = DeviceAllocReq(vm_id="test-vm-1", pf_num=1, vf_num=0)
        result = allocator.allocate(req)

        assert result.success is True
        assert "0000:3b:00.0" in result.device_list

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_release_device(self, mock_db, allocator):
        mock_device = MagicMock()
        mock_device.bdf = "0000:3b:00.0"
        mock_device.status = DeviceAllocation.DEVICE_STATUS_ALLOCATED
        mock_device.allocated_vm_id = "test-vm-1"

        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.all.return_value = [mock_device]
        DeviceAllocation.query = mock_query

        req = DeviceReleaseReq(vm_id="test-vm-1")
        result = allocator.release(req)

        assert result.success is True
        assert mock_device.status == DeviceAllocation.DEVICE_STATUS_AVAILABLE
        assert mock_device.allocated_vm_id is None

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_release_no_allocated_devices(self, mock_db, allocator):
        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.all.return_value = []
        DeviceAllocation.query = mock_query

        req = DeviceReleaseReq(vm_id="nonexistent-vm")
        result = allocator.release(req)

        assert result.success is True

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_allocate_insufficient_devices(self, mock_db, allocator):
        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.with_for_update.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        DeviceAllocation.query = mock_query

        req = DeviceAllocReq(vm_id="test-vm-1", pf_num=2, vf_num=0)
        result = allocator.allocate(req)

        assert result.success is False
        assert len(result.device_list) == 0

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_get_available_devices(self, mock_db, allocator):
        mock_device = MagicMock()
        mock_device.to_dict.return_value = {
            "bdf": "0000:3b:00.0",
            "status": "available",
            "device_type": DeviceTypeConfig.DEVICE_TYPE_NET_PF
        }

        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.all.return_value = [mock_device]
        DeviceAllocation.query = mock_query

        result = allocator.get_available_devices(DeviceTypeConfig.DEVICE_TYPE_NET_PF)

        assert len(result) == 1
        assert result[0]['bdf'] == "0000:3b:00.0"

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_get_allocated_devices_with_vm_id(self, mock_db, allocator):
        mock_device = MagicMock()
        mock_device.to_dict.return_value = {
            "bdf": "0000:3b:00.0",
            "status": "allocated",
            "allocated_vm_id": "test-vm-1"
        }

        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.all.return_value = [mock_device]
        DeviceAllocation.query = mock_query

        result = allocator.get_allocated_devices(vm_id="test-vm-1")

        assert len(result) == 1
        assert result[0]['allocated_vm_id'] == "test-vm-1"

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_get_all_devices(self, mock_db, allocator):
        mock_device1 = MagicMock()
        mock_device1.to_dict.return_value = {"bdf": "0000:3b:00.0"}
        mock_device2 = MagicMock()
        mock_device2.to_dict.return_value = {"bdf": "0000:3b:00.1"}

        mock_query = MagicMock()
        mock_query.all.return_value = [mock_device1, mock_device2]
        DeviceAllocation.query = mock_query

        result = allocator.get_all_devices()

        assert len(result) == 2


# ========== 数据库同步测试 ==========

class TestSyncDiscoveredToDb:

    @patch.object(DeviceManagerAllocator, '_insert_device_record')
    @patch.object(DeviceManagerAllocator, '_update_device_record')
    @patch('virtcca_deploy.services.resource_allocator.db.session')
    def test_sync_inserts_new_devices(self, mock_session, mock_update, mock_insert, allocator):
        mock_query = MagicMock()
        mock_query.with_entities.return_value = mock_query
        mock_query.all.return_value = []
        DeviceAllocation.query = mock_query

        discovered = [
            {"bdf": "0000:3b:00.0", "vendor_id": 0x19e5, "device_id": 0x1822, "numa_node": 0},
            {"bdf": "0000:3b:00.1", "vendor_id": 0x19e5, "device_id": 0x1821, "numa_node": 0},
        ]

        allocator.sync_discovered_to_db(discovered)

        assert mock_insert.call_count == 2
        mock_session.commit.assert_called_once()

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_sync_updates_existing_devices(self, mock_db, allocator):
        mock_existing = MagicMock()
        mock_existing.bdf = "0000:3b:00.0"

        mock_query = MagicMock()
        mock_query.with_entities.return_value = mock_query
        mock_query.all.return_value = [mock_existing]
        mock_query.filter_by.return_value = mock_query
        mock_query.first.return_value = mock_existing
        DeviceAllocation.query = mock_query

        discovered = [
            {"bdf": "0000:3b:00.0", "vendor_id": 0x19e5, "device_id": 0x1822, "numa_node": 1},
        ]

        allocator.sync_discovered_to_db(discovered)

        mock_db.session.add.assert_not_called()
        mock_db.session.commit.assert_called_once()

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_sync_empty_discovered_list(self, mock_db, allocator):
        allocator.sync_discovered_to_db([])

        mock_db.session.commit.assert_not_called()

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_sync_rollback_on_error(self, mock_db, allocator):
        mock_query = MagicMock()
        mock_query.with_entities.return_value = mock_query
        mock_query.all.side_effect = Exception("db error")
        DeviceAllocation.query = mock_query

        allocator.sync_discovered_to_db([{"bdf": "x", "vendor_id": 1, "device_id": 2}])

        mock_db.session.rollback.assert_called_once()


# ========== SR-IOV VF 设置测试 ==========

class TestSetupSriovVfValidation:

    def test_invalid_vf_num_negative(self, allocator):
        result = allocator.setup_sriov_vf("enp59s0", -1)
        assert result.success is False
        assert "Invalid vf_num" in result.message

    def test_invalid_vf_num_string(self, allocator):
        result = allocator.setup_sriov_vf("enp59s0", "abc")
        assert result.success is False
        assert "Invalid vf_num" in result.message

    def test_invalid_vf_num_float(self, allocator):
        result = allocator.setup_sriov_vf("enp59s0", 2.5)
        assert result.success is False
        assert "Invalid vf_num" in result.message

    @patch('os.path.isdir')
    def test_net_device_not_exist(self, mock_isdir, allocator):
        mock_isdir.return_value = False
        result = allocator.setup_sriov_vf("nonexistent0", 4)
        assert result.success is False
        assert "does not exist" in result.message

    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_device_no_sriov_support(self, mock_isdir, mock_exists, allocator):
        mock_isdir.return_value = True
        mock_exists.return_value = False
        result = allocator.setup_sriov_vf("enp59s0", 4)
        assert result.success is False
        assert "does not support SR-IOV" in result.message


class TestSetupSriovVfMaxVfs:

    @patch.object(DeviceManagerAllocator, '_find_allocated_vf_under_pf', return_value=None)
    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_vf_num_exceeds_max(self, mock_isdir, mock_exists, mock_find_pf, mock_find_vf, allocator):
        mock_isdir.return_value = True

        def exists_side_effect(path):
            if path.endswith("sriov_numvfs"):
                return True
            if path.endswith("sriov_totalvfs"):
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
        mock_find_pf.return_value = mock_pf_record

        with patch('builtins.open', mock_open(read_data="8")):
            result = allocator.setup_sriov_vf("enp59s0", 16)

        assert result.success is False
        assert "exceeds maximum" in result.message

    @patch.object(DeviceManagerAllocator, '_find_allocated_vf_under_pf', return_value=None)
    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_vf_num_within_max(self, mock_isdir, mock_exists, mock_find_pf, mock_find_vf, allocator):
        mock_isdir.return_value = True

        def exists_side_effect(path):
            if path.endswith("sriov_numvfs"):
                return True
            if path.endswith("sriov_totalvfs"):
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
        mock_find_pf.return_value = mock_pf_record

        file_contents = {"sriov_totalvfs": "32", "sriov_numvfs": "4"}
        open_mock = MagicMock()

        def open_side_effect(path, mode='r'):
            for key, content in file_contents.items():
                if path.endswith(key):
                    return mock_open(read_data=content).return_value
            if mode == 'w':
                return mock_open().return_value
            raise FileNotFoundError(path)

        open_mock.side_effect = open_side_effect

        with patch('builtins.open', open_mock):
            with patch.object(allocator, '_update_pf_status_after_sriov'):
                result = allocator.setup_sriov_vf("enp59s0", 4)

        assert result.success is True


class TestSetupSriovVfWrite:

    @patch.object(DeviceManagerAllocator, '_find_allocated_vf_under_pf', return_value=None)
    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_write_permission_denied(self, mock_isdir, mock_exists, mock_find_pf, mock_find_vf, allocator):
        mock_isdir.return_value = True

        def exists_side_effect(path):
            if path.endswith("sriov_numvfs"):
                return True
            if path.endswith("sriov_totalvfs"):
                return False
            return False

        mock_exists.side_effect = exists_side_effect

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
        mock_find_pf.return_value = mock_pf_record

        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            result = allocator.setup_sriov_vf("enp59s0", 4)

        assert result.success is False
        assert "Permission denied" in result.message

    @patch.object(DeviceManagerAllocator, '_find_allocated_vf_under_pf', return_value=None)
    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_write_os_error(self, mock_isdir, mock_exists, mock_find_pf, mock_find_vf, allocator):
        mock_isdir.return_value = True

        def exists_side_effect(path):
            if path.endswith("sriov_numvfs"):
                return True
            if path.endswith("sriov_totalvfs"):
                return False
            return False

        mock_exists.side_effect = exists_side_effect

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
        mock_find_pf.return_value = mock_pf_record

        with patch('builtins.open', side_effect=OSError("I/O error")):
            result = allocator.setup_sriov_vf("enp59s0", 4)

        assert result.success is False
        assert "Failed to write sriov_numvfs" in result.message


class TestSetupSriovVfVerify:

    @patch.object(DeviceManagerAllocator, '_find_allocated_vf_under_pf', return_value=None)
    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_verify_count_mismatch(self, mock_isdir, mock_exists, mock_find_pf, mock_find_vf, allocator):
        mock_isdir.return_value = True

        def exists_side_effect(path):
            if path.endswith("sriov_numvfs"):
                return True
            if path.endswith("sriov_totalvfs"):
                return False
            return False

        mock_exists.side_effect = exists_side_effect

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
        mock_find_pf.return_value = mock_pf_record

        open_mock = MagicMock()

        def open_side_effect(path, mode='r'):
            if mode == 'w':
                return mock_open().return_value
            return mock_open(read_data="0").return_value

        open_mock.side_effect = open_side_effect

        with patch('builtins.open', open_mock):
            result = allocator.setup_sriov_vf("enp59s0", 4)

        assert result.success is False
        assert "verification failed" in result.message


class TestSetupSriovVfSuccess:

    @patch.object(DeviceManagerAllocator, '_find_allocated_vf_under_pf', return_value=None)
    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_full_success_flow(self, mock_isdir, mock_exists, mock_find_pf, mock_find_vf, allocator):
        mock_isdir.return_value = True

        def exists_side_effect(path):
            if path.endswith("sriov_numvfs"):
                return True
            if path.endswith("sriov_totalvfs"):
                return False
            return False

        mock_exists.side_effect = exists_side_effect

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
        mock_find_pf.return_value = mock_pf_record

        open_mock = MagicMock()
        write_handle = MagicMock()

        def open_side_effect(path, mode='r'):
            if mode == 'w':
                return write_handle
            return mock_open(read_data="4").return_value

        open_mock.side_effect = open_side_effect

        with patch('builtins.open', open_mock):
            with patch.object(allocator, '_update_pf_status_after_sriov') as mock_update:
                result = allocator.setup_sriov_vf("enp59s0", 4)

        assert result.success is True
        assert result.device_name == "enp59s0"
        assert result.vf_num == 4
        mock_update.assert_called_once_with("enp59s0")


class TestSetupSriovVfAllocatedPf:

    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_pf_allocated_to_vm(self, mock_isdir, mock_exists, mock_find_pf, allocator):
        mock_isdir.return_value = True

        def exists_side_effect(path):
            if path.endswith("sriov_numvfs"):
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_ALLOCATED
        mock_pf_record.allocated_vm_id = "compute01-1"
        mock_find_pf.return_value = mock_pf_record

        result = allocator.setup_sriov_vf("enp59s0", 4)

        assert result.success is False
        assert "allocated to VM" in result.message
        assert "compute01-1" in result.message


class TestSetupSriovVfAllocatedVf:

    @patch.object(DeviceManagerAllocator, '_find_allocated_vf_under_pf')
    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_vf_allocated_under_pf(self, mock_isdir, mock_exists, mock_find_pf, mock_find_vf, allocator):
        mock_isdir.return_value = True

        def exists_side_effect(path):
            if path.endswith("sriov_numvfs"):
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_AVAILABLE
        mock_find_pf.return_value = mock_pf_record

        mock_vf_record = MagicMock()
        mock_vf_record.bdf = "0000:3b:00.1"
        mock_vf_record.allocated_vm_id = "compute01-2"
        mock_find_vf.return_value = mock_vf_record

        result = allocator.setup_sriov_vf("enp59s0", 4)

        assert result.success is False
        assert "has allocated VF" in result.message
        assert "0000:3b:00.1" in result.message
        assert "compute01-2" in result.message


class TestFindAllocatedVfUnderPf:

    @patch('virtcca_deploy.services.resource_allocator.DeviceAllocation')
    def test_found_allocated_vf(self, mock_allocation, allocator):
        mock_vf_record = MagicMock()
        mock_vf_record.bdf = "0000:3b:00.1"
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_vf_record]
        mock_allocation.query = mock_query

        result = allocator._find_allocated_vf_under_pf("0000:3b:00.0")

        assert result is mock_vf_record

    @patch('virtcca_deploy.services.resource_allocator.DeviceAllocation')
    def test_no_allocated_vf(self, mock_allocation, allocator):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_allocation.query = mock_query

        result = allocator._find_allocated_vf_under_pf("0000:3b:00.0")

        assert result is None


class TestFindPfRecordByNetDevice:

    @patch('virtcca_deploy.services.resource_allocator.DeviceAllocation')
    def test_found_pf_record(self, mock_allocation, allocator):
        mock_pf_record = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_pf_record
        mock_allocation.query = mock_query

        result = allocator._find_pf_record_by_net_device("enp59s0")

        assert result is mock_pf_record

    @patch('virtcca_deploy.services.resource_allocator.DeviceAllocation')
    def test_no_matching_pf_in_db(self, mock_allocation, allocator):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_allocation.query = mock_query

        result = allocator._find_pf_record_by_net_device("enp59s0")
        assert result is None


class TestUpdatePfStatusAfterSriov:

    @patch('virtcca_deploy.services.resource_allocator.db')
    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    def test_update_status_to_sriov_used(self, mock_find, mock_db, allocator):
        mock_record = MagicMock()
        mock_record.bdf = "0000:3b:00.0"
        mock_find.return_value = mock_record

        allocator._update_pf_status_after_sriov("enp59s0")

        assert mock_record.status == DeviceAllocation.DEVICE_STATUS_SRIOV_USED
        assert mock_record.device_name == "enp59s0"
        mock_db.session.commit.assert_called_once()

    @patch('virtcca_deploy.services.resource_allocator.db')
    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    def test_update_no_record_found(self, mock_find, mock_db, allocator):
        mock_find.return_value = None

        allocator._update_pf_status_after_sriov("enp59s0")

        mock_db.session.commit.assert_not_called()

    @patch('virtcca_deploy.services.resource_allocator.db')
    @patch.object(DeviceManagerAllocator, '_find_pf_record_by_net_device')
    def test_update_db_commit_failure(self, mock_find, mock_db, allocator):
        mock_record = MagicMock()
        mock_find.return_value = mock_record
        mock_db.session.commit.side_effect = Exception("db error")

        allocator._update_pf_status_after_sriov("enp59s0")

        mock_db.session.rollback.assert_called_once()


class TestVerifySriovNumvfs:

    @patch('builtins.open', mock_open(read_data="4"))
    def test_verify_match(self, allocator):
        result = allocator._verify_sriov_numvfs("enp59s0", 4)
        assert result is True

    @patch('builtins.open', mock_open(read_data="0"))
    def test_verify_mismatch(self, allocator):
        result = allocator._verify_sriov_numvfs("enp59s0", 4)
        assert result is False

    @patch('builtins.open', side_effect=ValueError("bad value"))
    def test_verify_read_error(self, mock_open_func, allocator):
        result = allocator._verify_sriov_numvfs("enp59s0", 4)
        assert result is False

    @patch('builtins.open', side_effect=OSError("read error"))
    def test_verify_os_error(self, mock_open_func, allocator):
        result = allocator._verify_sriov_numvfs("enp59s0", 4)
        assert result is False


# ========== VF 自动销毁与 PF 恢复测试 ==========

class TestTryReclaimSriovPf:

    @patch.object(DeviceManagerAllocator, '_destroy_vfs_and_restore_pf')
    @patch.object(DeviceManagerAllocator, '_find_allocated_vf_under_pf', return_value=None)
    @patch('virtcca_deploy.services.resource_allocator.DeviceAllocation')
    def test_all_vfs_released_triggers_destroy(self, mock_allocation, mock_find_vf, mock_destroy, allocator):
        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.device_type = DeviceTypeConfig.DEVICE_TYPE_NET_PF
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_SRIOV_USED

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_pf_record
        mock_allocation.query = mock_query

        allocator._try_reclaim_sriov_pf(["0000:3b:00.1"])

        mock_destroy.assert_called_once_with(mock_pf_record)

    @patch.object(DeviceManagerAllocator, '_destroy_vfs_and_restore_pf')
    @patch.object(DeviceManagerAllocator, '_find_allocated_vf_under_pf')
    @patch('virtcca_deploy.services.resource_allocator.DeviceAllocation')
    def test_remaining_allocated_vf_skips_destroy(self, mock_allocation, mock_find_vf, mock_destroy, allocator):
        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.device_type = DeviceTypeConfig.DEVICE_TYPE_NET_PF
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_SRIOV_USED

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_pf_record
        mock_allocation.query = mock_query

        remaining_vf = MagicMock()
        mock_find_vf.return_value = remaining_vf

        allocator._try_reclaim_sriov_pf(["0000:3b:00.1"])

        mock_destroy.assert_not_called()

    @patch.object(DeviceManagerAllocator, '_destroy_vfs_and_restore_pf')
    @patch('virtcca_deploy.services.resource_allocator.DeviceAllocation')
    def test_no_sriov_used_pf_skips(self, mock_allocation, mock_destroy, allocator):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_allocation.query = mock_query

        allocator._try_reclaim_sriov_pf(["0000:3b:00.1"])

        mock_destroy.assert_not_called()

    @patch.object(DeviceManagerAllocator, '_destroy_vfs_and_restore_pf')
    @patch.object(DeviceManagerAllocator, '_find_allocated_vf_under_pf', return_value=None)
    @patch('virtcca_deploy.services.resource_allocator.DeviceAllocation')
    def test_same_pf_deduplication(self, mock_allocation, mock_find_vf, mock_destroy, allocator):
        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.device_type = DeviceTypeConfig.DEVICE_TYPE_NET_PF
        mock_pf_record.status = DeviceAllocation.DEVICE_STATUS_SRIOV_USED

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_pf_record
        mock_allocation.query = mock_query

        allocator._try_reclaim_sriov_pf(["0000:3b:00.1", "0000:3b:00.2"])

        mock_destroy.assert_called_once_with(mock_pf_record)


class TestDestroyVfsAndRestorePf:

    @patch('builtins.open')
    @patch.object(DeviceManagerAllocator, '_verify_sriov_numvfs')
    @patch.object(DeviceManagerAllocator, '_restore_pf_after_vf_destroy')
    def test_successful_destroy(self, mock_restore_pf, mock_verify_sriov, mock_open, allocator):
        """测试成功销毁 VF 并恢复 PF"""
        # 创建 PF 记录
        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.device_name = "enp59s0"

        # 创建设备分配器实例
        allocator = DeviceManagerAllocator()
        
        # 执行被测方法
        allocator._destroy_vfs_and_restore_pf(mock_pf_record)
        
        # 验证 _restore_pf_after_vf_destroy 被调用
        mock_restore_pf.assert_called_once_with(mock_pf_record)
        
        # 验证 _verify_sriov_numvfs 被调用
        mock_verify_sriov.assert_called_once_with("enp59s0", 0)

    @patch('builtins.open', side_effect=PermissionError("denied"))
    @patch.object(DeviceManagerAllocator, '_restore_pf_after_vf_destroy')
    def test_permission_denied(self, mock_open, allocator):
        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.device_name = "enp59s0"

        allocator._destroy_vfs_and_restore_pf(mock_pf_record)

        allocator._restore_pf_after_vf_destroy.assert_not_called()

    @patch('builtins.open', side_effect=OSError("I/O error"))
    @patch.object(DeviceManagerAllocator, '_restore_pf_after_vf_destroy')
    def test_os_error_on_write(self, mock_open, allocator):
        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.device_name = "enp59s0"

        allocator._destroy_vfs_and_restore_pf(mock_pf_record)

        allocator._restore_pf_after_vf_destroy.assert_not_called()

    @patch('builtins.open', mock_open())
    @patch.object(DeviceManagerAllocator, '_restore_pf_after_vf_destroy')
    @patch.object(DeviceManagerAllocator, '_verify_sriov_numvfs', return_value=False)
    def test_verify_failure_skips_restore(self, mock_open, allocator):
        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.device_name = "enp59s0"

        allocator._destroy_vfs_and_restore_pf(mock_pf_record)

        allocator._restore_pf_after_vf_destroy.assert_not_called()

    @patch.object(DeviceManagerAllocator, '_restore_pf_after_vf_destroy')
    def test_no_device_name_skips(self, allocator):
        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.device_name = None

        allocator._destroy_vfs_and_restore_pf(mock_pf_record)

        allocator._restore_pf_after_vf_destroy.assert_not_called()

    @patch.object(DeviceManagerAllocator, '_restore_pf_after_vf_destroy')
    def test_empty_device_name_skips(self, allocator):
        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"
        mock_pf_record.device_name = ""

        allocator._destroy_vfs_and_restore_pf(mock_pf_record)

        allocator._restore_pf_after_vf_destroy.assert_not_called()


class TestRestorePfAfterVfDestroy:

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_restore_pf_and_delete_vf_records(self, mock_db, allocator):
        mock_vf1 = MagicMock()
        mock_vf1.bdf = "0000:3b:00.1"
        mock_vf2 = MagicMock()
        mock_vf2.bdf = "0000:3b:00.2"

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_vf1, mock_vf2]

        DeviceAllocation.query = mock_query

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"

        allocator._restore_pf_after_vf_destroy(mock_pf_record)

        assert mock_pf_record.status == DeviceAllocation.DEVICE_STATUS_AVAILABLE
        mock_db.session.delete.assert_any_call(mock_vf1)
        mock_db.session.delete.assert_any_call(mock_vf2)
        assert mock_db.session.delete.call_count == 2
        mock_db.session.commit.assert_called_once()

    @patch('virtcca_deploy.services.resource_allocator.db')
    def test_restore_pf_no_vf_records(self, mock_db, allocator):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        DeviceAllocation.query = mock_query

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"

        allocator._restore_pf_after_vf_destroy(mock_pf_record)

        assert mock_pf_record.status == DeviceAllocation.DEVICE_STATUS_AVAILABLE
        mock_db.session.delete.assert_not_called()
        mock_db.session.commit.assert_called_once()

    @patch('virtcca_deploy.services.resource_allocator.db')
    @patch('virtcca_deploy.services.resource_allocator.DeviceAllocation')
    def test_restore_pf_db_error_rollback(self, mock_allocation, mock_db, allocator):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_allocation.query = mock_query

        mock_db.session.commit.side_effect = Exception("db error")

        mock_pf_record = MagicMock()
        mock_pf_record.bdf = "0000:3b:00.0"

        allocator._restore_pf_after_vf_destroy(mock_pf_record)

        mock_db.session.rollback.assert_called_once()


class TestReleaseWithVfAutoDestroy:

    @patch('virtcca_deploy.services.resource_allocator.db')
    @patch.object(DeviceManagerAllocator, '_try_reclaim_sriov_pf')
    def test_release_vf_triggers_reclaim_check(self, mock_try_reclaim, mock_db, allocator):
        mock_vf_device = MagicMock()
        mock_vf_device.bdf = "0000:3b:00.1"
        mock_vf_device.device_type = DeviceTypeConfig.DEVICE_TYPE_NET_VF
        mock_vf_device.status = DeviceAllocation.DEVICE_STATUS_ALLOCATED
        mock_vf_device.allocated_vm_id = "test-vm-1"

        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.all.return_value = [mock_vf_device]
        DeviceAllocation.query = mock_query

        req = DeviceReleaseReq(vm_id="test-vm-1")
        result = allocator.release(req)

        assert result.success is True
        assert mock_vf_device.status == DeviceAllocation.DEVICE_STATUS_AVAILABLE
        assert mock_vf_device.allocated_vm_id is None
        mock_try_reclaim.assert_called_once_with(["0000:3b:00.1"])

    @patch('virtcca_deploy.services.resource_allocator.db')
    @patch.object(DeviceManagerAllocator, '_try_reclaim_sriov_pf')
    def test_release_pf_only_no_reclaim(self, mock_allocation, mock_db, allocator):
        mock_pf_device = MagicMock()
        mock_pf_device.bdf = "0000:3b:00.0"
        mock_pf_device.device_type = DeviceTypeConfig.DEVICE_TYPE_NET_PF
        mock_pf_device.status = DeviceAllocation.DEVICE_STATUS_ALLOCATED
        mock_pf_device.allocated_vm_id = "test-vm-1"

        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.all.return_value = [mock_pf_device]
        DeviceAllocation.query = mock_query

        req = DeviceReleaseReq(vm_id="test-vm-1")
        result = allocator.release(req)

        assert result.success is True
        allocator._try_reclaim_sriov_pf.assert_not_called()

    @patch('virtcca_deploy.services.resource_allocator.db')
    @patch.object(DeviceManagerAllocator, '_try_reclaim_sriov_pf')
    def test_release_mixed_pf_and_vf(self, mock_allocation, mock_db, allocator):
        mock_pf_device = MagicMock()
        mock_pf_device.bdf = "0000:3b:00.0"
        mock_pf_device.device_type = DeviceTypeConfig.DEVICE_TYPE_NET_PF
        mock_pf_device.status = DeviceAllocation.DEVICE_STATUS_ALLOCATED
        mock_pf_device.allocated_vm_id = "test-vm-1"

        mock_vf_device = MagicMock()
        mock_vf_device.bdf = "0000:3b:00.1"
        mock_vf_device.device_type = DeviceTypeConfig.DEVICE_TYPE_NET_VF
        mock_vf_device.status = DeviceAllocation.DEVICE_STATUS_ALLOCATED
        mock_vf_device.allocated_vm_id = "test-vm-1"

        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.all.return_value = [mock_pf_device, mock_vf_device]
        DeviceAllocation.query = mock_query

        req = DeviceReleaseReq(vm_id="test-vm-1")
        result = allocator.release(req)

        assert result.success is True
        allocator._try_reclaim_sriov_pf.assert_called_once_with(["0000:3b:00.1"])

    @patch('virtcca_deploy.services.resource_allocator.db')
    @patch.object(DeviceManagerAllocator, '_try_reclaim_sriov_pf')
    def test_release_multiple_vfs(self, mock_allocation, mock_db, allocator):
        mock_vf1 = MagicMock()
        mock_vf1.bdf = "0000:3b:00.1"
        mock_vf1.device_type = DeviceTypeConfig.DEVICE_TYPE_NET_VF
        mock_vf1.status = DeviceAllocation.DEVICE_STATUS_ALLOCATED
        mock_vf1.allocated_vm_id = "test-vm-1"

        mock_vf2 = MagicMock()
        mock_vf2.bdf = "0000:3b:00.2"
        mock_vf2.device_type = DeviceTypeConfig.DEVICE_TYPE_NET_VF
        mock_vf2.status = DeviceAllocation.DEVICE_STATUS_ALLOCATED
        mock_vf2.allocated_vm_id = "test-vm-1"

        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.all.return_value = [mock_vf1, mock_vf2]
        DeviceAllocation.query = mock_query

        req = DeviceReleaseReq(vm_id="test-vm-1")
        result = allocator.release(req)

        assert result.success is True
        allocator._try_reclaim_sriov_pf.assert_called_once_with(
            ["0000:3b:00.1", "0000:3b:00.2"]
        )
