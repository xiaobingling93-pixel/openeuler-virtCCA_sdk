## 一键部署脚本
### 使用说明
> - chmod 755 ./build.sh
> - 分步执行脚本需要遵循下面的执行顺序。
> - export http_proxy 配置代理以解决镜像拉取和安装包下载等网络问题，且代理配置需要写到/etc/profile文件。

1. `./build.sh containerd`
    完成containerd部署，并ctr命令启动一个runc容器。

2. `./build.sh k8s`
    初始化k8s集群（单节点）。

3. `./build.sh kdeploy`
    制作`kata-deploy`镜像：安装docker并启动registry本地镜像仓，下载组件源码并应用patch，编译构建kata-deploy镜像并推送本地镜像仓。
    注意：
    - **此步骤只需执行一次即可，后续的机密容器环境部署可以复用该镜像。**
    - 支持在非virtCCA的普通机器执行，则后续virtCCA执行机拉取镜像时需要：①registry本地镜像仓的rootCA需要部署到执行机；②执行机的/etc/hosts中添加registry本地镜像仓与其IP的映射；③mount到执行机机密容器文件系统，添加域名映射（同②）。

4. `./build operator`
    拉取kata-deploy镜像，启动cc-operator系列容器（manage & daemon），完成机密容器环境部署。至此，环境已经可以启动virtCCA机密容器，后续步骤用户按需参考执行，非必要步骤。

5. `./build.sh rats`
    编译远程证明组件(kbs、rvps、as)并在host上拉起对应服务，安装cosign和skopeo等工具。

6. `./build.sh encrypt`
    启动一个加密镜像的参考流程。

7. `./build.sh nydus`
    安装nydus启动相关的二进制文件和配置文件。

8. `./build.sh all`
    按上述顺序一次性执行上述操作，考虑到网络波动等因素，建议分步执行，确保每一步成功执行后再执行下一步。