#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from gevent import monkey
monkey.patch_all()

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, mock_open

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(PROJECT_ROOT, 'src')
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from virtcca_deploy.common.constants import DeviceTypeConfig
from virtcca_deploy.common.data_model import SriovVfSetupResp
from virtcca_deploy.services import virt_service


class TestEnsureSriovVfResources:

    @pytest.fixture
    def mock_allocator(self):
        return MagicMock()

    def test_sufficient_vfs_no_provisioning(self, mock_allocator):
        mock_allocator.get_available_devices.return_value = [
            {"bdf": "0000:3b:01.0", "device_name": "enp59s1"},
            {"bdf": "0000:3b:01.1", "device_name": "enp59s2"},
        ]

        result = virt_service._ensure_sriov_vf_resources(mock_allocator, 2, 1)

        assert result is None
        mock_allocator.get_available_devices.assert_called_once_with(
            DeviceTypeConfig.DEVICE_TYPE_NET_VF
        )
        mock_allocator.setup_sriov_vf.assert_not_called()

    def test_no_vfs_no_pfs_returns_error(self, mock_allocator):
        mock_allocator.get_available_devices.side_effect = [
            [],
            [],
        ]

        result = virt_service._ensure_sriov_vf_resources(mock_allocator, 1, 1)

        assert result is not None
        assert "Insufficient SR-IOV VF/PF resources" in result
        assert "no available PF(s)" in result

    def test_provision_vfs_from_single_pf(self, mock_allocator):
        mock_allocator.get_available_devices.side_effect = [
            [],
            [{"bdf": "0000:3b:00.0", "device_name": "enp59s0"}],
            [{"bdf": "0000:3b:01.0"}, {"bdf": "0000:3b:01.1"}],
        ]
        mock_allocator.setup_sriov_vf.return_value = SriovVfSetupResp(
            success=True, device_name="enp59s0", vf_num=2
        )
        mock_allocator.find_device.return_value = []
        mock_allocator.sync_discovered_to_db.return_value = None

        with patch.object(virt_service, '_get_pf_max_vf_capacity', return_value=8):
            result = virt_service._ensure_sriov_vf_resources(mock_allocator, 2, 1)

        assert result is None
        mock_allocator.setup_sriov_vf.assert_called_once_with("enp59s0", 2)
        mock_allocator.find_device.assert_called_once()
        mock_allocator.sync_discovered_to_db.assert_called_once()

    def test_provision_vfs_from_multiple_pfs(self, mock_allocator):
        mock_allocator.get_available_devices.side_effect = [
            [],
            [
                {"bdf": "0000:3b:00.0", "device_name": "enp59s0"},
                {"bdf": "0000:3c:00.0", "device_name": "enp60s0"},
            ],
            [{"bdf": f"0000:3b:01.{i}"} for i in range(4)] +
            [{"bdf": f"0000:3c:01.{i}"} for i in range(4)],
        ]
        mock_allocator.setup_sriov_vf.side_effect = [
            SriovVfSetupResp(success=True, device_name="enp59s0", vf_num=4),
            SriovVfSetupResp(success=True, device_name="enp60s0", vf_num=4),
        ]
        mock_allocator.find_device.return_value = []
        mock_allocator.sync_discovered_to_db.return_value = None

        with patch.object(virt_service, '_get_pf_max_vf_capacity', return_value=4):
            result = virt_service._ensure_sriov_vf_resources(mock_allocator, 4, 2)

        assert result is None
        assert mock_allocator.setup_sriov_vf.call_count == 2

    def test_pf_setup_failure_continues_to_next_pf(self, mock_allocator):
        mock_allocator.get_available_devices.side_effect = [
            [],
            [
                {"bdf": "0000:3b:00.0", "device_name": "enp59s0"},
                {"bdf": "0000:3c:00.0", "device_name": "enp60s0"},
            ],
            [{"bdf": f"0000:3c:01.{i}"} for i in range(2)],
        ]
        mock_allocator.setup_sriov_vf.side_effect = [
            SriovVfSetupResp(
                success=False, device_name="enp59s0", vf_num=2,
                message="Permission denied"
            ),
            SriovVfSetupResp(success=True, device_name="enp60s0", vf_num=2),
        ]
        mock_allocator.find_device.return_value = []
        mock_allocator.sync_discovered_to_db.return_value = None

        with patch.object(virt_service, '_get_pf_max_vf_capacity', return_value=8):
            result = virt_service._ensure_sriov_vf_resources(mock_allocator, 2, 1)

        assert result is None
        assert mock_allocator.setup_sriov_vf.call_count == 2

    def test_all_pfs_fail_returns_error(self, mock_allocator):
        mock_allocator.get_available_devices.side_effect = [
            [],
            [{"bdf": "0000:3b:00.0", "device_name": "enp59s0"}],
        ]
        mock_allocator.setup_sriov_vf.return_value = SriovVfSetupResp(
            success=False, device_name="enp59s0", vf_num=2,
            message="Permission denied"
        )

        with patch.object(virt_service, '_get_pf_max_vf_capacity', return_value=8):
            result = virt_service._ensure_sriov_vf_resources(mock_allocator, 2, 1)

        assert result is not None
        assert "Insufficient SR-IOV VF/PF resources" in result
        assert "still short 2 after provisioning" in result

    def test_pf_without_device_name_skipped(self, mock_allocator):
        mock_allocator.get_available_devices.side_effect = [
            [],
            [{"bdf": "0000:3b:00.0", "device_name": None}],
        ]

        result = virt_service._ensure_sriov_vf_resources(mock_allocator, 1, 1)

        assert result is not None
        assert "Insufficient SR-IOV VF/PF resources" in result
        mock_allocator.setup_sriov_vf.assert_not_called()

    def test_pf_zero_vf_capacity_skipped(self, mock_allocator):
        mock_allocator.get_available_devices.side_effect = [
            [],
            [{"bdf": "0000:3b:00.0", "device_name": "enp59s0"}],
        ]

        with patch.object(virt_service, '_get_pf_max_vf_capacity', return_value=0):
            result = virt_service._ensure_sriov_vf_resources(mock_allocator, 1, 1)

        assert result is not None
        assert "Insufficient SR-IOV VF/PF resources" in result
        mock_allocator.setup_sriov_vf.assert_not_called()

    def test_partial_vfs_available_reduces_shortage(self, mock_allocator):
        mock_allocator.get_available_devices.side_effect = [
            [{"bdf": "0000:3b:01.0"}],
            [{"bdf": "0000:3b:00.0", "device_name": "enp59s0"}],
            [{"bdf": "0000:3b:01.0"}, {"bdf": "0000:3b:01.1"}],
        ]
        mock_allocator.setup_sriov_vf.return_value = SriovVfSetupResp(
            success=True, device_name="enp59s0", vf_num=1
        )
        mock_allocator.find_device.return_value = []
        mock_allocator.sync_discovered_to_db.return_value = None

        with patch.object(virt_service, '_get_pf_max_vf_capacity', return_value=8):
            result = virt_service._ensure_sriov_vf_resources(mock_allocator, 2, 1)

        assert result is None
        mock_allocator.setup_sriov_vf.assert_called_once_with("enp59s0", 1)

    def test_recheck_after_provisioning_fails(self, mock_allocator):
        mock_allocator.get_available_devices.side_effect = [
            [],
            [{"bdf": "0000:3b:00.0", "device_name": "enp59s0"}],
            [],
        ]
        mock_allocator.setup_sriov_vf.return_value = SriovVfSetupResp(
            success=True, device_name="enp59s0", vf_num=2
        )
        mock_allocator.find_device.return_value = []
        mock_allocator.sync_discovered_to_db.return_value = None

        with patch.object(virt_service, '_get_pf_max_vf_capacity', return_value=8):
            result = virt_service._ensure_sriov_vf_resources(mock_allocator, 2, 1)

        assert result is not None
        assert "after provisioning" in result

    def test_multiple_vms_total_required_calculation(self, mock_allocator):
        mock_allocator.get_available_devices.side_effect = [
            [{"bdf": "0000:3b:01.0"}],
            [{"bdf": "0000:3b:00.0", "device_name": "enp59s0"}],
            [{"bdf": f"0000:3b:01.{i}"} for i in range(4)],
        ]
        mock_allocator.setup_sriov_vf.return_value = SriovVfSetupResp(
            success=True, device_name="enp59s0", vf_num=3
        )
        mock_allocator.find_device.return_value = []
        mock_allocator.sync_discovered_to_db.return_value = None

        with patch.object(virt_service, '_get_pf_max_vf_capacity', return_value=8):
            result = virt_service._ensure_sriov_vf_resources(mock_allocator, 2, 2)

        assert result is None
        mock_allocator.setup_sriov_vf.assert_called_once_with("enp59s0", 3)


class TestGetPfMaxVfCapacity:

    def test_read_success(self):
        with patch('builtins.open', mock_open(read_data="32")):
            result = virt_service._get_pf_max_vf_capacity("enp59s0")

        assert result == 32

    def test_file_not_found(self):
        with patch('builtins.open', side_effect=FileNotFoundError("not found")):
            result = virt_service._get_pf_max_vf_capacity("enp59s0")

        assert result == 0

    def test_invalid_value(self):
        with patch('builtins.open', mock_open(read_data="not_a_number")):
            result = virt_service._get_pf_max_vf_capacity("enp59s0")

        assert result == 0

    def test_os_error(self):
        with patch('builtins.open', side_effect=OSError("I/O error")):
            result = virt_service._get_pf_max_vf_capacity("enp59s0")

        assert result == 0


class TestDeployCvmSriovIntegration:

    @pytest.fixture
    def mock_config(self):
        cfg = MagicMock()
        cfg.device_allocator = MagicMock()
        return cfg

    @pytest.fixture
    def vm_spec(self):
        spec = MagicMock()
        spec.core_num = 4
        spec.memory = 8192
        spec.max_vm_num = 1
        spec.net_pf_num = 0
        spec.net_vf_num = 2
        return spec

    @pytest.fixture
    def deploy_spec(self, vm_spec):
        spec = MagicMock()
        spec.vm_spec = vm_spec
        spec.vm_id_list = ["cvm-test-1"]
        spec.vm_iface = {}
        return spec

    @patch('virtcca_deploy.services.virt_service.cvm_numa_check')
    @patch('virtcca_deploy.services.virt_service._deploy_single_vm')
    def test_deploy_cvm_with_vf_required(
        self, mock_deploy_single, mock_numa_check, deploy_spec, mock_config, app
    ):
        from virtcca_deploy.services.virt_service import VmDeploymentContext
        from virtcca_deploy.common.data_model import VmDeploySpec
        
        mock_numa_check.return_value = ([0], None)
        mock_ctx = VmDeploymentContext(
            cvm_name="cvm-test-1",
            vm_spec=VmDeploySpec(),
            host_numa_id=0,
            success=True
        )
        mock_deploy_single.return_value = mock_ctx
        mock_config.device_allocator.allocate.return_value = MagicMock(
            success=True, device_dict={}
        )

        with patch('virtcca_deploy.services.virt_service.cvm_device_alloc') as mock_device_alloc:
            mock_device_alloc.return_value = ([], None)
            with app.app_context():
                virt_service.deploy_cvm(deploy_spec, mock_config)

        mock_deploy_single.assert_called_once()

    @patch('virtcca_deploy.services.virt_service.cvm_numa_check')
    def test_deploy_cvm_returns_error_when_numa_insufficient(
        self, mock_numa_check, deploy_spec, mock_config
    ):
        mock_numa_check.return_value = (None, "Insufficient NUMA resources for CVM deployment")

        result_vms, err_msg = virt_service.deploy_cvm(deploy_spec, mock_config)

        assert result_vms == []
        assert "Insufficient NUMA resources" in err_msg

    @patch('virtcca_deploy.services.virt_service.cvm_numa_check')
    @patch('virtcca_deploy.services.virt_service._deploy_single_vm')
    def test_deploy_cvm_with_pf_required(
        self, mock_deploy_single, mock_numa_check, deploy_spec, mock_config, vm_spec, app
    ):
        from virtcca_deploy.services.virt_service import VmDeploymentContext
        from virtcca_deploy.common.data_model import VmDeploySpec
        
        vm_spec.net_pf_num = 1
        vm_spec.net_vf_num = 0
        mock_numa_check.return_value = ([0], None)
        mock_ctx = VmDeploymentContext(
            cvm_name="cvm-test-1",
            vm_spec=VmDeploySpec(),
            host_numa_id=0,
            success=True
        )
        mock_deploy_single.return_value = mock_ctx

        with patch('virtcca_deploy.services.virt_service.cvm_device_alloc') as mock_device_alloc:
            mock_device_alloc.return_value = (["0000:3b:00.0"], None)
            with app.app_context():
                virt_service.deploy_cvm(deploy_spec, mock_config)

        mock_deploy_single.assert_called_once()

    @patch('virtcca_deploy.services.virt_service.cvm_numa_check')
    @patch('virtcca_deploy.services.virt_service._deploy_single_vm')
    def test_deploy_cvm_with_no_device_required(
        self, mock_deploy_single, mock_numa_check, deploy_spec, mock_config, vm_spec, app
    ):
        from virtcca_deploy.services.virt_service import VmDeploymentContext
        from virtcca_deploy.common.data_model import VmDeploySpec
        
        vm_spec.net_pf_num = 0
        vm_spec.net_vf_num = 0
        mock_numa_check.return_value = ([0], None)
        mock_ctx = VmDeploymentContext(
            cvm_name="cvm-test-1",
            vm_spec=VmDeploySpec(),
            host_numa_id=0,
            success=True
        )
        mock_deploy_single.return_value = mock_ctx

        with patch('virtcca_deploy.services.virt_service.cvm_device_alloc') as mock_device_alloc:
            mock_device_alloc.return_value = ([], None)
            with app.app_context():
                virt_service.deploy_cvm(deploy_spec, mock_config)

        mock_deploy_single.assert_called_once()