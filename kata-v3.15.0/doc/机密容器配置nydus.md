# 机密容器配置nydus

当前 virtcca-kata-deploy 默认使用 v0.13.0 版本 nydus-snapshotter，建议提升至 v0.14.0 版本，保证 ctr 方式启动 nydus 镜像的兼容性。

## nydus基础环境搭建

1. 安装nydus-image，nydusd，nydusify，nydusctl和nydus-overlayfs。

```bash
mkdir -p kata-containers/build/nydus && cd kata-containers/build/nydus
wget https://github.com/dragonflyoss/nydus/releases/download/v2.3.0/nydus-static-v2.3.0-linux-arm64.tgz
tar -zxvf  nydus-static-v2.3.0-linux-arm64.tgz
cd nydus-static
install -D -m 755 nydusd nydus-image  nydusify nydusctl nydus-overlayfs /usr/bin
```

2. 安装containerd-nydus-grpc (nydus snapshotter)。

```bash
cd kata-containers/build/nydus
wget https://github.com/containerd/nydus-snapshotter/releases/download/v0.14.0/nydus-snapshotter-v0.14.0-linux-arm64.tar.gz
tar -zxvf  nydus-snapshotter-v0.14.0-linux-arm64.tar.gz 
install -D -m 755 bin/containerd-nydus-grpc  /usr/bin
```

3. 安装nerdctl。

```
wget https://github.com/containerd/nerdctl/releases/download/v1.7.7/nerdctl-1.7.7-linux-arm64.tar.gz
tar -zxvf nerdctl-1.7.7-linux-arm64.tar.gz
install -D -m 755 nerdctl /usr/bin
```

4. 配置nydusd，文件路径：`/etc/nydus/nydusd-config.fusedev.json`。

```bash
mkdir /etc/nydus
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

5. 获取nydus-snapshotter配置文件。

```
wget https://raw.githubusercontent.com/containerd/nydus-snapshotter/refs/tags/v0.14.0/misc/snapshotter/config.toml
```

6. 设置 nydus 的 home 目录`root`选项与本机 containerd 对应的`root`选项，此处设置与 [部署containerd并初始化k8s集群](部署containerd并初始化k8s集群.md) 中设置的containerd一致； 设置nydusd和nydus-image的实际安装路径。
```
vim config.toml

root = "/var/lib/containerd/io.containerd.snapshotter.v1.nydus"
nydusd_path= "/usr/bin/nydusd"
nydusimage_path= "/usr/bin/nydus-image"

:wq
```

## 修改 virtcca-kata-deploy 使用的 nydus 组件

virtcca-kata-deploy 会自动拉取 `containerd-nydus-grpc` 并运行，但不支持同时使用 ctr 启动 nydus 镜像。可通过以下方式替换为 v0.14.0 版本，保证 ctr 方式启动 nydus 镜像的兼容性。

1. 获取当前运行的 containerd-nydus-grpc 进程 id，并杀死该进程。
```bash
ps aux | grep containerd-nydus-grpc
kill -9 <pid>
```

2. 替换上文中自行下载的 `containerd-nydus-grpc` 二进制和配置文件
```
cp -y kata-containers/build/nydus/bin/containerd-nydus-grpc /opt/confidential-containers/bin/
cp -y config.toml /opt/confidential-containers/share/nydus-snapshotter/config-coco-guest-pulling.toml
```

3. 在`/etc/containerd/config.toml`路径下修改containerd配置文件。

```
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

4. 重启 containerd，virtcca-kata-deploy 会重新拉起更新后的 `containerd-nydus-grpc`。
```
systemctl restart containerd
```

5. 安装并启用 shared_fs。
```
yum install virtiofsd -y
cp /usr/libexec/virtiofsd /opt/kata/libexec/
sed -i 's/^\([[:space:]]*shared_fs[[:space:]]*=[[:space:]]*\)"[^"]*"/\1"virtio-fs"/' /opt/kata/share/defaults/kata-containers/configuration-qemu-virtcca.toml
```

## nydus 镜像构造

1. 使用nydusify转换自建镜像仓中的镜像格式。

```bash
nydusify convert --source registry.com:5000/busybox:latest --target registry.com:5000/busybox:latest-nydus
```

> 本文档以私有仓busybox镜像为例进行说明，实际部署请按需将`registry.com:5000/busybox:latest`自行替换为目标镜像名。

2. 使用`nydusify`检查目标镜像，命令显示验证完毕且无错误信息，说明镜像转换成功。

```bash
nydusify check --target  registry.com:5000/busybox:latest-nydus
```

![image](../../doc/zh-cn/confidential_container/figures/nydus-check.png)

## 基于nydus镜像部署容器

1. 使用nerdctl拉取nydus镜像，使用ctr运行基于kata的nydus镜像。

```bash
nerdctl pull --snapshotter=nydus registry.com:5000/busybox:latest-nydus
ctr run --snapshotter=nydus --runtime "io.containerd.kata.v2" --rm -t registry.com:5000/busybox:latest-nydus test-kata sh
```

2. 使用k8s运行基于kata的nydus镜像。

新建k8s部署文件`nydus-kata-sandbox.yaml`。

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-kata-qemu-virtcca
  annotations:
    io.containerd.cri.runtime-handler: "kata-qemu-virtcca"
    io.katacontainers.config.hypervisor.kernel_params: "agent.debug_console agent.log=debug"
spec:
  runtimeClassName: kata-qemu-virtcca
  terminationGracePeriodSeconds: 5
  containers:
  - name: box-1
    image: registry.com:5000/busybox:latest-nydus
    imagePullPolicy: Always
    command:
    - sh
    tty: true
```

部署pod。

```bash
kubectl apply -f nydus-kata-sandbox.yaml
```