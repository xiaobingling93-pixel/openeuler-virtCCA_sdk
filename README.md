# virtCCA_sdk

## 介绍
virtCCA（包含 TEE 虚拟化的 ARM 机密计算架构）的软件开发工具包，如远程认证、基于硬件的密钥派生等。

## 操作系统
支持鲲鹏架构下openEuler系列操作系统。

## 使用说明
- [远程证明](#远程证明)
- [kata(cc0.8.0版本)](https://gitee.com/openeuler/virtCCA_sdk/blob/master/kata-cc0.8.0/doc/zh-cn/confidential_container/kata%E6%9C%BA%E5%AF%86%E5%AE%B9%E5%99%A8.md)
- [kata(v3.15.0版本)](https://gitee.com/openeuler/virtCCA_sdk/blob/master/kata-v3.15.0/doc/kata%E6%9C%BA%E5%AF%86%E5%AE%B9%E5%99%A8.md)
    **机密容器推荐使用此版本**
- mpc使用样例
  - [arithmetic](https://gitee.com/openeuler/virtCCA_sdk/blob/master/MPC/demo/arithmetic/README.md)
  - [pir](https://gitee.com/openeuler/virtCCA_sdk/blob/master/MPC/demo/pir/README.md)
  - [psi](https://gitee.com/openeuler/virtCCA_sdk/blob/master/MPC/demo/psi/README.md)
- [qcow2镜像制作](https://gitee.com/openeuler/virtCCA_sdk/blob/master/cvm-image-rewriter/README.en.md)

## 远程证明

### 编译

1. 安装依赖
    ```sh
    yum install tar cmake make git gcc gcc-c++ openssl-devel glib2-devel
    ```

2. 编译安装基线度量值计算工具
    参考 `attestation/rim_ref/README.md`

3. 编译安装远程证明sdk
    ```sh
    cd attestation/sdk
    cmake -S . -B build
    cmake --build build
    cmake --install build
    ```

    **远程证明用户态静态库libvccaattestation.a会安装到/usr/local/lib目录下，头文件attestation.h会安装到/usr/local/include目录下**

4. 编译安装`QCBOR 1.2`和`t_cose 1.1.2`依赖，编译远程证明样例代码和支持virtCCA的rats-tls需要使用:
    ```sh
    if [ ! -d "QCBOR" ]; then
        git clone https://github.com/laurencelundblade/QCBOR.git -b v1.2
    fi
    if [ ! -d "t_cose" ]; then
        git clone https://github.com/laurencelundblade/t_cose.git -b v1.1.2
    fi
    cd QCBOR
    make
    make install
    cd ../t_cose
    cmake -S . -B build
    cmake --build build
    cmake --install build
    ```

5. 编译远程证明样例代码，样例代码需要依赖远程证明sdk、`QCBOR 1.2`和`t_cose 1.1.2`，需要提前安装好

    **样例代码server端包含了调用远程证明sdk获取远程证明报告的代码，client端包含了报告解析和验证的代码，server和client使用TCP进行数据传递，代码仅供参考，建议使用rats-tls**

    ```sh
    cd attestation/samples
    cmake -S . -B build
    cmake --build build
    ```
    **远程证明样例代码的server和client会生成到build目录下**

6. 编译安装`libcbor`依赖，编译支持virtCCA的rats-tls需要使用:
    ```sh
    git clone https://github.com/PJK/libcbor.git
    cd libcbor
    cmake -S . -B build
    cd build
    make
    make install
    ```

7. 编译支持virtCCA的rats-tls，rats-tls需要依赖远程证明sdk、`libcbor`、`QCBOR 1.2`和`t_cose 1.1.2`，需要提前安装好
    ```sh
    cd attestation/rats-tls
    git clone https://github.com/inclavare-containers/rats-tls.git
    cd rats-tls
    git reset --hard 40f7b78403d75d13b1a372c769b2600f62b02692
    git apply ../*.patch
    bash build.sh -s -r
    ```

    **编译完成后会在bin目录下生成rats-tls.tar.gz软件包**

8. 编译启动时证明使用的initramfs，initramfs需要依赖支持virtCCA的rats-tls，需要提前编译好
    ```sh
    cd attestation/initramfs
    bash build.sh
    ```


#### 远程证明样例代码

1. 启动server，server参数说明请使用`server -h`查看
    ```sh
    ./server
    ```

2. 启动client, 可以使用-m参数传递机密虚机的基线度量值用于校验，基线度量值可以使用基线度量值计算工具计算得到，client参数说明请使用`client -h`查看
    ```sh
    ./client -m 38d644db0aeddedbf9e11a50dd56fb2d0c663f664d63ad62762490da41562108
    ```


#### 支持virtCCA的rats-tls
1. 将rats-tls编译生产的rats-tls.tar.gz软件包拷贝到需要使用的机器，然后执行解压命令：
    ```sh
    tar -zxf rats-tls.tar.gz
    ```

2. 将rats-tls的动态库复制到/usr/lib目录下
    ```sh
    cp -r lib/rats-tls /usr/lib/
    ```

3. 导入环境变量后运行virtcca-server，virtcca-server参数说明请使用`virtcca-server -h`查看
    ```sh
    export LD_LIBRARY_PATH=/usr/lib/rats-tls:$LD_LIBRARY_PATH
    ./virtcca-server
    ```

3. 导入环境变量后运行virtcca-client，virtcca-client参数说明请使用`virtcca-client -h`查看
    ```sh
    export LD_LIBRARY_PATH=/usr/lib/rats-tls:$LD_LIBRARY_PATH
    ./virtcca-client
    ```

## 参与贡献
```
如果您想为本仓库贡献代码，请向本仓库任意maintainer发送邮件
如果您找到产品中的任何Bug，欢迎您提出ISSUE
```
