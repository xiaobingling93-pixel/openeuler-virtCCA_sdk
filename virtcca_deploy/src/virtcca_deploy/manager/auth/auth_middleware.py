#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import flask
from http import HTTPStatus

from virtcca_deploy.common.data_model import ApiResponse
from virtcca_deploy.manager.auth.auth_service import AuthService

KICKED_MESSAGE = "Your account has already been logged in on another device."


def _unauthorized_response(message):
    """构造统一的 401 响应"""
    return flask.jsonify(ApiResponse(
        message=message
    ).to_dict()), HTTPStatus.UNAUTHORIZED


def register_auth_middleware(app):
    """注册认证中间件到Flask应用"""

    INTERNAL_PREFIX = '/api/v1/internal/'
    PUBLIC_ROUTES = {'/', '/api/v1/auth/login'}

    @app.before_request
    def authenticate_request():
        """请求前认证检查"""
        path = flask.request.path

        # 内部路由直接放行
        if path.startswith(INTERNAL_PREFIX):
            return None

        # 白名单路由放行
        if path in PUBLIC_ROUTES:
            return None

        # 提取JWT token
        auth_header = flask.request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return _unauthorized_response("Missing authentication token.")

        token = auth_header.split(' ', 1)[1]
        secret_key = app.config.get('JWT_SECRET_KEY', '')
        if not secret_key:
            return _unauthorized_response("Server authentication not configured.")

        # 解码token
        payload = AuthService.decode_token(token, secret_key)
        if not payload:
            return _unauthorized_response("Invalid or expired token.")

        username = payload.get('sub')
        if not username:
            return _unauthorized_response("Invalid token payload.")

        # 检查是否为当前活跃session
        session = AuthService.get_active_session(username)
        if not session or session.token != token:
            return _unauthorized_response(KICKED_MESSAGE)

        # 将用户信息存入flask.g供后续使用
        flask.g.current_user = username
        flask.g.current_device_id = payload.get('dev', '')
        return None
