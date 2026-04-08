#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import flask
from http import HTTPStatus

import virtcca_deploy.common.config as config
from virtcca_deploy.common.constants import (
    ROUTE_AUTH_LOGIN, ROUTE_AUTH_LOGOUT,
)
from virtcca_deploy.common.data_model import ApiResponse
from virtcca_deploy.manager.auth.auth_service import AuthService
from virtcca_deploy.manager.auth.auth_models import User

g_logger = config.g_logger

auth_bp = flask.Blueprint('auth', __name__)


@auth_bp.route(ROUTE_AUTH_LOGIN, methods=['POST'])
def login():
    """用户登录接口"""
    if not flask.request.is_json:
        return flask.jsonify(ApiResponse(
            message="Content-Type must be application/json"
        ).to_dict()), HTTPStatus.BAD_REQUEST

    data = flask.request.get_json()
    if not data:
        return flask.jsonify(ApiResponse(
            message="Request body is required"
        ).to_dict()), HTTPStatus.BAD_REQUEST

    username = data.get('username', '').strip()
    password = data.get('password', '')
    device_id = data.get('device_id', '').strip()

    if not username or not password or not device_id:
        return flask.jsonify(ApiResponse(
            message="Missing required fields: username, password, device_id"
        ).to_dict()), HTTPStatus.BAD_REQUEST

    # 仅支持root用户
    if username != "root":
        return flask.jsonify(ApiResponse(
            message="The user does not exist."
        ).to_dict()), HTTPStatus.NOT_FOUND

    user = User.query.filter_by(username=username).first()
    if not user:
        return flask.jsonify(ApiResponse(
            message="The user does not exist."
        ).to_dict()), HTTPStatus.NOT_FOUND

    # 检查密码是否已设置
    if not AuthService.is_root_password_set():
        return flask.jsonify(ApiResponse(
            message="The password of user root is not set"
        ).to_dict()), HTTPStatus.UNAUTHORIZED

    # 检查账户锁定状态
    is_locked, remaining = AuthService.check_account_locked(user)
    if is_locked:
        return flask.jsonify(ApiResponse(
            message=f"The account has been locked. Please try again in {remaining} seconds."
        ).to_dict()), HTTPStatus.TOO_MANY_REQUESTS

    # 验证密码
    if not AuthService.verify_password(password, user.password_hash, user.salt):
        AuthService.record_failed_login(
            username, flask.request.remote_addr, device_id,
            max_attempts=flask.current_app.config.get('MAX_LOGIN_ATTEMPTS', 5),
            lockout_minutes=flask.current_app.config.get('LOCKOUT_DURATION_MINUTES', 15)
        )
        return flask.jsonify(ApiResponse(
            message="Incorrect user name or password"
        ).to_dict()), HTTPStatus.UNAUTHORIZED

    # 密码正确，重置失败计数
    AuthService.reset_failed_login(username)

    # 单设备登录：踢出旧会话
    AuthService.invalidate_previous_session(
        username, device_id, flask.request.remote_addr)

    # 生成JWT token
    token = AuthService.generate_token(
        user_id=user.id,
        username=username,
        device_id=device_id,
        secret_key=flask.current_app.config['JWT_SECRET_KEY'],
        expiration_minutes=flask.current_app.config.get('JWT_EXPIRATION_MINUTES', 30)
    )

    # 保存会话记录
    AuthService.set_active_session(
        user_id=user.id,
        username=username,
        device_id=device_id,
        token=token,
        ip_address=flask.request.remote_addr
    )

    # 记录登录成功审计日志
    AuthService._write_audit_log(
        username, "login_success", device_id,
        flask.request.remote_addr, None
    )

    g_logger.info("User %s logged in successfully from %s", username, flask.request.remote_addr)

    return flask.jsonify(ApiResponse(
        message="Login succeeded.",
        data={"token": token}
    ).to_dict())


@auth_bp.route(ROUTE_AUTH_LOGOUT, methods=['POST'])
def logout():
    """用户主动登出接口"""
    auth_header = flask.request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return flask.jsonify(ApiResponse(
            message="Missing authentication token"
        ).to_dict()), HTTPStatus.UNAUTHORIZED

    token = auth_header.split(' ', 1)[1]
    secret_key = flask.current_app.config.get('JWT_SECRET_KEY', '')
    payload = AuthService.decode_token(token, secret_key)

    if not payload:
        return flask.jsonify(ApiResponse(
            message="Invalid or expired token"
        ).to_dict()), HTTPStatus.UNAUTHORIZED

    username = payload.get('sub', '')
    AuthService.clear_active_session(username)

    return flask.jsonify(ApiResponse(
        message="Logged out successfully."
    ).to_dict())
