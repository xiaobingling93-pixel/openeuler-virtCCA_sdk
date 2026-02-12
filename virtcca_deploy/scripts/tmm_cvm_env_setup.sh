#!/bin/bash
# ============================
# Environment Variables Configuration
# ============================
# Default image parameters
IMAGE_SIZE="10"
ROOT_PASSWORD=""          # Don't set password by default
OUTPUT_PATH=""            # Default to current script path
FINAL_DESTINATION="/etc/virtcca_deploy"      # Final image storage directory
FORCE_RECREATE="false"    # Don't force recreate by default
INSTALL_KAE="false"       # Don't install KAE driver by default
# Repository configuration
GIT_REPO="https://gitcode.com/openeuler/virtCCA_sdk.git"
WORK_DIR="/tmp/cvm_builder_$(date +%s)"
# Script directory (for default output path)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Color codes (optional, for better display)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
# ============================
# Function Definitions
# ============================
# Display usage help
get_host_openeuler_version() {
    local version=""
    
    # Check if /etc/os-release exists
    if [ -f /etc/os-release ]; then
        # Try to get version from os-release
        if grep -q "openEuler" /etc/os-release; then
            local full_version=$(grep "^VERSION=" /etc/os-release | cut -d'"' -f2)
            
            #  (: 24.03)
            if [[ "$full_version" =~ ([0-9]+\.[0-9]+) ]]; then
                version="${BASH_REMATCH[1]}"
                
                #  LTS-SP  (: LTS-SP1)
                if [[ "$full_version" =~ LTS-SP([0-9]+) ]]; then
                    sp_version="-LTS-SP${BASH_REMATCH[1]}"
                elif [[ "$full_version" =~ LTS-SP([0-9]+) ]]; then
                    # 
                    sp_version="-LTS-SP${BASH_REMATCH[1]}"
                fi
                
                # 
                if [ -n "$sp_version" ]; then
                    version="${version}${sp_version}"
                fi
                
                echo "$version"
                return 0
            fi
        fi
    fi
    
    # Fallback: check /etc/issue
    if [ -z "$version" ] && [ -f /etc/issue ]; then
        version=$(head -n1 /etc/issue | grep -oP "openEuler [0-9]+\.[0-9]+(?:-LTS-SP[0-9]+)?" | sed 's/openEuler //')
    fi
    
    # Fallback: use uname -a
    if [ -z "$version" ]; then
        version=$(uname -a | grep -oP "openEuler[0-9]+\.[0-9]+(?:-LTS-SP[0-9]+)?" | sed 's/openEuler//')
    fi
    
    echo "$version"
}

HOST_VERSION=$(get_host_openeuler_version)
if [ -n "$HOST_VERSION" ]; then
    IMAGE_VERSION="$HOST_VERSION"
    echo -e "${GREEN}Detected host openEuler version: $HOST_VERSION${NC}"
else
    IMAGE_VERSION="24.03-LTS-SP2"
    echo -e "${YELLOW}Warning: Could not detect host openEuler version, using default: $IMAGE_VERSION${NC}"
fi

show_usage() {
    echo -e "${BLUE}ARM Confidential VM Image Creation Tool${NC}"
    echo ""
    echo -e "${BLUE}Usage:${NC}"
    echo "  $0 [options]"
    echo ""
    echo -e "${BLUE}Options:${NC}"
    echo "  -v <version>    Specify image version (default: $IMAGE_VERSION)"
    echo "  -s <size>       Image size in GB (default: $IMAGE_SIZE)"
    echo "  -p <password>   Set root password for the image"
    echo "  -o <path>       Specify create-oe-image.sh output path (temporary directory)"
    echo "  -d <path>       Specify final image storage directory (final location)"
    echo "  -f              Force re-run script and clean downloaded files"
    echo "  -k              Compile and install KAE driver"
    echo "  -h              Show this help message"
    echo ""
    echo -e "${BLUE}Notes:${NC}"
    echo "  -o option specifies temporary output directory for create-oe-image.sh"
    echo "  -d option specifies final image storage directory (script will auto-copy)"
    echo ""
    echo -e "${BLUE}Examples:${NC}"
    echo "  $0 -v 24.03-LTS-SP2 -s 20 -p mypassword -d /var/images/"
    echo "  $0 -v 24.03-LTS-SP2 -o /tmp/build -d /opt/vm_images/"
    echo "  $0 -d /home/user/images/ -f"
}
# Parse command line arguments
parse_arguments() {
    while getopts ":v:s:p:o:d:fkh" opt; do
        case ${opt} in
            v)
                IMAGE_VERSION="$OPTARG"
                echo -e "${GREEN}Set image version to: $IMAGE_VERSION${NC}"
                ;;
            s)
                if [[ "$OPTARG" =~ ^[0-9]+$ ]] && [ "$OPTARG" -ge 1 ]; then
                    IMAGE_SIZE="$OPTARG"
                    echo -e "${GREEN}Set image size to: ${IMAGE_SIZE}G${NC}"
                else
                    echo -e "${RED}Error: Image size must be a positive integer${NC}"
                    exit 1
                fi
                ;;
            p)
                ROOT_PASSWORD="$OPTARG"
                echo -e "${GREEN}Root password set${NC}"
                ;;
            o)
                OUTPUT_PATH="$OPTARG"
                # Convert to absolute path
                if [[ ! "$OUTPUT_PATH" =~ ^/ ]]; then
                    OUTPUT_PATH="$SCRIPT_DIR/$OUTPUT_PATH"
                fi
                echo -e "${GREEN}Set temporary output path to: $OUTPUT_PATH${NC}"
                ;;
            d)
                FINAL_DESTINATION="$OPTARG"
                # Convert to absolute path
                if [[ ! "$FINAL_DESTINATION" =~ ^/ ]]; then
                    FINAL_DESTINATION="$SCRIPT_DIR/$FINAL_DESTINATION"
                fi
                echo -e "${GREEN}Set final image directory to: $FINAL_DESTINATION${NC}"
                ;;
            f)
                FORCE_RECREATE="true"
                echo -e "${GREEN}Enabled force recreate mode${NC}"
                ;;
            k)
                INSTALL_KAE="true"
                echo -e "${GREEN}Enabled KAE driver installation${NC}"
                ;;
            h)
                show_usage
                exit 0
                ;;
            \?)
                echo -e "${RED}Error: Invalid option -$OPTARG${NC}"
                show_usage
                exit 1
                ;;
            :)
                echo -e "${RED}Error: Option -$OPTARG requires an argument${NC}"
                show_usage
                exit 1
                ;;
        esac
    done
}
# Check TMM kernel information
check_tmm() {
    echo -e "${BLUE}=== Checking TMM Environment ===${NC}"
    
    # Check ARM architecture
    if [[ $(uname -m) != "aarch64" ]] && [[ $(uname -m) != "arm64" ]]; then
        echo -e "${RED}Error: This script only supports ARM64 architecture${NC}"
        exit 1
    fi
    echo -e "${GREEN} System architecture: $(uname -m)${NC}"
    
    # Check TMM feature0 information
    echo "Checking TMM feature0 kernel info..."
    local found=false
    local tmm_value=""
    
    # Check multiple possible locations
    for source in "dmesg" "/var/log/kern.log" "/var/log/syslog"; do
        if [ "$source" = "dmesg" ]; then
            if dmesg 2>/dev/null | grep -q "TMM feature0:"; then
                tmm_value=$(dmesg | grep "TMM feature0:" | tail -1 | awk -F: '{print $NF}' | xargs)
                found=true
                break
            fi
        elif [ -f "$source" ] && grep -q "TMM feature0:" "$source" 2>/dev/null; then
            tmm_value=$(grep "TMM feature0:" "$source" | tail -1 | awk -F: '{print $NF}' | xargs)
            found=true
            break
        fi
    done
    
    if [ "$found" = true ] && [ -n "$tmm_value" ]; then
        echo -e "${GREEN} Detected TMM feature0: $tmm_value${NC}"
        return 0
    else
        echo -e "${YELLOW} Warning: TMM feature0 kernel info not detected${NC}"
        echo "Continue? [y/N]"
        read -r choice
        if [[ ! "$choice" =~ ^[Yy]$ ]]; then
            echo "Operation cancelled"
            exit 0
        fi
        return 1
    fi
}
# Install dependencies
install_dependencies() {
    echo ""
    echo -e "${BLUE}=== Installing Dependencies ===${NC}"
    
    # Check if most dependencies are already installed
    echo "Checking and installing necessary dependencies..."
    
    # Define package list
    local packages=(
        dnf-plugins-core
        grub2-efi-aa64-modules
        libguestfs-tools
        qemu-img
        virt-install
        guestfs-tools
        cloud-utils-growpart
        nbdkit
        ncurses-devel
        openssl-devel
        elfutils-libelf-devel
        dwarves
        git
        wget
        rsync
    )
    
    # Install base packages
    yum install -y "${packages[@]}"
    
    # Install development tools group
    yum groupinstall -y "Development Tools"
    
    # Check KAE driver dependencies (if needed)
    if [ "$INSTALL_KAE" = "true" ]; then
        echo "Installing KAE driver compilation dependencies..."
        yum install -y kernel-devel gcc make
    fi
    
    echo -e "${GREEN} Dependencies installed${NC}"
}
# Configure libvirtd
setup_libvirtd() {
    echo ""
    echo -e "${BLUE}=== Configuring libvirtd ===${NC}"
    
    # Check and install libvirt
    if ! command -v virsh &> /dev/null; then
        echo "Installing libvirt..."
        yum install -y libvirt libvirt-daemon-kvm qemu-kvm
    fi
    
    # Start service
    echo "Starting libvirtd service..."
    systemctl start libvirtd
    systemctl enable libvirtd
    
    if systemctl is-active --quiet libvirtd; then
        echo -e "${GREEN} libvirtd service running normally${NC}"
    else
        echo -e "${RED}Error: libvirtd failed to start${NC}"
        exit 1
    fi
}
# Prepare final destination directory
prepare_final_destination() {
    if [ -n "$FINAL_DESTINATION" ]; then
        echo -e "${BLUE}Preparing final image directory...${NC}"
        
        # Check if directory exists
        if [ ! -d "$FINAL_DESTINATION" ]; then
            echo "Creating directory: $FINAL_DESTINATION"
            mkdir -p "$FINAL_DESTINATION"
            if [ $? -ne 0 ]; then
                echo -e "${RED}Error: Cannot create directory $FINAL_DESTINATION${NC}"
                exit 1
            fi
        fi
        
        # Check if directory is writable
        if [ ! -w "$FINAL_DESTINATION" ]; then
            echo -e "${RED}Error: Directory $FINAL_DESTINATION is not writable${NC}"
            exit 1
        fi
        
        echo -e "${GREEN} Final directory prepared: $FINAL_DESTINATION${NC}"
    fi
}
# Clean up work directory (if using -f option)
cleanup_workdir() {
    if [ "$FORCE_RECREATE" = "true" ]; then
        echo -e "${YELLOW}Cleaning up previous work directories...${NC}"
        # Clean up possible old work directories
        local old_dirs=$(find /tmp -maxdepth 1 -type d -name "cvm_builder_*" 2>/dev/null)
        if [ -n "$old_dirs" ]; then
            echo "Found old work directories:"
            echo "$old_dirs"
            read -p "Delete these directories? [y/N]: " choice
            if [[ "$choice" =~ ^[Yy]$ ]]; then
                echo "$old_dirs" | xargs rm -rf 2>/dev/null
                echo -e "${GREEN} Old directories cleaned up${NC}"
            fi
        fi
    fi
}
# Build create-oe-image.sh command parameters
build_create_command() {
    local cmd="./create-oe-image.sh -v $IMAGE_VERSION -s $IMAGE_SIZE"
    
    # Add password parameter (if set)
    if [ -n "$ROOT_PASSWORD" ]; then
        cmd="$cmd -p $ROOT_PASSWORD"
    fi
    
    # Add temporary output path parameter (if set)
    if [ -n "$OUTPUT_PATH" ]; then
        # Ensure directory exists
        mkdir -p "$OUTPUT_PATH" 2>/dev/null
        cmd="$cmd -o $OUTPUT_PATH"
    fi
    
    # Add force recreate parameter
    if [ "$FORCE_RECREATE" = "true" ]; then
        cmd="$cmd -f"
    fi
    
    # Add KAE driver installation parameter
    if [ "$INSTALL_KAE" = "true" ]; then
        cmd="$cmd -k"
    fi
    
    echo "$cmd"
}
# Copy images to final directory
copy_to_final_destination() {
    if [ -z "$FINAL_DESTINATION" ]; then
        return 0
    fi
    
    echo ""
    echo -e "${BLUE}=== Copying Images to Final Directory ===${NC}"
    
    # Determine source file location
    local source_dir="$WORK_DIR/virtCCA_sdk/cvm-image-rewriter"
    if [ -n "$OUTPUT_PATH" ]; then
        source_dir="$OUTPUT_PATH"
    fi
    
    # Find generated image files
    local image_files=()
    local json_files=()
    
    # Search in current directory
    if [ -d "$source_dir" ]; then
        while IFS= read -r file; do
            image_files+=("$file")
        done < <(find "$source_dir" -maxdepth 1 -name "*.qcow2" -type f 2>/dev/null)
        
        while IFS= read -r file; do
            json_files+=("$file")
        done < <(find "$source_dir" -maxdepth 1 -name "*.json" -type f 2>/dev/null)
    fi
    
    # If not found, search in work directory
    if [ ${#image_files[@]} -eq 0 ]; then
        while IFS= read -r file; do
            image_files+=("$file")
        done < <(find "$WORK_DIR" -name "*.qcow2" -type f 2>/dev/null)
    fi
    
    if [ ${#json_files[@]} -eq 0 ]; then
        while IFS= read -r file; do
            json_files+=("$file")
        done < <(find "$WORK_DIR" -name "*.json" -type f 2>/dev/null)
    fi
    
    if [ ${#image_files[@]} -eq 0 ]; then
        echo -e "${YELLOW}Warning: No image files found${NC}"
        return 1
    fi
    
    # Display found files
    echo "Found the following image files:"
    for file in "${image_files[@]}"; do
        echo "  - $file ($(du -h "$file" | cut -f1))"
    done
    
    for file in "${json_files[@]}"; do
        echo "  - $file"
    done
    
    # Copy files
    local copied_files=()
    echo ""
    echo "Copying to: $FINAL_DESTINATION"
    
    # Copy image files
    for file in "${image_files[@]}"; do
        local filename=$(basename "$file")
        local dest="$FINAL_DESTINATION/$filename"
        
        echo -n "Copying $filename ... "
        
        # Use rsync with progress
        rsync -ah --progress "$file" "$dest" 2>/dev/null
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}${NC}"
            copied_files+=("$dest")
            
            # Set permissions (optional)
            chmod 644 "$dest" 2>/dev/null
        else
            # If rsync fails, use cp
            cp "$file" "$dest"
            if [ $? -eq 0 ]; then
                echo -e "${GREEN}${NC}"
                copied_files+=("$dest")
                chmod 644 "$dest" 2>/dev/null
            else
                echo -e "${RED}${NC}"
            fi
        fi
    done
    
    # Copy JSON files
    for file in "${json_files[@]}"; do
        local filename=$(basename "$file")
        local dest="$FINAL_DESTINATION/$filename"
        
        echo -n "Copying $filename ... "
        cp "$file" "$dest"
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}${NC}"
            copied_files+=("$dest")
            chmod 644 "$dest" 2>/dev/null
        else
            echo -e "${RED}${NC}"
        fi
    done
    
    # Display results
    echo ""
    if [ ${#copied_files[@]} -gt 0 ]; then
        echo -e "${GREEN} File copy completed${NC}"
        echo "Final directory contents:"
        ls -lh "$FINAL_DESTINATION" | grep -E "\.(qcow2|json)$" || echo "(No relevant files found)"
        
        # Display image information
        for file in "${copied_files[@]}"; do
            if [[ "$file" == *.qcow2 ]]; then
                echo ""
                echo -e "${CYAN}Image Information:${NC}"
                echo -e "  File: $(basename "$file")"
                echo -e "  Path: $file"
                echo -e "  Size: $(du -h "$file" | cut -f1)"
                echo -e "  Modified: $(stat -c %y "$file" | cut -d. -f1)"
            fi
        done
    else
        echo -e "${YELLOW}Warning: No files were copied${NC}"
    fi
    
    return 0
}
# Download and run image creation script
create_image() {
    echo ""
    echo -e "${BLUE}=== Creating Confidential VM Image ===${NC}"
    
    echo -e "${GREEN}Image version: $IMAGE_VERSION${NC}"
    echo -e "${GREEN}Image size: ${IMAGE_SIZE}G${NC}"
    [ -n "$ROOT_PASSWORD" ] && echo -e "${GREEN}Root password: Set${NC}"
    [ -n "$OUTPUT_PATH" ] && echo -e "${GREEN}Temporary output: $OUTPUT_PATH${NC}"
    [ -n "$FINAL_DESTINATION" ] && echo -e "${GREEN}Final directory: $FINAL_DESTINATION${NC}"
    echo -e "${GREEN}Work directory: $WORK_DIR${NC}"
    [ "$FORCE_RECREATE" = "true" ] && echo -e "${YELLOW}Force recreate: Yes${NC}"
    [ "$INSTALL_KAE" = "true" ] && echo -e "${YELLOW}Install KAE driver: Yes${NC}"
    
    # Prepare final directory
    prepare_final_destination
    
    # Clean up work directory (if needed)
    cleanup_workdir
    
    # Create and enter work directory
    mkdir -p "$WORK_DIR"
    cd "$WORK_DIR" || exit 1
    
    # Clone repository
    echo "Cloning virtCCA_sdk repository..."
    if ! git clone --depth 1 "$GIT_REPO"; then
        echo -e "${RED}Error: Repository clone failed${NC}"
        exit 1
    fi
    
    cd virtCCA_sdk/cvm-image-rewriter || {
        echo -e "${RED}Error: Cannot enter cvm-image-rewriter directory${NC}"
        exit 1
    }
    
    # Set environment variable
    export LIBGUESTFS_BACKEND=direct
    
    # Check if script exists
    if [ ! -f "create-oe-image.sh" ]; then
        echo -e "${RED}Error: create-oe-image.sh script not found${NC}"
        exit 1
    fi
    
    # Give execute permission
    chmod +x create-oe-image.sh
    
    # Build execution command
    local create_cmd=$(build_create_command)
    
    echo ""
    echo -e "${BLUE}Executing command:${NC}"
    echo -e "${GREEN}$create_cmd${NC}"
    echo ""
    
    # Execute creation script
    echo "Starting image creation..."
    if eval "$create_cmd"; then
        echo ""
        echo -e "${GREEN} Image created successfully!${NC}"
        
        # Copy to final directory
        copy_to_final_destination
        
        echo ""
        echo -e "${BLUE}=== Creation Complete ===${NC}"
        echo -e "Work directory: ${YELLOW}$WORK_DIR${NC}"
        
        if [ -n "$FINAL_DESTINATION" ]; then
            echo -e "Final image: ${GREEN}$FINAL_DESTINATION${NC}"
            echo ""
            echo -e "${CYAN}Final directory contents:${NC}"
            ls -lh "$FINAL_DESTINATION" 2>/dev/null || echo "(Cannot access directory)"
        else
            echo -e "Image location: ${YELLOW}$WORK_DIR/virtCCA_sdk/cvm-image-rewriter${NC}"
            if [ -n "$OUTPUT_PATH" ]; then
                echo -e "or: ${YELLOW}$OUTPUT_PATH${NC}"
            fi
        fi
        
    else
        echo -e "${RED}Error: Image creation failed${NC}"
        exit 1
    fi
}
# Interactive parameter setup
interactive_setup() {
    echo ""
    echo -e "${BLUE}=== Interactive Parameter Setup ===${NC}"
    echo "Current settings:"
    echo "  1. Image version: $IMAGE_VERSION"
    echo "  2. Image size: ${IMAGE_SIZE}G"
    echo "  3. Root password: ${ROOT_PASSWORD:-Not set}"
    echo "  4. Temporary output: ${OUTPUT_PATH:-Default}"
    echo "  5. Final directory: ${FINAL_DESTINATION:-No copy}"
    echo "  6. Force recreate: $FORCE_RECREATE"
    echo "  7. Install KAE driver: $INSTALL_KAE"
    echo ""
    
    read -p "Modify these settings? [y/N]: " modify
    if [[ "$modify" =~ ^[Yy]$ ]]; then
        read -p "Image version [default: $IMAGE_VERSION]: " user_version
        [ -n "$user_version" ] && IMAGE_VERSION="$user_version"
        
        read -p "Image size(GB) [default: $IMAGE_SIZE]: " user_size
        if [[ "$user_size" =~ ^[0-9]+$ ]] && [ "$user_size" -ge 1 ]; then
            IMAGE_SIZE="$user_size"
        elif [ -n "$user_size" ]; then
            echo -e "${RED}Error: Image size must be a positive integer${NC}"
            exit 1
        fi
        
        read -p "Root password [leave empty for none]: " user_password
        [ -n "$user_password" ] && ROOT_PASSWORD="$user_password"
        
        read -p "Temporary output path [leave empty for default]: " user_output
        [ -n "$user_output" ] && OUTPUT_PATH="$user_output"
        
        read -p "Final image directory [leave empty for no copy]: " user_final
        [ -n "$user_final" ] && FINAL_DESTINATION="$user_final"
        
        read -p "Force recreate? [y/N]: " user_force
        [[ "$user_force" =~ ^[Yy]$ ]] && FORCE_RECREATE="true"
        
        read -p "Install KAE driver? [y/N]: " user_kae
        [[ "$user_kae" =~ ^[Yy]$ ]] && INSTALL_KAE="true"
    fi
}
# Main function
main() {
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}     ARM Confidential VM Image Creator   ${NC}"
    echo -e "${GREEN}========================================${NC}"
    
    # Parse command line arguments
    parse_arguments "$@"
    
    # If no arguments provided, enter interactive mode
    if [ $# -eq 0 ]; then
        interactive_setup
    fi
    
    # Display final configuration
    echo ""
    echo -e "${BLUE}=== Final Configuration ===${NC}"
    echo -e "Image version: ${GREEN}$IMAGE_VERSION${NC}"
    echo -e "Image size: ${GREEN}${IMAGE_SIZE}G${NC}"
    [ -n "$ROOT_PASSWORD" ] && echo -e "Root password: ${GREEN}Set${NC}" || echo -e "Root password: ${YELLOW}Not set${NC}"
    echo -e "Temporary output: ${GREEN}${OUTPUT_PATH:-Default}${NC}"
    if [ -n "$FINAL_DESTINATION" ]; then
        echo -e "Final directory: ${CYAN}$FINAL_DESTINATION${NC}"
    else
        echo -e "Final directory: ${YELLOW}No auto copy${NC}"
    fi
    echo -e "Force recreate: ${GREEN}$FORCE_RECREATE${NC}"
    echo -e "Install KAE driver: ${GREEN}$INSTALL_KAE${NC}"
    
    # Ask for confirmation
    echo ""
    read -p "Continue creating image? [Y/n]: " confirm
    if [[ "$confirm" =~ ^[Nn]$ ]]; then
        echo "Operation cancelled"
        exit 0
    fi
    
    # Check TMM environment
    check_tmm
    
    # Install dependencies
    install_dependencies
    
    # Configure libvirtd
    setup_libvirtd
    
    # Create image
    create_image
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}            Operation Complete!         ${NC}"
    echo -e "${GREEN}========================================${NC}"
    
    # Display final tips
    if [ -n "$FINAL_DESTINATION" ]; then
        echo ""
        echo -e "${CYAN}Tips:${NC}"
        echo -e "Image saved to: ${GREEN}$FINAL_DESTINATION${NC}"
        echo -e "Temporary files at: ${YELLOW}$WORK_DIR${NC}"
        echo -e "To clean up temporary files, run: ${YELLOW}rm -rf $WORK_DIR${NC}"
    fi
}
# ============================
# Script Execution
# ============================
# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Use: sudo $0"
    exit 1
fi
# Run main function (pass all arguments)
main "$@"
