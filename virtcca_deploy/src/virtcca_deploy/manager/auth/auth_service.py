#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import hashlib
import secrets
import re
import json
from datetime import datetime, timedelta, timezone

import jwt

import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants
from virtcca_deploy.manager.auth.auth_models import User, UserSession, AuditLog
from virtcca_deploy.services.db_service import db

g_logger = config.g_logger


class AuthService:
    """认证服务，静态方法提供无状态操作"""

    @staticmethod
    def hash_password(password: str, salt: str = None) -> tuple:
        """SHA-256 + 随机salt，返回 (hashed_password, salt)"""
        if salt is None:
            salt = secrets.token_hex(32)
        hashed = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
        return hashed, salt

    @staticmethod
    def verify_password(password: str, hashed_password: str, salt: str) -> bool:
        """验证密码"""
        return AuthService.hash_password(password, salt)[0] == hashed_password

    @staticmethod
    def validate_password_complexity(password: str) -> tuple:
        """校验密码复杂度：大小写+数字+特殊字符，长度≥8
        返回 (是否合法, 错误信息)
        """
        if len(password) < 8:
            return False, "The password must be at least 8 characters long."
        if not re.search(r'[A-Z]', password):
            return False, "The password must contain at least one uppercase letter."
        if not re.search(r'[a-z]', password):
            return False, "The password must contain at least one lowercase letter."
        if not re.search(r'[0-9]', password):
            return False, "The password must contain at least one digit."
        if not re.search(r'[^A-Za-z0-9]', password):
            return False, "The password must contain at least one special character."
        return True, ""

    @staticmethod
    def generate_token(user_id: int, username: str, device_id: str,
                       secret_key: str, expiration_minutes: int) -> str:
        """生成JWT token"""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": username,
            "uid": user_id,
            "dev": device_id,
            "iat": now,
            "exp": now + timedelta(minutes=expiration_minutes),
        }
        return jwt.encode(payload, secret_key, algorithm="HS256")

    @staticmethod
    def decode_token(token: str, secret_key: str) -> dict | None:
        """解码并验证JWT token"""
        try:
            return jwt.decode(token, secret_key, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            g_logger.warning("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            g_logger.warning("Invalid token: %s", e)
            return None

    @staticmethod
    def check_account_locked(user: User) -> tuple:
        """检查账户是否被锁定，返回 (是否锁定, 剩余秒数)"""
        if user.locked_until is None:
            return False, 0
        if isinstance(user.locked_until, str):
            locked_until = datetime.fromisoformat(user.locked_until)
        else:
            locked_until = user.locked_until
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            else:
                locked_until = locked_until.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        if now >= locked_until:
            return False, 0
        remaining = int((locked_until - now).total_seconds())
        return True, remaining

    @staticmethod
    def record_failed_login(username: str, ip_address: str, device_id: str,
                            max_attempts: int, lockout_minutes: int) -> tuple:
        """记录失败登录，返回 (是否被锁定, 剩余秒数)
        失败次数达到 max_attempts 时锁定账户 lockout_minutes 分钟
        """
        user = db.session.query(User).filter_by(username=username).first()
        if not user:
            return False, 0

        user.failed_login_count += 1
        if user.failed_login_count >= max_attempts:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)
            is_locked, remaining = True, lockout_minutes * 60
        else:
            is_locked, remaining = False, 0

        db.session.commit()

        AuthService._write_audit_log(
            username, "login_failed", device_id, ip_address,
            json.dumps({"failed_count": user.failed_login_count,
                        "locked": is_locked})
        )
        g_logger.warning("Failed login for user %s, count=%d, locked=%s",
                         username, user.failed_login_count, is_locked)
        return is_locked, remaining

    @staticmethod
    def reset_failed_login(username: str):
        """登录成功后重置失败计数和锁定状态"""
        user = db.session.query(User).filter_by(username=username).first()
        if user:
            user.failed_login_count = 0
            user.locked_until = None
            db.session.commit()

    @staticmethod
    def invalidate_previous_session(username: str, new_device_id: str,
                                    new_ip: str) -> str | None:
        """单设备登录：使之前设备的session失效，返回被踢出设备的device_id"""
        existing_session = db.session.query(UserSession).filter_by(
            username=username, logout_time=None).first()

        kicked_device_id = None
        if existing_session:
            kicked_device_id = existing_session.device_id
            existing_session.logout_time = datetime.now(timezone.utc)
            existing_session.logout_reason = "session_switch"
            db.session.commit()

            AuthService._write_audit_log(
                username, "session_switch", existing_session.device_id,
                existing_session.ip_address,
                json.dumps({
                    "old_device_id": existing_session.device_id,
                    "new_device_id": new_device_id,
                    "old_ip": existing_session.ip_address,
                    "new_ip": new_ip,
                    "switch_time": datetime.now(timezone.utc).isoformat()
                })
            )
            g_logger.info("Session switched for user %s: %s -> %s",
                          username, kicked_device_id, new_device_id)

        return kicked_device_id

    @staticmethod
    def set_active_session(user_id: int, username: str, device_id: str,
                           token: str, ip_address: str):
        """设置当前活跃session"""
        new_session = UserSession(
            user_id=user_id,
            username=username,
            device_id=device_id,
            token=token,
            ip_address=ip_address,
        )
        db.session.add(new_session)
        db.session.commit()

    @staticmethod
    def clear_active_session(username: str) -> bool:
        """清除活跃session（主动登出）"""
        session = db.session.query(UserSession).filter_by(
            username=username, logout_time=None).first()
        if session:
            session.logout_time = datetime.now(timezone.utc)
            session.logout_reason = "active_logout"
            db.session.commit()

            AuthService._write_audit_log(
                username, "active_logout", session.device_id,
                session.ip_address, None
            )
            g_logger.info("User %s logged out from device %s", username, session.device_id)
            return True
        return False

    @staticmethod
    def get_active_session(username: str) -> UserSession | None:
        """获取当前活跃session"""
        return db.session.query(UserSession).filter_by(
            username=username, logout_time=None).first()

    @staticmethod
    def set_root_password(password: str) -> tuple:
        """设置root用户密码，返回 (是否成功, 错误信息)"""
        is_valid, error_msg = AuthService.validate_password_complexity(password)
        if not is_valid:
            return False, error_msg

        user = db.session.query(User).filter_by(username=constants.ROOT_USERNAME).first()
        if not user:
            return False, f"User {constants.ROOT_USERNAME} does not exist."

        hashed, salt = AuthService.hash_password(password)
        user.password_hash = hashed
        user.salt = salt
        user.failed_login_count = 0
        user.locked_until = None
        db.session.commit()

        g_logger.info("Root password has been set successfully")
        return True, ""

    @staticmethod
    def init_root_user():
        """确保root用户存在（无密码状态，需通过CLI设置密码）"""
        existing = db.session.query(User).filter_by(username=constants.ROOT_USERNAME).first()
        if existing:
            return

        root_user = User(
            username=constants.ROOT_USERNAME,
            password_hash='',
            salt='',
        )
        db.session.add(root_user)
        db.session.commit()
        g_logger.info("Created default root user")

    @staticmethod
    def is_root_password_set() -> bool:
        """检查root密码是否已设置"""
        user = db.session.query(User).filter_by(username=constants.ROOT_USERNAME).first()
        return user is not None and bool(user.password_hash)

    @staticmethod
    def _write_audit_log(username: str, action: str, device_id: str,
                         ip_address: str, details: str | None):
        """写入审计日志"""
        log_entry = AuditLog(
            username=username,
            action=action,
            device_id=device_id,
            ip_address=ip_address,
            details=details,
        )
        db.session.add(log_entry)
        db.session.commit()
