# virtCCA机密虚机支持DIM动态度量指导

## 前置步骤

CoCo远程证明支持DIM动态度量是基于virtCCA远程证明的扩展功能，用户首先需要基于virtcca完成前置步骤[kata机密容器环境搭建](https://gitee.com/openeuler/virtCCA_sdk/blob/master/kata-v3.15.0/doc/%E6%9C%BA%E5%AF%86%E5%AE%B9%E5%99%A8%E8%BF%9C%E7%A8%8B%E8%AF%81%E6%98%8E%E7%8E%AF%E5%A2%83%E9%83%A8%E7%BD%B2.md)，至少完成到步骤[容器镜像签名验签](https://gitee.com/openeuler/virtCCA_sdk/blob/master/kata-v3.15.0/doc/%E5%AE%B9%E5%99%A8%E9%95%9C%E5%83%8F%E7%AD%BE%E5%90%8D%E9%AA%8C%E7%AD%BE.md)。

### 1 CoCo远程证明使能DIM日志校验

**步骤1：** 进入到容器，参考步骤[容器化编译CoCo远程证明组件](https://gitee.com/openeuler/virtCCA_sdk/blob/master/kata-v3.15.0/doc/%E5%AE%B9%E5%99%A8%E5%8C%96%E7%BC%96%E8%AF%91CoCo%E7%BB%84%E4%BB%B6.md)：

```bash
docker exec -it coco-build-env /bin/bash
```
**步骤2：** 远程证明组件打上支持DIM校验特性的补丁：

```bash
# guest-components组件补丁
cd /home/kata-containers/build/guest-components
wget https://gitee.com/xucee/virtCCA_sdk/raw/master/kata-v3.15.0/guest-components-virtcca-dim.patch
git apply ./guest-components-virtcca-dim.patch

# trustee组件补丁
cd /home/kata-containers/build/trustee
wget https://gitee.com/xucee/virtCCA_sdk/raw/master/kata-v3.15.0/trustee-virtcca-dim.patch
git apply ./trustee-virtcca-dim.patch
```
**步骤3：** 进入容器进行编译，生成attestation-service和attestation-agent组件：

```bash
# 编译guest-components
cd /coco/build/guest-components
make clean && make build TEE_PLATFORM=virtcca

# 编译attestation-agent和attestation-service
cd /coco/build/guest-components/attestation-agent/attester
cargo build --no-default-features --features bin,virtcca-attester --bin evidence_getter --release
cd /coco/build/trustee/attestation-service && make VERIFIER=virtcca-verifier
```


### 2 机密虚机内核使能DIM动态度量

**步骤1：** 拉取对应的内核源码：

```
git clone https://gitee.com/confidential_computing/kernel.git
cd kernel
git fetch --depth 1 origin befeef1c91ee7915a328b28788a9ff2f8aa119b4
git checkout befeef1c91ee7915a328b28788a9ff2f8aa119b4

# 替换内核config
wget https://gitee.com/xucee/virtCCA_sdk/raw/master/kata-v3.15.0/conf/virtcca.config
cp virtcca.config .config
```

**步骤2：** 将DIM代码放至内核的security目录（在kernel源码目录下执行）：

```
git clone https://gitee.com/HuaxinLuGitee/dim_ra.git --depth 1
cp -r dim_ra/src/ security/dim
```

**步骤3：** 修改security目录下的编译配置（在kernel源码目录下执行）：

```
# 添加Kconfig引用
sed -i '/endmenu/i\source "security/dim/Kconfig"' security/Kconfig
# 添加Makefile引用
echo "obj-y += dim/" >> security/Makefile
# 替换内核版本的Makefile（默认为编译成内核模块）
mv -f security/dim/Makefile.kernel security/dim/Makefile
```

**步骤3：** 编译内核：

```
make Image -j $(nproc)
```
**注意：** 编译过程中会弹出DIM相关的编译选项配置交互，需要将`DIM_CORE`开启，`DIM_CORE_SIGNATURE_SUPPORT`关闭。

**步骤4：** 使用编译生成的Image替换机密虚机的内核（根据实际路径拷贝）：

```
cp arch/arm64/boot/Image /opt/kata/share/kata-containers
cd /opt/kata/share/kata-containers
ln -sf Image vmlinuz-confidential.container
```

**步骤5：** 重启机密虚机并登陆CVM（可选）：

```
略
```

**步骤6：** 检查DIM接口目录生成（可选）：

```
ls /sys/kernel/security/dim
```

### 3 机密虚机文件系统添加DIM启动配置

**步骤1：** 挂载文件系统：

```
mount -o loop,offset=3145728 /opt/kata/share/kata-containers/kata-containers-confidential.img /mnt
```

**步骤2：** 替换coco组件：

```
# 替换attestation-agent
cd /home/kata-containers/build/guest-components/target/aarch64-unknown-linux-musl/release/
cp /mnt/usr/local/bin/attestation-agent /mnt/usr/local/bin/attestation-agent.bak
cp attestation-agent /mnt/usr/local/bin/attestation-agent

# 替换grpc-as
cd /home/kata-containers/build/trustee/target/release
cp /home/coco/remote_attestation/grpc-as /home/coco/remote_attestation/grpc-as.bak
cp grpc-as /home/coco/remote_attestation/
```

**步骤3：** 创建dim策略（度量bash为例）：

```
mkdir -p /mnt/etc/dim/digest_list
echo "measure obj=BPRM_TEXT path=/usr/bin/bash" > /mnt/etc/dim/policy
```

**步骤4：** 添加systemd服务配置系统启动时执行DIM度量：

```
# 创建systemd服务
cat << EOF > /mnt/etc/systemd/system/dim.service
[Unit]
Description=DIM Init

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c "echo 1 > /sys/kernel/security/dim/baseline_init"
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
# 创建软链接，系统启动时执行
ln -sf /lib/systemd/system/dim.service /mnt/etc/systemd/system/multi-user.target.wants/
```

**步骤5：** 在virtcca的基础上配置验证dim的policy：


```
vim /opt/confidential-containers/attestation-service/token/simple/policies/opa/default.rego

package policy
import future.keywords.every
import future.keywords.if
default allow := false
allow if {
    print("Full Input:", input)
    print("Rim:", input["virtcca.realm.rim"])
    print("Ref:", data.reference)
    input["virtcca.realm.rim"] in data.reference["virtcca.realm.rim"]

    every item in input["virtcca.dim"] {
        item in data.reference["virtcca.dim"]
    }
}
```
**步骤6：** 通过[dim_tools](https://gitee.com/openeuler/dim_tools#/openeuler/dim_tools/blob/master/doc/cmd.md)工具生成dim基线值

```
dim_gen_baseline /usr/bin/bash
dim USER sha256:1922b9243799a576fcd2f0eae047adad09868dd106cc1b4f13d457bad225292e /usr/bin/bash
```
**步骤7：** 通过rvps工具添加dim基线值（可与rim基线值一起添加），将步骤6生成的sha256的哈希值写到到virtcca.dim列表中。

```bash
cd /home/coco/remote_attestation
cat << EOF > sample
{
    "virtcca.realm.rim": [
        "59cbfed47932c52b6d36723727a6abe67547c22e6569b423562376e87ed8b3d5"
    ],
    "virtcca.dim" : [
        "2491ef77532db575c87ecf9cf9a5778a6592ad8dddd51ac827587ce3ff5f3e37",
        "8eceea7c8658ea28f8a9494c514c73983803fd949dc6c35f7aa936e34b0d99cb"
    ]
}
EOF
provenance=$(cat sample | base64 --wrap=0)
cat << EOF > message
{
    "version" : "0.1.0",
    "type": "sample",
    "payload": "$provenance"
}
EOF
./rvps-tool register --path ./message --addr http://127.0.0.1:50003
```
**步骤8：** 修改yaml文件，添加内核启动参数`dim_measure_rot=virtcca dim_measure_pcr=4 dim_measure_only=1`：

```
io.katacontainers.config.hypervisor.kernel_params: "agent.debug_console agent.log=debug dim_measure_rot=virtcca dim_measure_pcr=4 dim_measure_only=1"
```

**步骤9：** 卸载挂载点，启动coco组件拉起容器

```bash
umount /mnt
kubectl apply -f xxxx.yaml
```
