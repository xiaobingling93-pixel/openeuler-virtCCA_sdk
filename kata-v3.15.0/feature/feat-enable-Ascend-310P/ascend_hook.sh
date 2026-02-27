#!/bin/sh

# configuration params
DEVICE="/dev/hisi_hdc"
KATA_BASE="/run/kata-containers"
LOG_FILE="/tmp/prestart.log"

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

if [ -e "$DEVICE" ]; then
    sleep 3s
    log "INFO" "Found Ascend device $DEVICE!"
    npu-smi info
    sleep 2s

    # step2 Accurately bind container directories
    find "$KATA_BASE" -maxdepth 2 -type d -name "rootfs" | while read -r ROOTFS_DIR; do

        # Extract Container ID(e.g. extract a86ad41... from /run/kata-containers/a86ad41.../rootfs)
        CONTAINER_ID=$(basename "$(dirname "$ROOTFS_DIR")")

        #-------------------------------------------------------------#
        # Calculate the bound target path
        BIND_TARGET="$ROOTFS_DIR/usr/local/bin"
        # Skip the mounted directory
        if findmnt -n -o TARGET "$BIND_TARGET/npu-smi" >/dev/null; then
            log "INFO" "Skip Already Mounted: $CONTAINER_ID $BIND_TARGET/npu-smi"
            continue
        fi

        # Create target directory (force mode)
        if ! mkdir -p "$BIND_TARGET" 2>/dev/null; then
            log "ERROR" "Create directory failed: $BIND_TARGET"
            continue
        fi

        touch "$BIND_TARGET/npu-smi"

        # Perform binding and mounting.
        if mount --bind "/usr/local/bin/npu-smi" "$BIND_TARGET/npu-smi"; then
            log "SUCCESS" "bind successfully: $CONTAINER_ID  $BIND_TARGET/npu-smi"
        else
            log "ERROR" "bind failed: $BIND_TARGET/npu-smi (error code: $?)"
        fi

        #-------------------------------------------------------------#
        BIND_TARGET="$ROOTFS_DIR/usr/local/dcmi"
        # Create target directory (force mode)
        if ! mkdir -p "$BIND_TARGET" 2>/dev/null; then
            log "ERROR" "Create directory failed: $BIND_TARGET"
            continue
        fi
        # Perform binding and mounting.
        if mount --bind "/usr/local/dcmi" "$BIND_TARGET"; then
            log "SUCCESS" "bind successfully: $CONTAINER_ID  $BIND_TARGET"
        else
            log "ERROR" "bind failed: $BIND_TARGET (error code: $?)"
        fi

        #-------------------------------------------------------------#
        BIND_TARGET="$ROOTFS_DIR/usr/local/Ascend/driver"
        # Create target directory (force mode)
        if ! mkdir -p "$BIND_TARGET" 2>/dev/null; then
            log "ERROR" "Create directory failed: $BIND_TARGET"
            continue
        fi
        # Perform binding and mounting.
        if mount --bind "/usr/local/Ascend/driver" "$BIND_TARGET"; then
            log "SUCCESS" "bind successfully: $CONTAINER_ID  $BIND_TARGET"
        else
            log "ERROR" "bind failed: $BIND_TARGET (error code: $?)"
        fi

        #-------------------------------------------------------------#
        BIND_TARGET="$ROOTFS_DIR/etc/"

        touch "$BIND_TARGET/ascend_install.info"
        # Perform binding and mounting.
        if mount --bind "/etc/ascend_install.info" "$BIND_TARGET/ascend_install.info"; then
            log "SUCCESS" "bind successfully: $CONTAINER_ID  $BIND_TARGET/ascend_install.info"
        else
            log "ERROR" "bind failed: $BIND_TARGET/ascend_install.info (error code: $?)"
        fi
        #-------------------------------------------------------------#
        # touch "$ROOTFS_DIR/etc/profile"
        # echo 'export LD_LIBRARY_PATH=/usr/local/Ascend/driver/lib64/driver:/usr/local/Ascend/driver/lib64/common:$LD_LIBRARY_PATH' >> "$ROOTFS_DIR/etc/profile"
        touch "$ROOTFS_DIR/root/.bashrc"
        echo 'export LD_LIBRARY_PATH=/usr/local/Ascend/driver/lib64/driver:/usr/local/Ascend/driver/lib64/common:$LD_LIBRARY_PATH' >> "$ROOTFS_DIR/root/.bashrc"
    done
else
    log "INFO" "Ascend device $DEVICE not found!"
    exit 1
fi
