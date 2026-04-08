#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from virtcca_deploy.manager.auth.auth_routes import auth_bp
from virtcca_deploy.manager.auth.auth_service import AuthService
from virtcca_deploy.manager.auth.auth_models import User, UserSession, AuditLog
from virtcca_deploy.manager.auth.auth_middleware import register_auth_middleware


def init_auth(app, server_config):
    """初始化认证模块：创建表、注册蓝图、注册中间件、设置配置"""
    from virtcca_deploy.services.db_service import db

    # 将认证配置注入Flask app config
    app.config['JWT_SECRET_KEY'] = server_config.jwt_secret_key
    app.config['JWT_EXPIRATION_MINUTES'] = server_config.jwt_expiration_minutes
    app.config['MAX_LOGIN_ATTEMPTS'] = server_config.max_login_attempts
    app.config['LOCKOUT_DURATION_MINUTES'] = server_config.lockout_duration_minutes

    # 创建认证相关数据库表
    db.create_all()

    # 确保root用户存在
    AuthService.init_root_user()

    # 注册蓝图
    app.register_blueprint(auth_bp)

    # 注册认证中间件
    register_auth_middleware(app)
