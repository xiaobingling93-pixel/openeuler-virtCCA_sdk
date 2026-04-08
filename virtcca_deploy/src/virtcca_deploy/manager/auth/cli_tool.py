#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""
virtCCA Deploy 管理工具 CLI
用于设置 root 用户密码等管理操作

用法:
    virtcca-deploy-tool set-password [--password <密码>]
    virtcca-deploy-tool set-password  (交互式输入)
"""

import argparse
import os
import sys
import getpass

import virtcca_deploy.common.config as config
import virtcca_deploy.common.constants as constants
from virtcca_deploy.manager.auth.auth_service import AuthService
from virtcca_deploy.manager.auth.auth_models import User
from virtcca_deploy.services.db_service import db


def _get_app_context():
    """创建最小Flask应用以获取数据库上下文"""
    import flask
    app = flask.Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = constants.MANAGER_DB
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def set_root_password(password: str) -> int:
    """设置root用户密码，返回退出码"""
    # 检查root权限
    if os.geteuid() != 0:
        print("Error: Setting the password requires administrative privileges, please run this command with sudo.")
        return 1

    # 校验密码复杂度
    is_valid, error_msg = AuthService.validate_password_complexity(password)
    if not is_valid:
        print(f"错误: {error_msg}")
        return 1

    app = _get_app_context()
    with app.app_context():
        db.create_all()
        AuthService.init_root_user()

        success, msg = AuthService.set_root_password(password)
        if success:
            print(f"The password of user root is set successfully.")
            return 0
        else:
            print(f"Error: {msg}")
            return 1


def interactive_set_password() -> int:
    """交互式设置root密码"""
    print("Setting the Password of the virtCCA Deploy root User")
    print("The password must contain at least eight characters,\
+including uppercase letters, lowercase letters, digits, and special characters.\n")

    while True:
        password = getpass.getpass("Enter the new password: ")
        confirm = getpass.getpass("Confirm the new password: ")

        if password != confirm:
            print("Error: The passwords are inconsistent. Please try again.\n")
            continue

        return set_root_password(password)


def main():
    parser = argparse.ArgumentParser(
        description='virtCCA Deploy Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 设置root密码（交互式）
  virtcca-deploy-tool set-password
        """
    )
    subparsers = parser.add_subparsers(dest='command', help='available command')

    # set-password 子命令
    subparsers.add_parser('set-password', help='set password for root')

    args = parser.parse_args()

    if args.command == 'set-password':
            sys.exit(interactive_set_password())
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
