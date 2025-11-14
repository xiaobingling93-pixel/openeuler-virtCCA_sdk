# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""
Usage:
    pdm run build-native
"""
import subprocess
import sys
from pathlib import Path
import shutil
import os

DEPENDENCY_LIB_NAMES = [
    "libdata_guard_common.so",
    "libdata_guard.so",
    "libhitls_bsl.so",
    "libhitls_crypto.so",
    "libmpc_tee.so",
    "libsecurec.so",
]


def find_built_extension(build_dir, expected_basename):
    if sys.platform.startswith("win"):
        exts = [".pyd", ".dll"]
    elif sys.platform == "darwin":
        exts = [".so", ".dylib"]
    else:
        exts = [".so"]
    for ext in exts:
        for p in build_dir.rglob(f"*{expected_basename}*{ext}"):
            return p.resolve()
    for ext in exts:
        candidate = build_dir / (expected_basename + ext)
        if candidate.exists():
            return candidate.resolve()
    return None


def build_native():
    root = Path(__file__).parent.resolve()
    build_dir = root / "build"
    pkg_dir = root / "kcal"
    pkg_dir.mkdir(exist_ok=True)

    module_name = "kcal"

    # Configure
    print("CMake configure...")
    build_dir.mkdir(parents=True, exist_ok=True)
    cmake_cmd = ["cmake", "-S", str(root), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release"]
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        cmake_cmd.append(f"-DPython3_ROOT_DIR={conda_prefix}")
    subprocess.run(cmake_cmd, check=True)

    # Build
    print("CMake build...")
    build_cmd = ["cmake", "--build", str(build_dir), f"-j{os.cpu_count() - 1}"]
    if sys.platform.startswith("win"):
        build_cmd += ["--config", "Release"]
    subprocess.run(build_cmd, check=True)

    # Copy built extension
    print("Searching for built extension...")
    built_ext = find_built_extension(build_dir, module_name)
    if not built_ext:
        raise FileNotFoundError(f"Built extension for {module_name} not found in {build_dir}")
    target_name = module_name + (".pyd" if sys.platform.startswith("win") else ".so")
    target_path = pkg_dir / target_name
    shutil.copy2(built_ext, target_path)
    print(f"Copied extension: {built_ext} -> {target_path}")

    # Copy dependency libs
    lib_dir = root / "lib"
    pkg_lib_dir = pkg_dir / "lib"
    shutil.copytree(lib_dir, pkg_lib_dir, dirs_exist_ok=True)

    print("build-native finished. Run `pdm build` to create wheel.")


if __name__ == "__main__":
    build_native()
