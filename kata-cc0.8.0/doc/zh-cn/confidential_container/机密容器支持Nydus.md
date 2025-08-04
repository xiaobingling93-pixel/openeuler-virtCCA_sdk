# Nydus 基于机密容器部署
## 部署说明
### 环境依赖要求
参考 [机密容器部署运行](机密容器部署运行.md) 完成kata机密容器基础环境部署，主要依赖如下
| 软件包 | 版本 | 说明 | 获取路径 |
| :---------: | :---------: | :---------: | :---------: |
| runc | v1.1.8 | 低级容器运行时 | 通过yum源下载或安装 |
| contaienrd | v1.6.8.2 | coco社区适配的高级容器运行时 | https://github.com/confidential-containers/containerd/releases/download/v1.6.8.2/containerd-1.6.8.2-linux-arm64.tar.gz |
| k8s | 1.18.20 | 容器编排系统 | 通过yum源下载或安装 |
| kata | cc0.8.0 | 安全容器 | 参考 [机密容器部署运行](机密容器部署运行.md) 编译部署 |
| guest kernel | / | / | 参考 [机密容器部署运行](机密容器部署运行.mdC) 编译部署 |
| rootfs | / | / | 参考 [机密容器部署运行](机密容器部署运行.md) 编译部署 |

### 新增软件

| 软件包 | 版本 | 说明 | 获取路径 |
| :---------: | :---------: | :---------: | :---------: |
| nydus-static | v2.3.0 | 包含nydusd、nydus-image、nydusify等二进制软件，提供Nydus镜像解析、转换OCI镜像为Nydus等功能。 | https://github.com/dragonflyoss/nydus/releases/download/v2.3.0/nydus-static-v2.3.0-linux-arm64.tgz |
| Nydus Snapshotter | v0.15.0 | containerd外部插件，接收containerd的CRI请求，调用nydusd处理nydus镜像。 | https://github.com/containerd/nydus-snapshotter/releases/download/v0.14.0/nydus-snapshotter-v0.14.0-linux-arm64.tar.gz |
| Nerdctl | v1.7.7 | containerd 命令行工具。 | https://github.com/containerd/nerdctl/releases/download/v1.7.7/nerdctl-1.7.7-linux-arm64.tar.gz |

## nydus基础环境搭建

1. 安装nydus-image，nydusd，nydusify，nydusctl和nydus-overlayfs。

```bash
wget  https://github.com/dragonflyoss/nydus/releases/download/v2.3.0/nydus-static-v2.3.0-linux-arm64.tgz
tar -zxvf  nydus-static-v2.3.0-linux-arm64.tgz
cd nydus-static
install -D -m 755 nydusd nydus-image  nydusify nydusctl nydus-overlayfs /usr/bin
```

2. 安装containerd-nydus-grpc (nydus snapshotter)。

```bash
wget  https://github.com/containerd/nydus-snapshotter/releases/download/v0.14.0/nydus-snapshotter-v0.14.0-linux-arm64.tar.gz
tar -zxvf  nydus-snapshotter-v0.14.0-linux-arm64.tar.gz 
install -D -m 755 bin/containerd-nydus-grpc  /usr/bin
```

3. 安装nerdctl。

```
wget https://github.com/containerd/nerdctl/releases/download/v1.7.7/nerdctl-1.7.7-linux-arm64.tar.gz
tar -zxvf nerdctl-1.7.7-linux-arm64.tar.gz
install -D -m 755 nerdctl /usr/bin
```

4. 使用nydusify转换自建镜像仓中的镜像格式。

```bash
nydusify convert --source registry.com:5000/busybox:latest --target registry.com:5000/busybox:latest-nydus
```

> 本文档以私有仓busybox镜像为例进行说明，实际部署请按需将`registry.com:5000/busybox:latest`自行替换为目标镜像名。

5. 使用`nydusify`检查目标镜像，命令显示验证完毕且无错误信息，说明镜像转换成功。

```bash
nydusify check --target  registry.com:5000/busybox:latest-nydus
```

![image](figures/nydus-check.png)

6. 配置nydusd，文件路径：`/etc/nydus/nydusd-config.fusedev.json`。

```bash
tee /etc/nydus/nydusd-config.fusedev.json > /dev/null << EOF
{
  "device": {
    "backend": {
      "type": "registry",
      "config": {
        "scheme": "https",
        "skip_verify": false,
        "timeout": 5,
        "connect_timeout": 5,
        "retry_limit": 4,
        "auth": ""
      }
    },
    "cache": {
      "type": "blobcache",
      "config": {
        "work_dir": "cache"
      }
    }
  },
  "mode": "direct",
  "digest_validate": false,
  "iostats_files": false,
  "enable_xattr": true,
  "fs_prefetch": {
    "enable": true,
    "threads_count": 4
  }
}
EOF
```

- `device.backend.config.scheme`:  访问方式https/http。
- `device.backend.config.auth`:  私有仓登录信息，使用以下命令将私有仓的用户名和密码进行base64编码后再重新填入：
```bash
echo -n "username:password" | base64
```
- `device.backend.config.skip_verify`:  是否跳过https证书检查。

7. 获取nydus-snapshotter配置文件。

```
wget https://raw.githubusercontent.com/containerd/nydus-snapshotter/refs/tags/v0.14.0/misc/snapshotter/config.toml
```

8. 设置 nydus 的 home 目录`root`选项与本机 containerd 对应的`root`选项，此处设置与 [机密容器部署运行](机密容器部署运行.md) 中设置的containerd一致； 设置nydusd和nydus-image的实际安装路径，并关闭 `virtio_fs_extra_args` 选项。
```
vim config.toml

root = "/home/kata/var/lib/containerd/io.containerd.snapshotter.v1.nydus"
nydusd_path= "/usr/bin/nydusd"
nydusimage_path= "/usr/bin/nydus-image"

:wq
```
![image](figures/config.png)

9. 启动运行containerd-nydus-grpc。

```bash
containerd-nydus-grpc --config config.toml --log-to-stdout
```

10. 在`/etc/containerd/config.toml`路径下修改containerd配置文件。

```
vim /etc/containerd/config.toml

[plugins."io.containerd.grpc.v1.cri".containerd]
      default_runtime_name = "runc"
      disable_snapshot_annotations = false
      discard_unpacked_layers = false
      ignore_rdt_not_enabled_errors = false
      no_pivot = false
      snapshotter = "nydus" 
[proxy_plugins]
  [proxy_plugins.nydus]
    type = "snapshot"
    address = "/run/containerd-nydus/containerd-nydus-grpc.sock"
```

11. 重启containerd。

```bash
systemctl daemon-reload && systemctl restart containerd
```

12. 使用nerdctl拉取nydus镜像，使用ctr运行基于kata的nydus镜像。

```bash
nerdctl pull --snapshotter=nydus registry.com:5000/busybox:latest-nydus
ctr run --snapshotter=nydus --runtime "io.containerd.kata.v2"  --rm -t registry.com:5000/busybox:latest-nydus test-kata sh
```

![image](figures/9af5ff25-576c-4cd4-babb-30b4bcab8fa0.png)

## 使用k8s部署基于nydus镜像的kata容器

1. 在`/etc/kata-containers/configuration.toml`下修改kata配置。

```
vim /etc/kata-containers/configuration.toml
```

2. 配置nydus共享文件系统。

```
shared_fs = "virtio-fs-nydus" 
virtio_fs_daemon =  "/usr/bin/nydusd" 
virtio_fs_extra_args = []
# virtio_fs_extra_args = [ "--thread-pool-size=1",]
```

![image](figures/cd5c2f8f-2498-4d65-b41b-8766c3fc9648.png)

3. 设置service\_offload = true。

```
service_offload = true
```

4. 在kata-containers/src/agent/Cargo.toml中image-rs的features新增nydus。

![image](figures/c9c9cdb5-6ddc-4f7b-9b3f-63b34c7ceabf.png)

5. 重新编译 kata-agent，并安装到guest rootfs。

```bash
cd kata-containers/tools/osbuilder/rootfs-builder/ 
SECCOMP=no CFLAGS=-mno-outline-atomics ./rootfs.sh -r  "$PWD/kata-overlay" 
mount rootfs.img rootfs 
cp kata-overlay/usr/bin/kata-agent rootfs/usr/bin
umount rootfs
```

6. 修改containerd配置文件`/etc/containerd/config.toml`, 设置cri\_handler = "cc"。

![image](figures/b903ef15-db55-43da-bffd-037871d2f0c9.png)

7. 修改containerd配置后需重启使配置生效。

```
systemctl restart containerd
```

8. 新建k8s部署文件`nydus-kata-sandbox.yaml`。

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nydus-kata-sandbox
spec:
  restartPolicy: Never
  runtimeClassName: kata
  containers:
  - name: box-1    
    image: registry.com:5000/busybox:latest-nydus
    imagePullPolicy: Always
    command:
      - sh
    tty: true
```

9. 部署pod并查看启动情况。

```bash
kubectl apply -f nydus-kata-sandbox.yaml
kubectl get pods
```

![image](figures/nydus_pod部署.png)

# Nydus 部署签名镜像

1. 参考[机密容器远程证明](机密容器远程证明.md)编译部署attestation-agent、attestation-service和KBS。

2. 参考[镜像签名验签](容器镜像签名验签.md)配置skopeo和kata，并生成签名密钥。

> 注：当前nydus仅支持镜像签名功能，不支持镜像加密。

3. 使用skopeo对nydus镜像签名
参考 [镜像签名验签](容器镜像签名验签.md)
生成gpg密钥，通过下述命令获取密钥指纹。

```bash
gpg --list-keys --fingerprint
```

![](figures/zh-cn_image_0000002080359789.png)

4. 通过密钥指纹`key_hash`指定密钥对目标镜像进行签名。

```bash
skopeo copy --insecure-policy  \
--sign-by {key_hash} \
docker://registry.com:5000/busybox:latest-nydus \
docker://registry.com:5000/busybox_nydus_sign:latest
```

5. 生成签名镜像部署文件`nydus-kata-sandbox-sign.yaml`。

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nydus-kata-sandbox
spec:
  restartPolicy: Never
  runtimeClassName: kata
  containers:
  - name: box-1
    image: registry.com:5000/busybox_nydus_sign:latest
    imagePullPolicy: Always
    command:
      - sh
    tty: true
```

6. 部署前面镜像pod，并查看部署情况。

```bash
kubectl apply -f nydus-kata-sandbox-sign.yaml
kubectl get pods -A
```

![image](figures/2c26be49-be59-4f30-a561-d646192dd116.png)
