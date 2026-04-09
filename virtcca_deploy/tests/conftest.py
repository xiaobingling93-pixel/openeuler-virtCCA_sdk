#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
from gevent import monkey
monkey.patch_all()

import os
import sys
import pytest
import tempfile
import logging

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SECRET_KEY = "test-secret-key-for-unit-testing-only"
VALID_PASSWORD = "Test@1234"
g_logger = logging.getLogger("virtcca_deploy_test")

class TestConfig:
    """测试专用的配置类，使用临时文件和固定密钥"""
    def __init__(self):
        self.ssl_cert = None
        self.vlan_pool_manager = None
        self._temp_dir = tempfile.mkdtemp(prefix="virtcca_test_")
        self.jwt_secret_key = None
        self.jwt_expiration_minutes = 30
        self.max_login_attempts = 5
        self.lockout_duration_minutes = 15
        self.logger = None

    def __del__(self):
        """析构函数，清理临时文件"""
        try:
            import shutil
            if os.path.exists(self._temp_dir):
                shutil.rmtree(self._temp_dir)
        except:
            pass
    
    def configure_log(self, log_name):
        """配置日志"""
        if self.logger is not None:
            return self.logger
        log_dir = os.path.join(self._temp_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)

        log_file = os.path.join(log_dir, log_name)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )

        self.logger = g_logger
        return self.logger

    def configure_ssl(self):
        """配置SSL"""
        pass
        
    def configure_vlan_pool(self):
        """配置VLAN池"""
        pass
        
    def configure_auth(self):
        """配置认证 - 使用临时文件和固定密钥"""
        # 创建临时JWT密钥文件
        jwt_secret_key_file = os.path.join(self._temp_dir, "jwt_secret.key")
        
        # 使用固定的测试密钥，不依赖文件系统
        self.jwt_secret_key = "test-jwt-secret-key-for-unit-testing-only-very-long-string-to-match-requirement"
        
        # 为了模拟实际环境，创建密钥文件（但实际使用固定密钥）
        try:
            os.makedirs(os.path.dirname(jwt_secret_key_file), exist_ok=True)
            with open(jwt_secret_key_file, 'w') as f:
                f.write(self.jwt_secret_key)
            # 设置文件权限（模拟生产环境）
            os.chmod(jwt_secret_key_file, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            # 文件操作失败不影响测试，因为我们使用固定密钥
            pass


@pytest.fixture(scope='function')
def app():
    """创建测试用 Flask 应用（内存 SQLite），并注册所有路由"""
    import tempfile
    from unittest import mock
    from virtcca_deploy.services.db_service import db
    from virtcca_deploy.manager import manager

    # 创建主临时目录
    main_temp_dir = tempfile.mkdtemp(prefix="virtcca_main_test_")
    
    # 统一使用内存数据库配置
    with mock.patch.multiple('virtcca_deploy.common.constants',
        DEFAULT_CONFIG_PATH=main_temp_dir,
        MANAGER_DB_PATH=main_temp_dir,
        MANAGER_DB='sqlite:///:memory:',
        CVM_COLLECT_LOG_PATH=os.path.join(main_temp_dir, "logs"),
        CVM_MANAGER_SOFTWARE_PATH=os.path.join(main_temp_dir, "software")):
        
        # 使用测试专用的配置对象
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
                
                from virtcca_deploy.manager.auth.auth_models import User
                if not User.query.filter_by(username="root").first():
                    root = User(username="root", password_hash='', salt='')
                    db.session.add(root)
                    db.session.commit()

            yield app
            
            # 测试结束后清理主临时目录
            try:
                import shutil
                if os.path.exists(main_temp_dir):
                    shutil.rmtree(main_temp_dir)
            except:
                pass


@pytest.fixture
def client(app):
    """Flask 测试客户端"""
    return app.test_client()


@pytest.fixture
def authenticated_client(app):
    """已认证的测试客户端"""
    from virtcca_deploy.manager.auth.auth_service import AuthService
    from virtcca_deploy.manager.auth.auth_models import User
    from virtcca_deploy.services.db_service import db

    with app.app_context():
        # 设置 root 密码
        hashed, salt = AuthService.hash_password("Test@1234")
        user = User.query.filter_by(username="root").first()
        user.password_hash = hashed
        user.salt = salt
        db.session.commit()

        # 直接从应用配置获取认证参数（确保是实际值）
        secret_key = app.config['JWT_SECRET_KEY']
        expiration_minutes = app.config['JWT_EXPIRATION_MINUTES']
        
        # 防御性检查：确保是整数
        if not isinstance(expiration_minutes, int):
            try:
                expiration_minutes = int(expiration_minutes)
            except (TypeError, ValueError):
                expiration_minutes = 30  # 默认值
        
        # 生成 token
        token = AuthService.generate_token(
            user_id=user.id,
            username="root",
            device_id="test-device-1",
            secret_key=secret_key,
            expiration_minutes=expiration_minutes
        )
        
        # 保存会话
        AuthService.set_active_session(
            user_id=user.id,
            username="root",
            device_id="test-device-1",
            token=token,
            ip_address="127.0.0.1"
        )

    client = app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


@pytest.fixture
def db_session(app):
    """提供数据库会话"""
    from virtcca_deploy.services.db_service import db
    with app.app_context():
        yield db.session
