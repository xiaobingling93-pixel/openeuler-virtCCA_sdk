# MIGVM Agent

## 
1. 下载安装编译依赖

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
cd -
```

1. 编译
```bash
mkdir build && cd build
cmake ..
make
cd -
```

1. 部署

将以下编译产物部署至CVM
```bash
cd rats-tls/bin/
tar xvf rats-tls.tar.gz
cp -rf lib/rats-tls ${CVM_PATH}/usr/lib/
cp -rfL lib/rats-tls/librats_tls.so.0 ${CVM_PATH}/lib64/

cd -
cp build/migcvm-agent   ${CVM_PATH}/home/
```

5. 运行
源机密虚机
```bash
./migcvm-agent
```

目的机密虚机
```bash
./migcvm-agent -r ${RIM}
```

宿主机
```bash
cd build
./socket-tool -c ${SRC_CID} -p ${SRC_VSOCK_PORT} -t 1 -i ${SRC_IP}
./socket-tool -c ${DST_CID} -p ${DST_VSOCK_PORT} -t 2 -i ${SRC_IP}
```

## 
```
.
 CMakeLists.txt        # CMake
 build.sh              # 
 debug/                # 
    socket-tool.c     # 
    tsi-test.c        # TSI
 migcvm_tsi/           # TSI
    migcvm_tsi.c
    tsi.h
 src/         # migcvm-agent
     xxx
```

## 
DH
1. xxxxxx

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

