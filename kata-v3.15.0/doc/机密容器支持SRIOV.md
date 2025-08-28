# 机密容器支持SRIOV
## 规格约束
kata项目约定了`maxPCIeRootPort=16`，且kata容器的两个网口（lo、eth0）固定占用2个`PCIeRootPort`，故单个pod最大支持cdi注入14个vfio设备。

## 创建vfio设备

1.  `VirtCCA`设备直通环境配置。
    1）修改内核启动参数
	vim /boot/efi/EFI/openEuler/grub.cfg
	Host OS内核启动参数添加：`virtcca_cvm_host=1 arm_smmu_v3.disable_ecmdq=1 vfio_pci.disable_idle_d3=1`
    2）BIOS使能SMMU
	BIOS用户界面路径：`Advanced > MISC Config > Support Smmu`，设置`Support Smmu`为`Enabled`
2.  当前以网卡为例给出创建VF并绑定vfio驱动操作。
    1.  查看ConnectX-6网卡的BDF号。

        lspci -tv | grep ConnectX-6

        domin为0000，两个BDF号分别为ab:00.0和ab:00.1。

        ![](figures/zh-cn_image_0000002304611994.png)

    2.  获取BDF号对应的网卡名称。

        ll /sys/class/net/ | grep ab:00.0

        ![](figures/zh-cn_image_0000002304452274.png)

    3.  创建VF设备，VF\_NUM数量用户按需自行决定。

        echo $\{VF\_NUM\} \> /sys/class/net/enp171s0f0np0/device/sriov\_numvfs

        ![](figures/zh-cn_image_0000002338371517.png)

    4.  将待直通的VF从内核默认网络驱动解绑。

        echo 0000:ab:00.2 \> /sys/bus/pci/devices/0000\\:ab\\:00.2/driver/unbind

        ![](figures/zh-cn_image_0000002304452282.png)

    5.  查看待直通VF的设备ID。

        lspci -ns ab:00.2

        ![](figures/zh-cn_image_0000002304611962.png)

    6.  加载vfio驱动。

        modprobe vfio-pci

    7.  将前述获取的设备ID绑定到vfio驱动。

        echo 15b3 101e \> /sys/bus/pci/drivers/vfio-pci/new\_id

    8.  查看成功绑定的vfio设备。

        ll /dev/vfio/

        ![](figures/zh-cn_image_0000002304611986.png)

> 前提条件：已参照**kata-deploy自动化部署**章节完成机密容器环境部署
## ctr命令启动使能SRIOV的机密容器
1.  修改ctr默认容器运行时配置文件支持vfio设备冷插拔。
    `vim /etc/kata-containers/configuration.toml`
    在`hypervisor.qemu`标签下添加：`cold_plug_vfio = "root-port"`

2.  ctr启动机密容器时通过--device透传vfio设备。

    ctr run --runtime "io.containerd.kata.v2" --device /dev/vfio/91 --rm -t docker.io/library/busybox:latest kata-test /bin/sh

    ![](figures/zh-cn_image_0000002338371509.png)

    容器中可以看到直通的VF设备ID。


## k8s启动使能SRIOV的机密容器
1. 修改`kata-qemu-virtcca`容器运行时配置文件支持vfio设备冷插拔。
    `vim /opt/kata/share/defaults/kata-containers/configuration-qemu-virtcca.toml`
    在`hypervisor.qemu`标签下添加：`cold_plug_vfio = "root-port"`

2. 修改containerd配置文件以支持cdi设备注入的注解。
    `vim /etc/containerd/config.toml`
    在`.containerd.runtimes.kata-qemu-virtcca`标签下作如下修改：
    - 新增：`privileged_without_host_devices_all_devices_allowed = true`
    - pod_annotations中新增：`"cdi.k8s.io/vfio*"`

    完成修改后的内容如下：
```shell
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata-qemu-virtcca]
runtime_type = "io.containerd.kata-qemu.v2"
runtime_path = "/opt/kata/bin/containerd-shim-kata-v2"
privileged_without_host_devices = true
privileged_without_host_devices_all_devices_allowed = true
pod_annotations = ["io.katacontainers.*", "cdi.k8s.io/vfio*"]
```
`systemctl daemon-reload && systemctl restart containerd` 使配置生效。
**注意：系统reboot后，containerd的配置会恢复到初始状态，上述修改需要重新配置。**

3. 新增cdi设备注入配置文件
```shell
mkdir -p /etc/cdi
cp ./virtCCA_sdk/kata-v3.15.0/conf/pcipc-nic.json ./virtCCA_sdk/kata-v3.15.0/conf/pcipc-nvme.json /etc/cdi
```
1）/etc/cdi下网卡和磁盘设备配置文件中用户需要关注并针对性修改的是：
- name：该设备的唯一标志，不同设备name彼此不同，容器配置中通过指定name来注入对应设备。
- path：该设备对应的vfio路径，参考上文**创建vfio设备**小节创建该路径。

2）cdi配置文件中的devices数组支持添加多个设备的描述，多设备配置参考如下：
```json
{
  "cdiVersion": "0.6.0",
  "kind": "pcipc/nic",
  "devices": [
    {
      "name": "1",
      "containerEdits": {
        "deviceNodes": [
          {
            "path": "/dev/vfio/77"
          }
        ]
      }
    },
    {
      "name": "2",
      "containerEdits": {
        "deviceNodes": [
          {
            "path": "/dev/vfio/78"
          }
        ]
      }
    },
    {
      "name": "3",
      "containerEdits": {
        "deviceNodes": [
          {
            "path": "/dev/vfio/79"
          }
        ]
      }
    }
  ]
}
```
对应的容器配置文件.yaml中`cdi.k8s.io/vfio-pcipc`注解写法为：`cdi.k8s.io/vfio-pcipc: "pcipc/nic=1,pcipc/nic=2,pcipc/nic=3"`

4. k8s启动机密容器并直通网卡
步骤：
- 1）完成vfio设备创建。
- 2）修改`/etc/cdi/pcipc-nic.json`完成待直通的vfio设备配置（name和path）。
- 3）容器配置文件.yaml中新增`cdi.k8s.io/vfio-pcipc`注解和initContainer预配网（可选），示例配置如下：
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-kata-qemu-virtcca
  annotations:
    io.containerd.cri.runtime-handler: "kata-qemu-virtcca"
    cdi.k8s.io/vfio-pcipc: "pcipc/nic=1" # 1即/etc/cdi/pcipc-nic.json中的name字段内容
spec:
  runtimeClassName: kata-qemu-virtcca
  terminationGracePeriodSeconds: 5
  initContainers: # 用于使用直通的网卡预配置网络（可选）
  - name: network-setup
    image: registry.hw.com:5000/ubuntu-net:latest
    imagePullPolicy: Always
    securityContext:
      privileged: true
    command: ["sh", "-c"]
    args: ["ip link set eth1 up && ip addr add 192.168.100.90/24 dev eth1"]
  containers:
  - name: box-1
    image: registry.hw.com:5000/busybox:latest
    imagePullPolicy: Always
    command:
    - sh
    tty: true
```
- 4）启动机密容器，进到容器中ip a可以看到直通的网卡。

5. k8s启动机密容器并直通nvme磁盘步骤：
- 1）完成vfio设备创建。
- 2）修改`/etc/cdi/pcipc-nvme.json`完成待直通的vfio设备配置（name和path）。
- 3）修改`kata-qemu-virtcca`容器运行时配置文件打开guest_hook_path注释：
    `vim /opt/kata/share/defaults/kata-containers/configuration-qemu-virtcca.toml`，确保`hypervisor.qemu`标签下：`guest_hook_path = "/usr/share/oci/hooks"`。
- 4）部署磁盘挂载hook脚本到文件系统：
```shell
# 确定待直通的nvme磁盘名（需支持SRIOV），针对性修改`./virtCCA_sdk/kata-v3.15.0/conf/pcipc-nvme-hook.sh`中的`$DEVICE`宏定义值
mount -o loop,offset=3145728 /opt/kata/share/kata-containers/kata-containers-confidential.img /mnt
mkdir -p /mnt/usr/share/oci/hooks/prestart
cd virtCCA_sdk
chmod 755 ./kata-v3.15.0/conf/pcipc-nvme-hook.sh && cp ./kata-v3.15.0/conf/pcipc-nvme-hook.sh /mnt/usr/share/oci/hooks/prestart
umount /mnt
```
- 5）容器配置文件.yaml中新增`cdi.k8s.io/vfio-pcipc`注解，示例配置如下：
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-kata-qemu-virtcca
  annotations:
    io.containerd.cri.runtime-handler: "kata-qemu-virtcca"
    cdi.k8s.io/vfio-pcipc: "pcipc/nvme=1" # 1即/etc/cdi/pcipc-nvme.json中的name字段内容
spec:
  runtimeClassName: kata-qemu-virtcca
  terminationGracePeriodSeconds: 5
  containers:
  - name: box-1
    image: registry.hw.com:5000/busybox:latest
    imagePullPolicy: Always
    command:
    - sh
    tty: true
```
6）启动机密容器，容器根目录下新增`pcipci_disk`目录，即直通磁盘的挂载点，可直接读写。
