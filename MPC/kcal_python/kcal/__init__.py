# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import os
import time
import ctypes

_pkg_dir = os.path.dirname(__file__)
_lib_dir = os.path.join(_pkg_dir, "lib")

if os.path.isdir(_lib_dir):
    old_ld = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = _lib_dir + os.pathsep + old_ld

    failed_files = []
    for so_file in os.listdir(_lib_dir):
        if so_file.endswith(".so"):
            so_path = os.path.join(_lib_dir, so_file)
            try:
                ctypes.CDLL(so_path, mode=ctypes.RTLD_GLOBAL)
                print(f"Preloaded {so_path} (RTLD_GLOBAL)")
            except OSError as e:
                failed_files.append(so_path)

    for _ in range(15):
        if failed_files:
            for so_file in failed_files:
                time.sleep(0.1)
                try:
                    ctypes.CDLL(str(so_file), mode=ctypes.RTLD_GLOBAL)
                    print(f"Preloaded {so_file} (RTLD_GLOBAL)")
                    failed_files.remove(so_file)
                except OSError as e:
                    print(f"Failed to load {so_file} {e}")
                    continue

    if failed_files:
        raise RuntimeError(f"kcal {failed_files} so lib failed to load")

from .kcal import *
