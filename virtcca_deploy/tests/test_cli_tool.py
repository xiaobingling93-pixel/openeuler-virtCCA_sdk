#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""CLI 工具测试"""

import pytest
import os
import sys


class TestValidatePasswordComplexity:
    """密码复杂度校验测试（通过 CLI 路径）"""

    def test_strong_password(self):
        from virtcca_deploy.manager.auth.auth_service import AuthService
        valid, msg = AuthService.validate_password_complexity("MyStr0ng@Pass")
        assert valid is True
        assert msg == ""

    def test_short_password(self):
        from virtcca_deploy.manager.auth.auth_service import AuthService
        valid, msg = AuthService.validate_password_complexity("Ab1@")
        assert valid is False

    def test_no_special_char(self):
        from virtcca_deploy.manager.auth.auth_service import AuthService
        valid, msg = AuthService.validate_password_complexity("Abcdefg1")
        assert valid is False

    def test_no_uppercase(self):
        from virtcca_deploy.manager.auth.auth_service import AuthService
        valid, msg = AuthService.validate_password_complexity("abcdefg1@")
        assert valid is False

    def test_no_lowercase(self):
        from virtcca_deploy.manager.auth.auth_service import AuthService
        valid, msg = AuthService.validate_password_complexity("ABCDEFG1@")
        assert valid is False

    def test_no_digit(self):
        from virtcca_deploy.manager.auth.auth_service import AuthService
        valid, msg = AuthService.validate_password_complexity("Abcdefg@h")
        assert valid is False


class TestCliToolEntryPoints:
    """CLI 工具入口测试"""

    def test_cli_parser_set_password_interactive2(self):
        """CLI 应正确解析 set-password 命令（交互式模式）"""
        import sys
        from unittest.mock import patch, MagicMock
        from virtcca_deploy.manager.auth.cli_tool import main

        with patch.object(sys, 'argv', ['virtcca-deploy-tool', 'set-password']):
            # 完全模拟 interactive_set_password 函数及其内部调用
            with patch('virtcca_deploy.manager.auth.cli_tool.interactive_set_password') as mock_interactive:
                with patch('virtcca_deploy.manager.auth.cli_tool.input') as mock_input:
                    with patch('virtcca_deploy.manager.auth.cli_tool.getpass') as mock_getpass:
                        # 设置模拟的输入返回值
                        mock_input.return_value = 'Test@1234'  # 模拟第一次输入
                        mock_getpass.getpass.return_value = 'Test@1234'  # 模拟第二次输入（确认密码）
                        
                        mock_interactive.return_value = 0  # 成功退出码
                        
                        with patch('sys.exit') as mock_exit:
                            main()
                            
                            # 验证交互式函数被调用
                            mock_interactive.assert_called_once()
                            # 验证正确退出
                            mock_exit.assert_called_once_with(0)

    def test_cli_set_password_euid_nonzero(self):
        """非 root 用户运行时应拒绝"""
        from unittest.mock import patch
        from virtcca_deploy.manager.auth.cli_tool import set_root_password

        with patch('os.geteuid', return_value=1000):
            result = set_root_password("Test@1234")
            assert result == 1

    def test_set_password_weak_rejected(self, app):
        """弱密码应被拒绝"""
        from virtcca_deploy.manager.auth.auth_service import AuthService

        with app.app_context():
            success, msg = AuthService.set_root_password("weak")
            assert success is False

    def test_set_password_no_uppercase_rejected(self, app):
        """缺少大写字母应被拒绝"""
        from virtcca_deploy.manager.auth.auth_service import AuthService

        with app.app_context():
            success, msg = AuthService.set_root_password("password@123")
            assert success is False

    def test_set_password_resets_lock(self, app):
        """设置密码应清除锁定状态"""
        from datetime import datetime, timedelta, timezone
        from virtcca_deploy.manager.auth.auth_service import AuthService
        from virtcca_deploy.manager.auth.auth_models import User
        from virtcca_deploy.services.db_service import db

        with app.app_context():
            user = User.query.filter_by(username="root").first()
            user.failed_login_count = 5
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
            db.session.commit()

            success, msg = AuthService.set_root_password("NewPass@567")
            assert success is True

            db.session.refresh(user)
            assert user.failed_login_count == 0
            assert user.locked_until is None


class TestIsRootPasswordSet:
    """检查密码是否已设置"""

    def test_not_set_initially(self, app):
        from virtcca_deploy.manager.auth.auth_service import AuthService

        with app.app_context():
            assert AuthService.is_root_password_set() is False

    def test_set_returns_true(self, app):
        from virtcca_deploy.manager.auth.auth_service import AuthService

        with app.app_context():
            AuthService.set_root_password("Strong@Pass1")
            assert AuthService.is_root_password_set() is True


class TestInitRootUser:
    """初始化 root 用户"""

    def test_init_root_user_creates_user(self, app):
        """应创建 root 用户"""
        from virtcca_deploy.manager.auth.auth_models import User
        from virtcca_deploy.manager.auth.auth_service import AuthService
        from virtcca_deploy.services.db_service import db

        with app.app_context():
            # 删除已有的 root 用户
            User.query.filter_by(username="root").delete()
            db.session.commit()

            AuthService.init_root_user()
            user = User.query.filter_by(username="root").first()
            assert user is not None
            assert user.password_hash == ''

    def test_init_root_user_idempotent(self, app):
        """多次调用不应创建重复用户"""
        from virtcca_deploy.manager.auth.auth_models import User
        from virtcca_deploy.manager.auth.auth_service import AuthService

        with app.app_context():
            AuthService.init_root_user()
            AuthService.init_root_user()
            count = User.query.filter_by(username="root").count()
            assert count == 1


class TestInitAuth:
    """init_auth 初始化函数测试"""

    def test_init_auth_registers_blueprint(self, app):
        """init_auth 应注册 auth Blueprint 并注入配置"""
        import flask
        from virtcca_deploy.services.db_service import db
        from virtcca_deploy.manager.auth import init_auth

        class FakeConfig:
            jwt_secret_key = 'test-init-secret'
            jwt_expiration_minutes = 45
            max_login_attempts = 3
            lockout_duration_minutes = 10

        new_app = flask.Flask(__name__)
        new_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        new_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(new_app)

        with new_app.app_context():
            init_auth(new_app, FakeConfig())
            assert 'auth' in new_app.blueprints
            assert new_app.config['JWT_SECRET_KEY'] == 'test-init-secret'
            assert new_app.config['JWT_EXPIRATION_MINUTES'] == 45


