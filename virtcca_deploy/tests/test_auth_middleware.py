#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from conftest import SECRET_KEY, VALID_PASSWORD
from virtcca_deploy.manager.auth.auth_service import AuthService
from virtcca_deploy.manager.auth.auth_models import User
from virtcca_deploy.services.db_service import db


class TestAuthMiddleware:
    def test_root_route_not_protected(self, client):
        """根路由不需要认证（404表示没有注册该路由，但不是401说明认证未拦截）"""
        resp = client.get('/')
        assert resp.status_code != 401

    def test_login_route_not_protected(self, client):
        """登录路由不需要认证"""
        resp = client.post('/api/v1/auth/login', json={})
        assert resp.status_code != 401  # 400是正常响应，不是认证失败

    def test_external_route_requires_auth(self, client):
        """外部路由需要认证"""
        resp = client.post('/api/v1/host/node-info', json={})
        assert resp.status_code == 401
        data = resp.get_json()
        assert "token" in data['message'].lower() or "authentication" in data['message'].lower()

    def test_deploy_route_requires_auth(self, client):
        """部署路由需要认证"""
        resp = client.post('/api/v1/vm/deploy', json={})
        assert resp.status_code == 401

    def test_undeploy_route_requires_auth(self, client):
        """销毁路由需要认证"""
        resp = client.post('/api/v1/vm/undeploy', json={})
        assert resp.status_code == 401

    def test_state_route_requires_auth(self, client):
        """状态查询路由需要认证"""
        resp = client.get('/api/v1/vm/state')
        assert resp.status_code == 401

    def test_valid_token_passes_middleware(self, authenticated_client):
        """有效 token 应通过中间件"""
        # /api/v1/host/node-info 需要认证，但由于我们的测试 app 没有注册该路由，
        # 这里验证 token 验证逻辑本身：用 flask.g 来检查
        resp = authenticated_client.get('/api/v1/vm/state')
        # 即使路由不存在（404），也不应该是 401
        assert resp.status_code != 401

    def test_expired_token_fails(self, client):
        """过期 token 应返回 401"""
        expired_token = AuthService.generate_token(
            user_id=1, username="root", device_id="dev1",
            secret_key=SECRET_KEY, expiration_minutes=-1
        )
        client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {expired_token}'
        resp = client.get('/api/v1/vm/state')
        assert resp.status_code == 401

    def test_kicked_session_fails(self, client, app):
        """被踢出的 session 应返回 401 + 特殊消息"""
        with app.app_context():
            hashed, salt = AuthService.hash_password(VALID_PASSWORD)
            user = User.query.filter_by(username="root").first()
            user.password_hash = hashed
            user.salt = salt
            db.session.commit()

        # 设备1登录
        resp1 = client.post('/api/v1/auth/login', json={
            'username': 'root', 'password': VALID_PASSWORD,
            'device_id': 'device-1',
        })
        token1 = resp1.get_json()['data']['token']

        # 设备2登录（踢出设备1）
        client.post('/api/v1/auth/login', json={
            'username': 'root', 'password': VALID_PASSWORD,
            'device_id': 'device-2',
        })

        # 设备1使用旧token
        client2 = app.test_client()
        client2.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token1}'
        resp = client2.get('/api/v1/vm/state')
        assert resp.status_code == 401
        data = resp.get_json()
        from virtcca_deploy.manager.auth.auth_middleware import KICKED_MESSAGE
        assert KICKED_MESSAGE in data['message']

    def test_missing_bearer_prefix_fails(self, client):
        """缺少 Bearer 前缀应返回 401"""
        client.environ_base['HTTP_AUTHORIZATION'] = 'some-token'
        resp = client.get('/api/v1/vm/state')
        assert resp.status_code == 401

    def test_no_auth_header_fails(self, client):
        """无 Authorization 头应返回 401"""
        resp = client.get('/api/v1/vm/state')
        assert resp.status_code == 401
