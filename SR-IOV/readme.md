# virtCCA SR-IOV支持

## 介绍
基于https://gitee.com/openeuler/kernel.git的OLK-6.6分支，commit基线：bcdbfa3e5a519b58c72f39ffe56dd3b09d5b38c1

## 使用说明
1. SP680驱动
    ```sh
    cd ${HOST_KERNEL_PATH}
    git am ${VIRTCCA_SDK_PATCH}/SR-IOV/SP680-support-virtCCA-SRIOV.patch
    # comiler and install kernel
    ```

2. MLNX驱动
    ```sh
    cd ${HOST_KERNEL_PATH}
    git am ${VIRTCCA_SDK_PATCH}/SR-IOV/MLNX5-support-virtCCA-SRIOV.patch
    # comiler and install kernel
    ```

3. NVMe驱动
    ```sh
    cd ${HOST_KERNEL_PATH}
    git am ${VIRTCCA_SDK_PATH}/SR-IOV/NVMe-support-virtCCA-SRIOV.patch
    # comiler and install kernel
    ```
