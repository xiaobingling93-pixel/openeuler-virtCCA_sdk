# 机密容器支持SRIOV
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

3.  修改ctr容器 配置文件支持vfio设备冷插拔。
    `vim /etc/kata-containers/configuration.toml`
    添加：`cold_plug_vfio = "root-port"`

4.  ctr启动机密容器时通过--device透传vfio设备。

    ctr run --runtime "io.containerd.kata.v2" --device /dev/vfio/91 --rm -t docker.io/library/busybox:latest kata-test /bin/sh

    ![](figures/zh-cn_image_0000002338371509.png)

    容器中可以看到直通的VF设备ID。
