#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

LOGFILE=/tmp/oe-guest-setup.txt
FORCE_RECREATE=false
TMP_GUEST_IMG_PATH="/tmp/openEuler-24.03-LTS-SP1-aarch64.qcow2"
SIZE=0
TMP_MOUNT_PATH="/tmp/vm_mount"
CREATE_IMAGE=true
MEASURE_IMAGE=true
KAE_ENABLE=false
EULER_VERSION=""

ok() {
    echo -e "\e[1;32mSUCCESS: $*\e[0;0m"
}

error() {
    echo -e "\e[1;31mERROR: $*\e[0;0m"
    cleanup
    exit 1
}

warn() {
    echo -e "\e[1;33mWARN: $*\e[0;0m"
}

info() {
    echo -e "\e[0;33mINFO: $*\e[0;0m"
}

check_tool() {
    [[ "$(command -v $1)" ]] || { error "$1 is not installed" 1>&2 ; }
}

usage() {
    cat <<EOM
Usage: $(basename "$0") [OPTION]...
  -h                        Show this help
  -i <input image>          Specify input qcow2 image for measurement
  -f                        Force to recreate the output image
  -s                        Specify the size of guest image
  -v                        openEuler version (24.03, 24.09, ...)
  -p                        Set the password of guest image
  -k                        Install kae driver
  -o <output file>          Specify the output file, default is openEuler-<version>-aarch64.qcow2.
                            Please make sure the suffix is qcow2. Due to permission consideration,
                            the output file will be put into /tmp/<output file>.
EOM
}

process_args() {
    while getopts "v:i:o:s:u:p:fchk" option; do
        case "$option" in
        i) INPUT_IMAGE=$(realpath "$OPTARG") ;;
        o) GUEST_IMG_PATH=$(realpath "$OPTARG") ;;
        s) SIZE=${OPTARG} ;;
        f) FORCE_RECREATE=true ;;
        k) KAE_ENABLE=true ;;
        v) EULER_VERSION=${OPTARG} ;;
        p) GUEST_PASSWORD=${OPTARG} ;;
        h)
            usage
            exit 0
            ;;
        *)
            echo "Invalid option '-${OPTARG}'"
            usage
            exit 1
            ;;
        esac
    done

    if [[ -n "${INPUT_IMAGE}" ]]; then
        CREATE_IMAGE=false
        MEASURE_IMAGE=true
    fi

    if [[ -z "${INPUT_IMAGE}" ]]; then
        INPUT_IMAGE=${TMP_GUEST_IMG_PATH}
    fi

    if [[ -z "${KERNEL_VERSION}" ]]; then
        KERNEL_VERSION="6.6.0-72.0.0.76.oe2403sp1.aarch64"
    fi

    if [[ ${CREATE_IMAGE} = "true" && -z "${EULER_VERSION}" ]]; then
        error "Please specify the openEuler release by setting EULER_VERSION or passing it via -v"
    fi

    # generate variables
    ORIGINAL_IMG="openEuler-${EULER_VERSION}-aarch64.qcow2"
    ORIGINAL_IMG_PATH=$(realpath "${SCRIPT_DIR}/${ORIGINAL_IMG}")

    # output guest image, set it if user does not specify it
    if [[ -z "${GUEST_IMG_PATH}" ]]; then
        GUEST_IMG_PATH=$(realpath "openEuler-${EULER_VERSION}-cvm-aarch64.qcow2")
    fi

    if [[ "${ORIGINAL_IMG_PATH}" == "${GUEST_IMG_PATH}" ]]; then
        error "Please specify a different name for guest image via -o"
    fi

    if [[ ${GUEST_IMG_PATH} != *.qcow2 ]]; then
        error "The output file should be qcow2 format with the suffix .qcow2."
    fi
}

download_image() {
    # Get the checksum file first
    if [[ -f ${SCRIPT_DIR}/"openEuler-${EULER_VERSION}-aarch64.qcow2.xz.sha256sum" ]]; then
        rm ${SCRIPT_DIR}/"openEuler-${EULER_VERSION}-aarch64.qcow2.xz.sha256sum"
    fi

    OFFICIAL_openEuler_IMAGE="https://repo.openeuler.org/openEuler-${EULER_VERSION}/virtual_machine_img/aarch64/"
    wget "${OFFICIAL_openEuler_IMAGE}/openEuler-${EULER_VERSION}-aarch64.qcow2.xz.sha256sum" -O ${SCRIPT_DIR}/openEuler-${EULER_VERSION}-aarch64.qcow2.xz.sha256sum --no-check-certificate

    while :; do
        # Download the image if not exists
        if [[ ! -f ${ORIGINAL_IMG_PATH} ]]; then
            wget -O ${ORIGINAL_IMG_PATH}.xz ${OFFICIAL_openEuler_IMAGE}/${ORIGINAL_IMG}.xz --no-check-certificate
        fi

        # calculate the checksum
        download_sum=$(sha256sum ${ORIGINAL_IMG_PATH}.xz | awk '{print $1}')
        found=false
        while IFS= read -r line || [[ -n "$line" ]]; do
            if [[ "$line" == *"$ORIGINAL_IMG"* ]]; then
                if [[ "${line%% *}" != ${download_sum} ]]; then
                    echo "Invalid download file according to sha256sum, re-download"
                    rm ${ORIGINAL_IMG_PATH}
                else
                    ok "Verify the checksum for openEuler image."
                    xz -dk ${ORIGINAL_IMG_PATH}.xz
                    return
                fi
                found=true
            fi
        done < ${SCRIPT_DIR}/"openEuler-${EULER_VERSION}-aarch64.qcow2.xz.sha256sum"
        if [[ $found != "true" ]]; then
            echo "Invalid SHA256SUM file"
            exit 1
        fi
    done
}

resize_guest_image() {
    if [ "$SIZE" -eq 0 ]; then
        ok "Skipped resize as SIZE is 0"
        return
    fi

    qemu-img resize ${TMP_GUEST_IMG_PATH} +${SIZE}G
    virt-customize -a ${TMP_GUEST_IMG_PATH} \
        --run-command 'echo "sslverify=false" >> /etc/yum.conf' \
        --install cloud-utils-growpart \
        --run-command 'growpart /dev/sda 2' \
        --run-command 'resize2fs /dev/sda2' \
        --run-command 'systemctl mask pollinate.service'
    if [ $? -eq 0 ]; then
        ok "Resize the guest image to ${SIZE}G"
    else
        error "Failed to resize guest image to ${SIZE}G"
    fi
}

create_guest_image() {
    if [ ${FORCE_RECREATE} = "true" ]; then
        rm -f ${ORIGINAL_IMG_PATH}
    fi

    download_image

    install -m 0777 ${ORIGINAL_IMG_PATH} ${TMP_GUEST_IMG_PATH}
    if [ $? -eq 0 ]; then
        ok "Copy the ${ORIGINAL_IMG} => ${TMP_GUEST_IMG_PATH}"
    else
        error "Failed to copy ${ORIGINAL_IMG} to /tmp"
    fi

    resize_guest_image
}

setup_guest_image() {
    info "Run setup scripts inside the guest image. Please wait ..."
    virt-customize -a ${TMP_GUEST_IMG_PATH} \
       --run-command 'grub2-mkimage -d /usr/lib/grub/arm64-efi -O arm64-efi --output=/boot/efi/EFI/openEuler/grubaa64.efi --prefix="(,msdos1)/efi/EFI/openEuler" fat part_gpt part_msdos linux tpm' \
       --run-command 'cp -f /boot/efi/EFI/openEuler/grubaa64.efi /boot/EFI/BOOT/BOOTAA64.EFI' \
       --run-command "sed -i '/linux.*vmlinuz-6.6.0/ s/$/ ima_rot=tpm cma=64M virtcca_cvm_guest=1 cvm_guest=1 swiotlb=65536,force loglevel=8/' /boot/efi/EFI/openEuler/grub.cfg" \
       --run-command "sed -i '/^GRUB_CMDLINE_LINUX=/ s/\"$/ ima_rot=tpm cma=64M virtcca_cvm_guest=1 cvm_guest=1 swiotlb=65536,force loglevel=8\"/' /etc/default/grub" \
       --run-command 'echo "sslverify=false" >> /etc/yum.conf'
    if [ $? -eq 0 ]; then
        ok "Run setup scripts inside the guest image"
    else
        error "Failed to setup guest image"
    fi
}

set_guest_password() {
    if [[ -z "${GUEST_PASSWORD}" ]]; then
        return
    fi

    virt-customize -a ${TMP_GUEST_IMG_PATH} \
       --password root:password:${GUEST_PASSWORD} \
       --password-crypto sha512
}

install_kae_driver() {
    local target_image=${1}

    mkdir -p ${TMP_MOUNT_PATH}
    guestmount -a ${target_image} -i ${TMP_MOUNT_PATH} || error "Failed to mount the VM image."

    info "Downloading and Making KAE driver"
    git clone https://gitee.com/openeuler/virtCCA_driver.git --depth 1
    cd virtCCA_driver/kae_driver
    make

    cp hisi_plat_qm.ko      ${TMP_MOUNT_PATH}/lib/modules/${KERNEL_VERSION}/extra/
    cp hisi_plat_sec.ko     ${TMP_MOUNT_PATH}/lib/modules/${KERNEL_VERSION}/extra/
    cp hisi_plat_hpre.ko    ${TMP_MOUNT_PATH}/lib/modules/${KERNEL_VERSION}/extra/

    cat > ${TMP_MOUNT_PATH}/etc/modules-load.d/virtcca-kae.conf << EOF
uacce
hisi_plat_qm
hisi_plat_sec
hisi_plat_hpre
EOF

    cat > ${TMP_MOUNT_PATH}/etc/modprobe.d/virtcca-kae-deps.conf << EOF
softdep hisi_plat_qm pre: uacce
softdep hisi_plat_sec pre: hisi_plat_qm
softdep hisi_plat_hpre pre: hisi_plat_sec
EOF

    guestunmount ${TMP_MOUNT_PATH}
    guestfish --rw -i -a ${target_image} << EOF
sh "depmod -a ${KERNEL_VERSION}"
EOF

    cd $SCRIPT_DIR
    ok "Install KAE driver successfully."
}

measure_guest_image() {
    local target_image=${1}

    info "Starting measurement process for: ${target_image}"
    guestunmount ${TMP_MOUNT_PATH} 2>/dev/null || true
    gcc measure_pe.c -o MeasurePe -lcrypto
    mkdir -p ${TMP_MOUNT_PATH}

    guestmount -a ${target_image} -i ${TMP_MOUNT_PATH} || error "Failed to mount the VM image."

    # measure grub
    BOOT_EFI_PATH="${TMP_MOUNT_PATH}/boot/EFI/BOOT/BOOTAA64.EFI"
    [[ -f "${BOOT_EFI_PATH}" ]] || error "BOOTAA64.EFI not found"
    sha_grub=$(./MeasurePe "${BOOT_EFI_PATH}" | awk -F"SHA-256 = " '{print $2}')

    # measure grub.cfg
    GRUB_CFG_PATH="${TMP_MOUNT_PATH}/boot/efi/EFI/openEuler/grub.cfg"
    [[ -f "${GRUB_CFG_PATH}" ]] || error "grub.cfg not found"
    sha_grub_cfg=$(sha256sum "${GRUB_CFG_PATH}" | awk '{print $1}')

    mkdir -p "${TMP_MOUNT_PATH}/tmp/kernel_uncompressed"

    # initialize json
    JSON_TEMPLATE='{"grub": "%s", "grub.cfg": "%s", "kernels": [], "hash_alg": "sha-256"}'
    printf "${JSON_TEMPLATE}" "${sha_grub}" "${sha_grub_cfg}" > image_reference_measurement.json

    find "${TMP_MOUNT_PATH}/boot" -name 'vmlinuz-*' -not -name 'vmlinuz-*rescue*' | while read kernel_path; do
        kernel_file=$(basename "${kernel_path}")
        version="${kernel_file#vmlinuz-}"

        # measure kernel
        uncompressed_path="${TMP_MOUNT_PATH}/tmp/kernel_uncompressed/${kernel_file}"
        gunzip -c "${kernel_path}" > "${uncompressed_path}" 2>/dev/null
        if [ $? -ne 0 ]; then
            warn "Failed to uncompress kernel: ${kernel_file}"
            continue
        fi
        kernel_hash=$(sha256sum "${uncompressed_path}" | awk '{print $1}')
        rm -f "${uncompressed_path}"

        # measure initramfs
        initramfs_path="${TMP_MOUNT_PATH}/boot/initramfs-${version}.img"
        if [ -f "${initramfs_path}" ]; then
            initramfs_hash=$(sha256sum "${initramfs_path}" | awk '{print $1}')
        else
            warn "Missing initramfs for kernel: ${version}"
            initramfs_hash="NOT_FOUND"
        fi

        # update json
        jq --arg version "${version}" \
           --arg kernel "${kernel_hash}" \
           --arg initramfs "${initramfs_hash}" \
           '.kernels += [{
               "version": $version,
               "kernel": $kernel,
               "initramfs": $initramfs
           }]' \
           image_reference_measurement.json > tmp.json && mv tmp.json image_reference_measurement.json
    done

    rm -rf "${TMP_MOUNT_PATH}/tmp/kernel_uncompressed"
    guestunmount ${TMP_MOUNT_PATH}
}

cleanup() {
    if [[ -f ${SCRIPT_DIR}/"openEuler-${EULER_VERSION}-aarch64.qcow2.xz.sha256sum" ]]; then
        rm ${SCRIPT_DIR}/"openEuler-${EULER_VERSION}-aarch64.qcow2.xz.sha256sum"
    fi

    if [[ -f ${SCRIPT_DIR}/"openEuler-${EULER_VERSION}-aarch64.qcow2.xz" ]]; then
        rm ${SCRIPT_DIR}/"openEuler-${EULER_VERSION}-aarch64.qcow2.xz"
        rm ${SCRIPT_DIR}/"openEuler-${EULER_VERSION}-aarch64.qcow2"
    fi
    info "Cleanup!"
}

    process_args "$@"

if [ ${CREATE_IMAGE} == true ]; then
    rm -f ${LOGFILE}
    echo "=== cvm guest image generation === " > ${LOGFILE}

    # install required tools
    yum install -y libguestfs-tools virt-install qemu-img genisoimage guestfs-tools cloud-utils-growpart jq &>> ${LOGFILE}

    check_tool qemu-img
    check_tool virt-customize
    check_tool virt-install

    info "Installation of required tools"

    create_guest_image

    setup_guest_image

    set_guest_password
fi

if [ ${KAE_ENABLE} == true ]; then
    install_kae_driver "${INPUT_IMAGE}"
fi

if [[ ${MEASURE_IMAGE} == true ]]; then
    measure_guest_image "${INPUT_IMAGE}"
    ok "The measurement process is done"
    if [ ${CREATE_IMAGE} == false ]; then
        exit 0
    fi
fi

cleanup

mv ${TMP_GUEST_IMG_PATH} ${GUEST_IMG_PATH}

ok "cvm guest image : ${GUEST_IMG_PATH}"
