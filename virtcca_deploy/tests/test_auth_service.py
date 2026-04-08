#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone

import pytest

from virtcca_deploy.manager.auth.auth_service import AuthService


class TestHashPassword:
    def test_hash_password_returns_tuple(self):
        hashed, salt = AuthService.hash_password("Test@1234")
        assert isinstance(hashed, str)
        assert isinstance(salt, str)
        assert len(hashed) == 64  # SHA-256 hex digest
        assert len(salt) == 64  # 32 bytes hex

    def test_hash_password_different_salts(self):
        """每次调用应生成不同的 salt"""
        hashed1, salt1 = AuthService.hash_password("Test@1234")
        hashed2, salt2 = AuthService.hash_password("Test@1234")
        assert salt1 != salt2
        assert hashed1 != hashed2

    def test_hash_password_with_provided_salt(self):
        """提供相同 salt 时应产生相同哈希"""
        salt = "fixed_salt_value"
        h1, s1 = AuthService.hash_password("Test@1234", salt)
        h2, s2 = AuthService.hash_password("Test@1234", salt)
        assert h1 == h2
        assert s1 == s2 == salt

    def test_hash_password_matches_sha256(self):
        """验证哈希结果与手动 SHA-256 一致"""
        password = "Test@1234"
        salt = "test_salt"
        expected = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
        actual, s = AuthService.hash_password(password, salt)
        assert actual == expected


class TestVerifyPassword:
    def test_verify_correct_password(self):
        hashed, salt = AuthService.hash_password("Test@1234")
        assert AuthService.verify_password("Test@1234", hashed, salt) is True

    def test_verify_wrong_password(self):
        hashed, salt = AuthService.hash_password("Test@1234")
        assert AuthService.verify_password("Wrong@5678", hashed, salt) is False

    def test_verify_empty_password(self):
        hashed, salt = AuthService.hash_password("Test@1234")
        assert AuthService.verify_password("", hashed, salt) is False


class TestValidatePasswordComplexity:
    def test_valid_password(self):
        valid, msg = AuthService.validate_password_complexity("Test@1234")
        assert valid is True
        assert msg == ""

    def test_too_short(self):
        valid, msg = AuthService.validate_password_complexity("T@1a")
        assert valid is False
        assert "at least 8" in msg

    def test_no_uppercase(self):
        valid, msg = AuthService.validate_password_complexity("test@1234")
        assert valid is False
        assert "uppercase" in msg

    def test_no_lowercase(self):
        valid, msg = AuthService.validate_password_complexity("TEST@1234")
        assert valid is False
        assert "lowercase" in msg

    def test_no_digit(self):
        valid, msg = AuthService.validate_password_complexity("Test@abcd")
        assert valid is False
        assert "digit" in msg

    def test_no_special_char(self):
        valid, msg = AuthService.validate_password_complexity("Test1234")
        assert valid is False
        assert "special character" in msg

    def test_exact_8_chars_valid(self):
        valid, msg = AuthService.validate_password_complexity("Aa@12345")
        assert valid is True

    def test_empty_password(self):
        valid, msg = AuthService.validate_password_complexity("")
        assert valid is False


class TestGenerateAndDecodeToken:
    SECRET = "this-is-a-long-secret-key-for-testing-also-more-than-32-bytes"

    @pytest.fixture
    def wrong_long_secret_key(self):
        """返回足够长的错误测试密钥"""
        return "this-is-a-wrong-long-secret-key-for-testing-also-more-than-32-bytes"

    def test_generate_token_returns_string(self):
        token = AuthService.generate_token(1, "root", "dev1", self.SECRET, 30)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_valid_token(self):
        token = AuthService.generate_token(1, "root", "dev1", self.SECRET, 30)
        payload = AuthService.decode_token(token, self.SECRET)
        assert payload is not None
        assert payload['sub'] == 'root'
        assert payload['uid'] == 1
        assert payload['dev'] == 'dev1'

    def test_decode_with_wrong_secret(self, wrong_long_secret_key):
        token = AuthService.generate_token(1, "root", "dev1", self.SECRET, 30)
        payload = AuthService.decode_token(token, wrong_long_secret_key)
        assert payload is None

    def test_decode_expired_token(self, monkeypatch):
        """生成已过期的 token"""
        token = AuthService.generate_token(1, "root", "dev1", self.SECRET, -1)
        payload = AuthService.decode_token(token, self.SECRET)
        assert payload is None


class TestAccountLockout:
    def test_not_locked_initially(self, app, db_session):
        from virtcca_deploy.manager.auth.auth_models import User
        user = User.query.filter_by(username="root").first()
        assert user.failed_login_count == 0

        is_locked, remaining = AuthService.check_account_locked(user)
        assert is_locked is False
        assert remaining == 0

    def test_account_locked_after_max_attempts(self, app, db_session):
        from virtcca_deploy.manager.auth.auth_models import User
        user = User.query.filter_by(username="root").first()
        user.failed_login_count = 4
        user.locked_until = None
        db_session.commit()

        # 第5次失败
        is_locked, remaining = AuthService.record_failed_login(
            "root", "127.0.0.1", "dev1", max_attempts=5, lockout_minutes=15
        )
        assert is_locked is True
        assert remaining > 0

    def test_unlocked_after_timeout(self, app, db_session):
        from virtcca_deploy.manager.auth.auth_models import User
        from datetime import datetime, timedelta, timezone
        user = User.query.filter_by(username="root").first()
        user.failed_login_count = 5
        user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=20)
        db_session.commit()

        is_locked, remaining = AuthService.check_account_locked(user)
        assert is_locked is False

    def test_reset_failed_login(self, app, db_session):
        from virtcca_deploy.manager.auth.auth_models import User
        from datetime import datetime, timedelta, timezone
        user = User.query.filter_by(username="root").first()
        user.failed_login_count = 5
        user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=20)
        db_session.commit()

        AuthService.reset_failed_login("root")

        db_session.refresh(user)
        assert user.failed_login_count == 0
        assert user.locked_until is None
