# MIGVM Agent

## 
1. 下载安装编译依赖
yum install virtCCA_sdk virtCCA_sdk-devel

QCBOR
```bash
git clone https://github.com/laurencelundblade/QCBOR.git -b v1.2
cd QCBOR
make
make install
cd -
```

t_cose
```bash
git clone https://github.com/laurencelundblade/t_cose.git -b v1.1.2
cd t_cose
cmake -S . -B build -DCRYPTO_PROVIDER=OpenSSL
cmake --build build
cmake --install build
cd -
```

libcbor
```bash
git clone https://github.com/PJK/libcbor.git
cd libcbor
cmake -S . -B build
cmake --build build
cmake --install build
cd -
```

rats-tls(该仓库须放置于当前migcvm-agent目录下)
```bash
git clone https://github.com/inclavare-containers/rats-tls.git
cd rats-tls
git reset --hard 40f7b78403d75d13b1a372c769b2600f62b02692
git apply ../../attestation/rats-tls/*.patch
bash build.sh -s -r -c -v gcc
cp -rf output/lib/rats-tls /usr/lib/
cp -rfL output/lib/rats-tls/librats_tls.so.0 /lib64/
cd -
```

2. 编译
```bash
chmod +x build.sh
./build.sh
```

3. 部署

将以下编译产物部署至CVM
```bash
cp build/migcvm-agent   ${CVM_PATH}/home/
```

4. 运行
源机密虚机
```bash
./migcvm-agent -s ${local-ip} -c ${remote-ip} -r ${RIM}
```

目的机密虚机
```bash
./migcvm-agent -s ${local-ip} -c ${remote-ip} -r ${RIM}
```

## 
通信矩阵
1. 源设备：热迁移源端MIG-CVM机密虚拟机
2. 源IP地址：源端MIG-CVM机密虚拟机IP地址
3. 源端口：1024~65535（默认值1234）
4. 目的设备：目标端MIG-CVM机密虚拟机
5. 目的IP地址：目标端MIG-CVM机密虚拟机IP地址
6. 目的端口（侦听）：1234
7. 协议：TCP
8. 端口说明：用于RATS-TLS信道内部密文秘钥传输监听端口
9. 侦听端口是否可更改：否
10. 认证方式：RATS-TLS
11. 加密方式：RATS_TLS_CERT_ALGO_RSA_3072_SHA256
12. 所属平面：控制面
13. 版本：所有版本
14. 特殊场景：无

## 
- CMake (>= 3.10)
- GNU Make
- C (GCCClang)

---

# MIGVM Agent

## Overview
The MIGVM Agent is a virtual machine migration agent that provides socket communication and TSI (Trusted Service Interface) capabilities.

## Build Instructions
1. Clone the repository
2. Run the build script:
```bash
chmod +x build.sh
./build.sh
```

The executable will be generated in the `build` directory as `migvm_agent`.

### Debug Mode
To build in debug mode, add the `--debug` parameter:
```bash
./build.sh --debug
```

Debug tool (socket-send) can be built separately:
```bash
./build.sh --build-debug-tool
```

## Run Instructions
Execute the agent with:
```bash
./build/migvm_agent
```

## Directory Structure
```
.
 CMakeLists.txt        # CMake configuration
 build.sh              # Build automation script
 migvm_agent.c         # Main application
 debug/                # Debug tools
    socket-send.c     # Socket test tool
    tsi-test.c        # TSI test tool
 migcvm_tsi/           # TSI implementation
    migcvm_tsi.c
    tsi.h
 socket_agent/         # Socket communication
     host_socket_agent.c
     socket_agent.h
```

## Secure Communication
The agent uses DH key exchange to establish secure channels:
1. xxxxxx

## Dependencies
- CMake (>= 3.10)
- GNU Make
- C compiler (GCC or Clang)

## License
This project is licensed under the MIT License.

