#!/bin/sh

# configuration params
DEVICE="/dev/nvme0n1"
MOUNT_POINT="/mnt"  # global mount point
KATA_BASE="/run/kata-containers"
LOG_FILE="/tmp/prestart.log"
BIND_SUFFIX="pcipci_disk"

# check the device mounting status
is_device_mounted() {
    findmnt -n -o SOURCE "$DEVICE" >/dev/null 2>&1 && return 0
    return 1
}

# log function
log() {
    local level=$1
    local message=$2
    local symbol=""
    case "$level" in
        "INFO") symbol="" ;;
        "SUCCESS") symbol="" ;;
        "WARN") symbol="" ;;
        "ERROR") symbol="" ;;
    esac
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $symbol [$level] $message" | tee -a "$LOG_FILE"
}

if [ -e "/dev/nvme0n1" ]; then
    log "INFO" "Found NVMe block device /dev/nvme0n1!"

    # step1 Global Mounting of NVMe Devices (Idempotent Operation)
    if ! is_device_mounted; then
        log "INFO" "mounting $DEVICE to $MOUNT_POINT"
        mkdir -p "$MOUNT_POINT"
        if mount "$DEVICE" "$MOUNT_POINT"; then
            log "SUCCESS" "the device has been mounted to $MOUNT_POINT"
        else
            log "ERROR" "mount device failed, error code: $?"
            exit 1
        fi
    else
        log "INFO" "the device has been mounted to $MOUNT_POINT, skip"
    fi

    # step2 Accurately bind container directories
    find "$KATA_BASE" -maxdepth 2 -type d -name "rootfs" | while read -r ROOTFS_DIR; do

        # Extract Container ID(e.g. extract a86ad41... from /run/kata-containers/a86ad41.../rootfs)
        CONTAINER_ID=$(basename "$(dirname "$ROOTFS_DIR")")

        # Create a dedicated empty directory for the container
        CONTAINER_MOUNT="$MOUNT_POINT/$CONTAINER_ID"
        if [ ! -d "$CONTAINER_MOUNT" ]; then
            if ! mkdir -p "$CONTAINER_MOUNT"; then
                log "ERROR" "Create container directory failed: $CONTAINER_MOUNT"
                continue
            else
                log "SUCCESS" "Create a container-specific directory: $CONTAINER_MOUNT"
            fi
        fi

        # Check if the exclusive directory is empty (security protection)
        if [ "$(ls -A "$CONTAINER_MOUNT")" ]; then
            log "WARN" "The directory is not empty! Clear it before mounting: $CONTAINER_MOUNT"
            rm -rf $CONTAINER_MOUNT/*
        fi

        # Calculate the bound target path (e.g. /run/kata-containers/<ID>/rootfs/$BIND_SUFFIX)
        BIND_TARGET="$ROOTFS_DIR/$BIND_SUFFIX"

        # Skip the mounted directory
        if findmnt -n -o TARGET "$BIND_TARGET" >/dev/null; then
            log "INFO" "Skip Already Mounted: $BIND_TARGET"
            continue
        fi

        # Create target directory (force mode)
        if ! mkdir -p "$BIND_TARGET" 2>/dev/null; then
            log "ERROR" "Create directory failed: $BIND_TARGET"
            continue
        fi

        # Perform binding and mounting.
        if mount --bind "$CONTAINER_MOUNT" "$BIND_TARGET"; then
            log "SUCCESS" "bind successfully: $CONTAINER_MOUNT  $BIND_TARGET"
        else
            log "ERROR" "bind failed: $BIND_TARGET (error code: $?)"
        fi
    done
else
    log "INFO" "NVMe block device /dev/nvme0n1 not found!"
    exit 1
fi