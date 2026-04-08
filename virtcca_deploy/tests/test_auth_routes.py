#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import json
from conftest import SECRET_KEY, VALID_PASSWORD
from virtcca_deploy.manager.auth.auth_service import AuthService
from virtcca_deploy.manager.auth.auth_models import User
from virtcca_deploy.services.db_service import db


class TestLoginEndpoint:
    def test_login_success(self, client, app):
        with app.app_context():
            hashed, salt = AuthService.hash_password(VALID_PASSWORD)
            user = User.query.filter_by(username="root").first()
            user.password_hash = hashed
            user.salt = salt
            db.session.commit()

        resp = client.post('/api/v1/auth/login', json={
            'username': 'root',
            'password': VALID_PASSWORD,
            'device_id': 'device-1',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'token' in data['data']

    def test_login_wrong_password(self, client, app):
        with app.app_context():
            hashed, salt = AuthService.hash_password(VALID_PASSWORD)
            user = User.query.filter_by(username="root").first()
            user.password_hash = hashed
            user.salt = salt
            db.session.commit()

        resp = client.post('/api/v1/auth/login', json={
            'username': 'root',
            'password': 'Wrong@1234',
            'device_id': 'device-1',
        })
        assert resp.status_code == 401
        data = resp.get_json()

    def test_login_missing_fields(self, client):
        resp = client.post('/api/v1/auth/login', json={
            'username': 'root',
        })
        assert resp.status_code == 400

    def test_login_non_json(self, client):
        resp = client.post('/api/v1/auth/login', data='not json')
        assert resp.status_code == 400

    def test_login_nonexistent_user(self, client, app):
        with app.app_context():
            hashed, salt = AuthService.hash_password(VALID_PASSWORD)
            user = User.query.filter_by(username="root").first()
            user.password_hash = hashed
            user.salt = salt
            db.session.commit()

        resp = client.post('/api/v1/auth/login', json={
            'username': 'nonexistent',
            'password': VALID_PASSWORD,
            'device_id': 'device-1',
        })
        assert resp.status_code == 404

    def test_login_password_not_set(self, client):
        resp = client.post('/api/v1/auth/login', json={
            'username': 'root',
            'password': VALID_PASSWORD,
            'device_id': 'device-1',
        })
        assert resp.status_code == 401
        data = resp.get_json()
        assert "The password of user root is not set" in data['message']

    def test_login_account_locked(self, client, app):
        from datetime import datetime, timedelta, timezone
        with app.app_context():
            hashed, salt = AuthService.hash_password(VALID_PASSWORD)
            user = User.query.filter_by(username="root").first()
            user.password_hash = hashed
            user.salt = salt
            user.failed_login_count = 5
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
            db.session.commit()

        resp = client.post('/api/v1/auth/login', json={
            'username': 'root',
            'password': VALID_PASSWORD,
            'device_id': 'device-1',
        })
        assert resp.status_code == 429


class TestLogoutEndpoint:
    def test_logout_success(self, authenticated_client):
        resp = authenticated_client.post('/api/v1/auth/logout')
        assert resp.status_code == 200
        data = resp.get_json()

    def test_logout_missing_token(self, client):
        resp = client.post('/api/v1/auth/logout')
        assert resp.status_code == 401

    def test_logout_invalid_token(self, client):
        client.environ_base['HTTP_AUTHORIZATION'] = 'Bearer invalid-token-string'
        resp = client.post('/api/v1/auth/logout')
        assert resp.status_code == 401


class TestSingleDeviceLogin:
    def test_second_login_kicks_first(self, client, app):
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

        # 设备2登录
        resp2 = client.post('/api/v1/auth/login', json={
            'username': 'root', 'password': VALID_PASSWORD,
            'device_id': 'device-2',
        })
        token2 = resp2.get_json()['data']['token']

        assert token1 != token2

        # 设备1使用旧token访问受保护路由
        client2 = app.test_client()
        client2.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token1}'
        resp3 = client2.get('/api/v1/host/node-info')
        assert resp3.status_code == 401
        data = resp3.get_json()
        from virtcca_deploy.manager.auth.auth_middleware import KICKED_MESSAGE
        assert KICKED_MESSAGE in data['message']
