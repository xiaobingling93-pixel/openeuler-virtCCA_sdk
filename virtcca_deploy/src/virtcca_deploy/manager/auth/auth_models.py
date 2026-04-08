#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from virtcca_deploy.services.db_service import db


class User(db.Model):
    """用户表"""
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False, default='')
    salt = db.Column(db.String(64), nullable=False, default='')
    failed_login_count = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return f"<User: {self.username}>"


class UserSession(db.Model):
    """用户会话表，同一用户只保留一条活跃记录"""
    __tablename__ = 'user_session'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    username = db.Column(db.String(80), nullable=False)
    device_id = db.Column(db.String(128), nullable=False)
    token = db.Column(db.String(512), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    login_time = db.Column(db.DateTime, default=db.func.current_timestamp())
    logout_time = db.Column(db.DateTime, nullable=True)
    logout_reason = db.Column(db.String(128), nullable=True)
        # 'active_logout', 'session_switch', 'token_expired'

    def __repr__(self):
        return f"<Session: {self.username}@{self.device_id}>"


class AuditLog(db.Model):
    """审计日志表"""
    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    action = db.Column(db.String(32), nullable=False)
        # 'login_success', 'login_failed', 'session_switch', 'active_logout', 'token_invalid'
    device_id = db.Column(db.String(128), nullable=True)
    ip_address = db.Column(db.String(45), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return f"<AuditLog: {self.username} {self.action}>"
