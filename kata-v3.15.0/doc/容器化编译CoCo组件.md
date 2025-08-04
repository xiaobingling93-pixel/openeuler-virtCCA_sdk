# 容器化编译CoCo远程证明组件

在使用了kata-deploy自动化部署的前提下，无需手动编译部署guest-componenets(步骤5)和kata-containers（步骤11、12），**本章节主要服务于远程证明组件编译（步骤6、7、8、9、10）。**

>  在部署有Docker本地镜像仓环境上搭建容器化编译环境。

1. 构建编译环境容器镜像。

   ```
   cd /home/kata-containers/build/virtCCA_sdk/kata-v3.15.0/conf/
   docker build --build-arg http_proxy=http://IP:PORT --build-arg https_proxy=http://IP:PORT -t coco-builder:latest .
   ```

   >![](public_sys-resources/icon-note.gif) **说明：** 
   >用户根据实际代理信息替换上述命令中的IP地址和端口，公网环境无需配置代理，下同。

3.  创建编译环境容器。

    ```
    docker run -itd --name coco-build-env -v /home/kata-containers:/coco -e http_proxy="http://IP:PORT" -e https_proxy="http://IP:PORT" coco-builder:latest
    ```

4.  进入容器。

    ```
    docker exec -it coco-build-env /bin/bash
    ```

5.  编译guest-componenet。

    ```
    cd /coco/build/guest-components
    make clean
    make build TEE_PLATFORM=virtcca
    ```

6.  编译度量报告获取调测工具。

    ```
    cd /coco/build/guest-components/attestation-agent/attester
    cargo build --no-default-features --features bin,virtcca-attester --bin evidence_getter --release
    ```

7.  编译coco\_keyprovider工具。

    ```
    cd /coco/build/guest-components/attestation-agent/coco_keyprovider
    cargo build --release
    ```

8.  编译attestation-service。

    ```
    cd /coco/build/trustee/attestation-service && make VERIFIER=virtcca-verifier
    ```

9.  编译rvps。

    ```
    cd /coco/build/trustee/rvps && make build
    ```

10. 编译kbs。

    ```
    cd /coco/build/trustee/kbs && make background-check-kbs COCO_AS_INTEGRATION_TYPE=grpc
    ```

11. 编译kata-agent。

    ```
    cd /coco/src/agent && make SECCOMP=no
    ```

12. 编译kata-shim和kata-runtime。

    ```
    cd /coco/ && make -C src/runtime
    ```

13. 退出容器。

    ```
    exit
    ```
14. 编译产物
    `guest-components`产物位于：`/home/kata-containers/build/guest-components/target/aarch64-unknown-linux-gnu/release/`
    `kbs rvps grpc-as`等产物位于：`/home/kata-containers/build/trustee/target/release/`
