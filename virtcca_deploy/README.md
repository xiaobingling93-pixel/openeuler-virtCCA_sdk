# VIRTCCA DEPLOY

virtcca 机密虚机自动化部署工具

## 安装部署
建议创建虚拟环境运行，首次运行执行以下命令生成虚拟环境
```
python -m venv virtcca-deploy-env
```

激活虚拟环境
```
source virtcca-deploy-env/bin/activate
```

安装virtcca deploy
```
yum install python3-devel -y
pip install .
mkdir -p /etc/virtcca_deploy/
cp conf/* /etc/virtcca_deploy/
```

### 配置虚拟机运行环境和虚拟机镜像
通过执行下面脚本自动安装libvirt、qemu等组件
可以自主配置镜像大小（默认10G），镜像版本（默认版本为Host操作系统版本）

```
cd scripts
bash tmm_cvm_env_setup.sh
```

注：
1.检查libvirt、qemu权限设置，确保计算节点能够正常运行机密虚机
2.检查系统防护墙和selinux配置，管理节点使用5001端口，计算节点使用5000端口，确保对应端口能够正常访问

### 管理节点运行virtcca-manager
获取管理节点域名
```
hostname
```

配置https证书与秘钥，加入本节点证书和秘钥，以及计算节点证书
```
mkdir -p /etc/virtcca_deploy/cert/
cp manager.crt /etc/virtcca_deploy/cert/
cp manager.key /etc/virtcca_deploy/cert/
cp compute.crt /etc/virtcca_deploy/cert/
```

运行virtcca-manager
```
virtcca-manager
```

### 计算节点运行virtcca-compute

配置https证书与秘钥，加入本节点证书和秘钥，以及管理节点证书
```
mkdir -p /etc/virtcca_deploy/cert/
cp compute.crt /etc/virtcca_deploy/cert/
cp compute.key /etc/virtcca_deploy/cert/
cp manager.crt /etc/virtcca_deploy/cert/
```

配置管理节点域名
```
vim /etc/virtcca_deploy/virtcca_deploy.conf
manager = ${manager_domain}
```

运行virtcca-compute
```
virtcca-compute
```

## 通信矩阵
源设备：机密虚机运维部署管理节点
源IP地址：机密虚机运维部署管理节点IP地址
源端口：1024~65535（默认值5001）
目的设备：机密虚机运维部署计算节点
目的IP地址：机密虚机运维部署计算节点IP地址
目的端口（侦听）：5000
协议：TCP
端口说明：用于机密虚机运维部署管理节点和计算节点间机密虚机运维命令交互
侦听端口是否可更改：否
认证方式：TLS
加密方式：TLS_AES_256_GCM_SHA_384
所属平面：控制面
版本：所有版本
特殊场景：无

