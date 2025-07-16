
# CVM Image Customization Tool

This tool is used to create, customize and/or measure the openEuler based CVM image (.qcow2) to support virtCCA grub boot and attestation. It provides two main functions: 

- **Image Customization:** it converts an openEuler VM image (downloaded from an official repo) into a CVM image, resizes it by adding extra space, customizes boot configurations, and sets the root password.

- **Image Measurement:** it computes the SHA-256 hashes of components in CVM image, such as GRUB EFI binary (BOOTAA64.EFI), grub configuration (grub.cfg), kernels and corresponding initramfs images. These hashes are saved in a JSON file (image_reference_measurement.json), and will be used as reference measurements in attestation. 

*Note: If an input image is specified with the -i option, the script skips the image creation process and only performs the measurement.*

## Prerequisites

Please install the following packages on the openEuler host.

```shell
yum install -y libguestfs-tools virt-install qemu-img genisoimage guestfs-tools cloud-utils-growpart jq
```

## Usage

Run the script from the command line with the appropriate options:

```shell
$ sh create-oe-image.sh -h
Usage: create-oe-image.sh [OPTION]...
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
```

Example Commands

- Create a new CVM image and and measure it:

```shell
sh create-oe-image.sh -v 24.03-LTS-SP2 -s 10 -p Password -o /tmp/virtcca_cvm_image.qcow2
```

- Measure an existing CVM image only:

```shell
sh create-oe-image.sh -i /path/to/virtcca_cvm_image.qcow2
```

## Workflow

### Image Customization

- `create_guest_image`

This function downloads the official openEuler image (.qcow2) and its associated SHA256 checksum file from the openEuler repository. It verifies the checksum to ensure integrity. If verification fails, it re-downloads the image.

The verified image is copied to a temporary location and resized using `qemu-img` by adding the specified additional space. The script uses `virt-customize` to modify configuration files, install necessary utilities, expand partitions and resize the filesystem, etc.

- `setup_guest_image`

This function customizes the boot process by (1) generating a new grub image with builtin tpm module, (2) appending kernel cmdline parameters to support virtCCA boot, e.g., `cma=64M virtcca_cvm_guest=1 cvm_guest=1 swiotlb=65536,force loglevel=8`.

- `set_guest_password`

The root password is set (with an option for SHA-512 encryption) using `virt-customize`.

### Image Measurement

This function mounts the CVM image using `guestmount`, then measures its boot components.

- Grub image and Configuration Measurements:

It compiles a C program (measure_pe.c) to create the MeasurePe binary used to calculate the SHA-256 hash of the GRUB EFI binary (BOOTAA64.EFI). It also computes the SHA-256 hash for the GRUB configuration file.

- Kernel and Initramfs image Measurements:

This function scans the `/boot` directory within the mounted image for kernel images (excluding rescue kernels).

For each found kernel (named vmlinuz-*), it attempts to uncompress the image, calculates its SHA-256 hash, and then measures the corresponding initramfs image.

These measurements are aggregated into a JSON file named image_reference_measurement.json with the following structure:

```json
{
    "grub": "<GRUB EFI hash>",
    "grub.cfg": "<GRUB config hash>",
    "kernels": [
        {
            "version": "<kernel version>",
            "kernel": "<kernel hash>",
            "initramfs": "<initramfs hash or NOT_FOUND>"
        },
        ...
    ],
    "hash_alg": "sha-256"
}
```
This JSON file will be used in attestation, serving as golden measurements of the CVM image.

## Notes

You can modify the `create-oe-image.sh` to apply further customizations as needed.
