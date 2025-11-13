# KCAL中间件 Python 接口封装

本文介绍 KCAL 中间件用 Python 进行封装(目前仅提供PSI接口)的项目如何 virtCCA 内部部署和验证, 对外提供以 Python 方式集成的思路

## 前置条件

1. 需获取 `kcal` 包，含 `include`和`lib`目录，获取链接: [https://www.hikunpeng.com/developer/download](https://gitee.com/link?target=https%3A%2F%2Fwww.hikunpeng.com%2Fdeveloper%2Fdownload)
2. 安装 `Python` 和 `pdm` 包, 以及依赖 `pybind11-3.0.1`版本
3. 运行环境为`virtCCA cvm，前提是用户已经启动两个 virtCCA 的机密虚机（cvm1、cvm2）`

## 目录结构介绍

当前项目目录如下, kcal 包下载后, 需要进行解压并将 kcal 包内的`include`、`lib`目录放到当前目录下, 然后进行构建

```bash
.
|-- CMakeLists.txt                   # pybind11 包装的项目构建文件
|-- README.md                        # 说明文档
|-- build_native.py                  # 构建 Python 封装包的脚本
|-- include                          # kcal 头文件
|-- kcal                             # 实际打包进 whl 里面的目录
|   |-- __init__.py
|   |-- kcal.pyi                     # Python 接口存根文件
|-- lib                              # kcal 动态链接库
|-- pyproject.toml                   # Python 打包管理说明
|-- src                              # pybind11 封装 kcal 中间件的源码
|   |-- CMakeLists.txt
|   |-- context_ext.cc
|   |-- context_ext.h
|   |-- kcal_wrapper.cc              # Python 对外接口
|-- test                             # 测试目录
    |-- __init__.py
    |-- demo.py                      # 演示示例
    |-- socket_util.py               # 简单 socket 网络通信实现
```

## 构建

进入到`kcal_python`目录, 然后执行以下操作(前提是已经安装好 `Python` 和 `pdm` 包, 这里推荐使用 `uv` 作为 `Python` 的版本管理工具)

### 安装依赖

1. 安装 uv 工具

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. 创建虚拟环境

   ```bash
   uv venv --python 3.11
   source .venv/bin/activate
   ```

3. 安装 pdm 工具

   ```bash
   uv pip install pdm
   ```

### 打包

该打包过程基于`kcal_python`根目录下面的`kcal`目录进行打包, `kcal`加速库会一并打包进`.whl`包内, 并在导入时自动加载

```bash
# 先构建 Python 模块
pdm run build-native

# 打包
pdm build
```

执行完后会在`dist`目录下面生成打包好的`.whl`包, 然后执行 `uv pip install dist/*.whl --force-reinstall`即可覆盖安装

## 部署

只需将生成的`.whl`包导入到`cvm`内, 然后在`cvm`内进行安装, 前提是`cvm`内安装有`Python`, 步骤如下

注: 机密虚机启动及连接参考: [https://www.hikunpeng.com/document/detail/zh/kunpengcctrustzone/tee/cVMcont/kunpengtee_16_0027.html](https://www.hikunpeng.com/document/detail/zh/kunpengcctrustzone/tee/cVMcont/kunpengtee_16_0027.html)

```bash
# 这里以 cvm 内的 /home/admin/dev 作为工作目录
scp dist/*.whl root@<cvm_ip>:/home/admin/dev/

# 安装, 进入到 cvm 内
pip install *.whl --force-reinstall
```

## 测试

为方便演示, 这里仅在一台机器上进行测试, 实际情况在两台分离部署的`cvm`内进行测试, 将`test`目录直接拷贝进`cvm`内的`/home/admin/dev`下, 连接`cvm`, 并打开两个终端, 分别运行以下指令, 即可进行`PSI`的测试, 数据量按需修改`test/demo.py`文件

```bash
python test/demo.py --server --host "127.0.0.1" -p 9090
python test/demo.py --client --host "127.0.0.1" -p 9090
```

