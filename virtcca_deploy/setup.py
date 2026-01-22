#!/usr/bin/python3.11
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

from setuptools import setup, find_packages

with open('requirements.txt') as f:
        requirements = f.read().splitlines()

        setup(
            name="virtcca_deploy",
            version="0.1.0",
            description='virtcca auto deploy tools',
            package_dir={"": "src"},
            packages=find_packages(where="src"),
            install_requires=requirements,
            data_files=[
                ("/etc/virtcca_deploy",  ["conf/virtcca_deploy.conf"]),
            ],
            entry_points={
                'console_scripts': [
                'virtcca-compute=virtcca_deploy.compute.compute:main',
                'virtcca-manager=virtcca_deploy.manager.manager:main',
                ],
    },
)