#!/bin/bash

set -ux

# Configuration for the Confidential Containers environment
IP_ADDR=$(hostname -I | awk '{print $1}')
REGISTRY_DOMAIN="registry.hw.com"
REGISTRY_PORT="5000"
KATA_VERSION="3.15.0"
TRUSTEE_VERSION="v0.12.0"
GUEST_COMPONENTS_VERSION="v0.12.0"
OPERATOR_VERSION="v0.13.0"
KBS_TYPES_COMMIT_TAG="611889d22e5a4e8e57f13a33a1bdf03aa4aa9c70"
CONTAINERD_FILE_NAME="containerd-1.7.27-linux-arm64.tar.gz"
CONTAINERD_URL="https://github.com/containerd/containerd/releases/download/v1.7.27/containerd-1.7.27-linux-arm64.tar.gz"
CONTAINERD_SERVICE_URL="https://raw.githubusercontent.com/containerd/containerd/refs/tags/v1.7.27/containerd.service"
WORK_DIR="$(pwd)"
REGISTRY_DIR="$WORK_DIR/registry"
KATA_SRC_DIR="$WORK_DIR/kata-containers"
DOCKERFILE_DIR="$KATA_SRC_DIR/build/virtCCA_sdk/kata-v3.15.0/conf"
CONTAINER_NAME="coco-build-env"
IMAGE_NAME="coco-builder:latest"
KATA_DEPLOY_IMAGE_NAME="kata-deploy-test:latest"
TEST_CONTAINER_IMAGE="docker.io/library/busybox:latest"
REMOTE_ATTESTATION_DIR="$WORK_DIR/coco/remote_attestation"
COCO_LOG_DIR="$REMOTE_ATTESTATION_DIR/logs"
COCO_CONFIG_DIR="$REMOTE_ATTESTATION_DIR/config"
HTTP_PROXY="${http_proxy:-}"
EULER_CERTS_PATH="/etc/pki/ca-trust/source/anchors"

if [ -n "$HTTP_PROXY" ]; then
    DOCKER_BUILD_ARGS="--build-arg http_proxy="$HTTP_PROXY" --build-arg https_proxy="$HTTP_PROXY""
    DOCKER_RUN_ENV="-e http_proxy="$HTTP_PROXY" -e https_proxy="$HTTP_PROXY""
    MOUNT_GATEWAY_CA="-v ${EULER_CERTS_PATH}/Huawei_Web_Secure_Internet_Gateway_CA.crt:/etc/ssl/certs/proxy-ca.crt"
else
    DOCKER_BUILD_ARGS=""
    DOCKER_RUN_ENV=""
    MOUNT_GATEWAY_CA=""
fi

# install cosign-linux-arm64
COSIGN_VERSION="v2.5.0"
TARGET_ARCH="linux-arm64"
DOWNLOAD_URL="https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-${TARGET_ARCH}"
INSTALL_PATH="/usr/local/bin/cosign"
COSIGN_TEMP_FILE="./cosign-${TARGET_ARCH}"

# install skopeo
GO_VERSION="1.22.4"
GO_ARCH="linux-arm64"
SKOPEO_VERSION="v1.15.1"
TMP_DIR="./"
GO_INSTALL_DIR="/usr/local"
GOPATH_DIR="/home/work/go"

# launch encrypted image
ENC_KEY_NAME="enc_key_1"
KBS_ENC_KEY_PATH="/opt/confidential-containers/kbs/repository/default/image_key"
KBS_SECURITY_POLICY="/opt/confidential-containers/kbs/repository/default/security-policy/test"
ENC_CONTAINER_IMAGE="ghcr.io/confidential-containers/staged-images/coco-keyprovider:latest"
PLAIN_IMAGE="${PLAIN_IMAGE:-"busybox"}"

# install nydus
NYDUS_VERSION="v2.3.0"
SNAPSHOTTER_VERSION="v0.14.0"
NERDCTL_VERSION="1.7.7"
NYDUS_WORK_DIR="./"
NYDUS_BIN_DIR="/usr/bin"
CONTAINERD_ROOT="/var/lib/containerd"
KATA_CONFIG="/opt/kata/share/defaults/kata-containers/configuration-qemu-virtcca.toml"

# Safely load profile file, ignore undefined variable errors
function source_profile()
{
    set +u  # Temporarily disable undefined variable checking
    source /etc/profile >/dev/null 2>&1 || true
    set -u  # Re-enable undefined variable checking
}

# Proxy configuration (enable as needed)
function containerd_proxy_configuration()
{
    if [ -n "$HTTP_PROXY" ]; then
        echo "> Configuring Containerd proxy: $HTTP_PROXY"
    else
        echo "> Proxy not enabled"
    fi

    # Create config directory
    echo "> Creating config directory..."
    mkdir -p /etc/systemd/system/containerd.service.d/

    # Create proxy config file
    echo "> Creating proxy config file..."
    cat > /etc/systemd/system/containerd.service.d/http-proxy.conf <<EOF
[Service]
Environment="HTTP_PROXY=$HTTP_PROXY"
Environment="HTTPS_PROXY=$HTTP_PROXY"
Environment="NO_PROXY=localhost,$REGISTRY_DOMAIN"
EOF

    # Verify config file
    if [ ! -f "/etc/systemd/system/containerd.service.d/http-proxy.conf" ]; then
        echo "> Error: Failed to create proxy config file!"
        return 1
    fi

    echo "> Reloading systemd configuration..."
    systemctl daemon-reload
}

function env_cleanup()
{
    systemctl stop containerd
    rm -rf /etc/containerd/*
    rm -rf /opt/containerd
    rm -rf /var/lib/containerd
    rm -rf /var/lib/containerd-nydus

    systemctl stop kubelet
    rm -rf /etc/kubernetes/*
    rm -rf /root/.kube
    rm -rf /var/lib/etcd
    rm -rf /var/lib/kubelet/*
}

# Install and configure Containerd
function install_containerd()
{
    env_cleanup
    source_profile
    echo "===== Starting Containerd installation ====="

    # 1. Download containerd
    echo "Downloading containerd..."

    # Check if file exists
    if [ -f "$CONTAINERD_FILE_NAME" ]; then
        echo "File already exists, skipping download: $CONTAINERD_FILE_NAME"
    else
        echo "Starting download: $CONTAINERD_FILE_NAME"
        wget "$CONTAINERD_URL"
    fi

    # 2. Extract files
    echo "Extracting package..."
    tar -xvf "$CONTAINERD_FILE_NAME" > /dev/null

    # 3. Copy binaries safely
    echo "Copying binaries to /usr/local/bin..."
    if pgrep containerd; then
        echo "Stopping existing containerd process..."
        pkill containerd
        sleep 2
    fi
    cp -f bin/* /usr/local/bin

    # 4. Install runc
    echo "Installing runc..."
    yum install -y runc > /dev/null

    # 5. Generate config file
    echo "Generating containerd config..."
    mkdir -p /etc/containerd/
    containerd config default > /etc/containerd/config.toml

    # 6. Add kata runtime config
    echo "Configuring kata runtime..."
    sed -i '/\[plugins."io.containerd.grpc.v1.cri".containerd\]/a \\n  [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata]\n    runtime_type = "io.containerd.kata.v2"\n    privileged_without_host_devices = false' /etc/containerd/config.toml

    # 7. Modify critical settings
    echo "Modifying core configurations..."
    sed -i 's/enable_unprivileged_ports = false/enable_unprivileged_ports = true/' /etc/containerd/config.toml
    sed -i 's|sandbox_image = "registry.k8s.io/pause:3.8"|sandbox_image = "registry.k8s.io/pause:3.10"|' /etc/containerd/config.toml

    # 8. Install systemd service
    echo "Installing containerd service..."
    if [ -f "containerd.service" ]; then
        echo "File already exists, skipping download: containerd.service"
    else
        echo "Starting download: containerd.service"
        wget --no-check-certificate "$CONTAINERD_SERVICE_URL"
    fi
    cp -f ./containerd.service /usr/lib/systemd/system/

    # 9. containerd proxy configuration
    containerd_proxy_configuration

    # 10. Start service
    echo "Starting containerd service..."
    systemctl enable containerd > /dev/null

    if systemctl is-active --quiet containerd; then
        systemctl stop containerd
        sleep 2
    fi
    systemctl start containerd

    # Verify service status
    echo "Verifying service status..."
    systemctl status containerd --no-pager | grep "Active:"

    # 11. Container test after fixes
    echo "Waiting for service initialization..."
    sleep 5

    echo "Pulling test image..."
    ctr image rm $TEST_CONTAINER_IMAGE
    ctr image pull --skip-verify $TEST_CONTAINER_IMAGE
    if ctr image ls --quiet | grep -Fe "${TEST_CONTAINER_IMAGE}"; then
        echo "Success: image ${TEST_CONTAINER_IMAGE} exist"
    else
        echo "Error: image ${TEST_CONTAINER_IMAGE} pull failed"
        echo "Please try to manually pull the image"
        exit 1
    fi

    echo "Running container test..."
    ctr run --rm \
        $TEST_CONTAINER_IMAGE \
        test-container \
        /bin/sh -c 'echo "Container test successful! Current time: $(date)"'

    echo "===== Containerd installation successful ====="
}

# Initialize a single-node Kubernetes cluster
function init_k8s() {
    source_profile
    echo "===== Starting Kubernetes single-node cluster installation ====="

    # 1. Configure yum repositories
    echo "Configuring Kubernetes yum repositories..."
    rm -rf /etc/yum.repos.d/k8s.repo
    cat <<EOF > /etc/yum.repos.d/k8s.repo
[k8s]
name=Kubernetes
baseurl=https://pkgs.k8s.io/core:/stable:/v1.32/rpm/
enabled=1
gpgcheck=0
repo_gpgcheck=0
EOF

    echo "Cleaning and rebuilding yum cache..."
    yum clean all --disablerepo="*" --enablerepo="k8s" > /dev/null
    yum makecache --disablerepo="*" --enablerepo="k8s" > /dev/null

    # 2. Install K8s components
    echo "Installing Kubernetes components..."
    yum install -y kubelet-1.32.4 kubeadm-1.32.4 kubectl-1.32.4 kubernetes-cni --nobest > /dev/null

    # 3. System configuration
    echo "Configuring system parameters..."

    # Disable firewall
    systemctl stop firewalld 2>/dev/null || true
    systemctl disable firewalld > /dev/null

    # Load kernel modules
    echo "modprobe br_netfilter" >> /etc/profile

    # Enable NET.BRIDGE.BRIDGE-NF-CALL-IPTABLES kernel option
    echo "sysctl -w net.bridge.bridge-nf-call-iptables=1" >> /etc/profile

    # Disable swap
    echo "swapoff -a" >> /etc/profile
    echo "cp -p /etc/fstab /etc/fstab.bak$(date '+%Y%m%d%H%M%S')" >> /etc/profile
    echo "sed -i "s/\/dev\/mapper\/openeuler-swap/\#\/dev\/mapper\/openeuler-swap/g" /etc/fstab" >> /etc/profile

    source_profile

    systemctl enable kubelet > /dev/null

    # 4. Initialize cluster
    echo "Preparing cluster initialization..."

    # Cleanup proxy settings (critical fix)
    echo "Clearing proxy settings..."
    export -n http_proxy
    export -n https_proxy
    export -n no_proxy
    unset http_proxy
    unset https_proxy

    # Create /etc/resolv.conf
    rm -rf /etc/resolv.conf
cat > /etc/resolv.conf <<EOF
{
nameserver 8.8.8.8
nameserver 114.114.114.114
}
EOF

    # Create /etc/resolv.conf and modify /etc/hosts
    touch /etc/resolv.conf && echo "$(hostname -I | awk '{print $1}') node" | sudo tee -a /etc/hosts

    # Generate initialization config
    kubeadm config print init-defaults > kubeadm-init.yaml

    # Execute update script in same directory
    chmod 755 update_kubeadm_init.sh
    ./update_kubeadm_init.sh

    if ! kubeadm reset -f > /dev/null 2>&1; then
        echo "Reset failed, performing deep cleanup..."
        # Handle etcd configuration errors
        rm -rf /etc/kubernetes/*
        rm -rf /root/.kube/*
        rm -rf /var/lib/etcd/*

        # Retry reset
        if ! kubeadm reset -f > /dev/null 2>&1; then
            echo "Error: Cluster reset failed! Manually check these directories:"
            echo "  /etc/kubernetes/"
            echo "  /var/lib/etcd/"
            echo "  /root/.kube/"
            exit 1
        fi
    fi

    export -n http_proxy
    export -n https_proxy
    export -n no_proxy

    if ! kubeadm init --config kubeadm-init.yaml > /dev/null 2>&1; then
        kubeadm reset -f
        rm -rf /var/lib/etcd
        iptables -F && iptables -t nat -F && iptables -t mangle -F

        if ! kubeadm init --config kubeadm-init.yaml; then
            echo "Error: Failed to initialize K8s node! Please check manually"
            exit 1
        fi
    fi

    # Configure kubectl
    mkdir -p $HOME/.kube
    cp -f /etc/kubernetes/admin.conf $HOME/.kube/config
    chown $(id -u):$(id -g) $HOME/.kube/config
    echo "export KUBECONFIG=/etc/kubernetes/admin.conf" >> /etc/profile
    source_profile

    # 5. Install CNI plugin
    echo "Installing Flannel network plugin..."

    source_profile
    # Download CNI plugins
    CNI_URL="https://github.com/containernetworking/plugins/releases/download/v1.5.1/cni-plugins-linux-arm64-v1.5.1.tgz"
    mkdir -p /opt/cni/bin
    if ! wget -qO- $CNI_URL | tar -xz -C /opt/cni/bin; then
        echo "CNI plugin download failed! Trying mirror..."
        wget -qO- https://mirror.ghproxy.com/$CNI_URL | tar -xz -C /opt/cni/bin || {
            echo "CNI plugin download failed, download manually:"
            echo "wget $CNI_URL"
            exit 1
        }
    fi


    # Apply Flannel configuration
    export -n http_proxy
    export -n https_proxy
    export -n no_proxy
    kubectl apply -f kube-flannel.yaml > /dev/null

    # 6. Verify deployment
    echo -e "\n===== Deployment complete, verifying cluster status ====="

    echo "Waiting for cluster components to initialize..."
    sleep 15
    for i in {1..30}; do
        # Check node status
        nodes_ready=$(kubectl get nodes -o jsonpath='{.items[*].status.conditions[?(@.type=="Ready")].status}' | grep -c True)

        # Check Pod status (exclude Completed and Succeeded)
        pods_not_ready=$(kubectl get pods -A -o jsonpath='{range .items[*]}{.status.phase}{"\n"}{end}' | grep -vE "Running|Succeeded|Completed" | wc -l)

        if [ $nodes_ready -ge 1 ] && [ $pods_not_ready -eq 0 ]; then
            echo "All components ready"
            break
        fi

        sleep 10
        echo "Waiting for components to initialize...(${i}0s)"

        # Debug information: show current status
        echo "=== Node status ==="
        kubectl get nodes
        echo "=== Pod status ==="
        kubectl get pods -A
    done

    echo -e "\nNode status:"
    kubectl get nodes -o wide

    echo -e "\nPod status:"
    kubectl get pods -A

    echo -e "\n===== Kubernetes cluster deployed successfully ====="
}

# Deploy Kata Confidential Containers environment
function kata_deploy()
{
source_profile

# 1. Install dependencies
echo "===== Installing system dependencies ====="
yum install -y docker httpd-tools git openssl kubectl || {
    echo "Dependency installation failed! Check network or yum configuration"
    exit 1
}

# 2. Configure Docker service
echo "===== Configuring Docker service ====="
systemctl start docker
systemctl enable docker

mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<EOF
{
  "registry-mirrors": [
    "https://registry.docker-cn.com",
    "http://hub-mirror.c.163.com"
  ],
  "insecure-registries": ["$REGISTRY_DOMAIN:$REGISTRY_PORT"],
  "dns": ["114.114.114.114", "8.8.8.8"]
}
EOF

    if [ -n "$HTTP_PROXY" ]; then
        echo "> Configuring Docker proxy: $HTTP_PROXY"
    fi

    # Create config directory
    echo "> Creating config directory..."
    mkdir -p /etc/systemd/system/docker.service.d

    # Create proxy config file
    echo "> Creating proxy config file..."
    cat > /etc/systemd/system/docker.service.d/http-proxy.conf <<EOF
[Service]
Environment="HTTP_PROXY=$HTTP_PROXY"
Environment="HTTPS_PROXY=$HTTP_PROXY"
Environment="NO_PROXY=localhost,$REGISTRY_DOMAIN"
EOF

systemctl daemon-reload
systemctl restart docker
docker pull registry:2
docker pull busybox:latest

# 3. Create working directories
echo "===== Creating working directories ====="
rm -rf "$KATA_SRC_DIR" "$REGISTRY_DIR"
mkdir -p "$REGISTRY_DIR"/{certs,data}
mkdir -p "$KATA_SRC_DIR"

# 4. Download source code
echo "===== Downloading Kata Containers ($KATA_VERSION) ====="
git clone https://github.com/kata-containers/kata-containers.git -b "$KATA_VERSION" "$KATA_SRC_DIR" || {
    echo "Kata Containers download failed!"
    exit 1
}
mkdir -p "$KATA_SRC_DIR"/build
echo "===== Downloading other components ====="
cd "$KATA_SRC_DIR/build"
git clone https://github.com/confidential-containers/trustee.git -b "$TRUSTEE_VERSION" || true
git clone https://github.com/confidential-containers/guest-components.git -b "$GUEST_COMPONENTS_VERSION" || true
git clone https://github.com/virtee/kbs-types.git || true
git clone https://gitee.com/openeuler/virtCCA_sdk.git || true

# 5. Apply patches
echo "===== Applying VirtCCA patches ====="
cd "$KATA_SRC_DIR"
git apply --reject --whitespace=fix ./build/virtCCA_sdk/kata-v"$KATA_VERSION"/kata-containers.patch || {
    echo "Warning: kata-containers patch issues detected, check .rej files"
}
git apply --reject --whitespace=fix ./build/virtCCA_sdk/kata-v"$KATA_VERSION"/kata-deploy.patch || {
    echo "Warning: kata-deploy patch issues detected, check .rej files"
}

if [ -n "$HTTP_PROXY" ]; then
    chmod +x ./build/virtCCA_sdk/kata-v"$KATA_VERSION"/tools/deploy_proxy_certs.sh
    ./build/virtCCA_sdk/kata-v"$KATA_VERSION"/tools/deploy_proxy_certs.sh
    git apply --reject --whitespace=fix ./build/virtCCA_sdk/kata-v"$KATA_VERSION"/tools/add_network_proxy.patch
fi

cd "$KATA_SRC_DIR/build/guest-components"
git apply --reject --whitespace=fix ../virtCCA_sdk/kata-v"$KATA_VERSION"/guest-components.patch || {
    echo "Warning: guest-components patch issues detected, check .rej files"
}

cd "$KATA_SRC_DIR/build/trustee"
git apply --reject --whitespace=fix ../virtCCA_sdk/kata-v"$KATA_VERSION"/trustee.patch || {
    echo "Warning: trustee patch issues detected, check .rej files"
}

cd "$KATA_SRC_DIR/build/kbs-types"
git reset --hard $KBS_TYPES_COMMIT_TAG
git apply --reject --whitespace=fix ../virtCCA_sdk/kata-v"$KATA_VERSION"/kbs-types.patch || {
    echo "Warning: kbs-types patch issues detected, check .rej files"
}

# 6. Copy configuration files
echo "===== Copying VirtCCA configuration files ====="
cd "$KATA_SRC_DIR"
cp -v ./build/virtCCA_sdk/kata-v"$KATA_VERSION"/conf/virtcca.config ./build/
cp -v ./build/virtCCA_sdk/kata-v"$KATA_VERSION"/conf/hosts ./build/

# 7. Prepare certificates
echo "===== Generating SSL certificates ====="
cd "$REGISTRY_DIR/certs"

# Generate root certificate
openssl genrsa -out rootCA.key 4096 || { echo "Root CA private key generation failed"; exit 1; }
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 3650 -out rootCA.crt \
  -subj "/CN=Local Root CA" -addext "basicConstraints=critical,CA:TRUE" || { echo "Root certificate generation failed"; exit 1; }

mkdir -p $KATA_SRC_DIR/tools/osbuilder/rootfs-builder/ubuntu/certs
cp -v rootCA.crt $KATA_SRC_DIR/tools/osbuilder/rootfs-builder/ubuntu/certs

# Generate domain certificate
openssl genrsa -out domain.key 4096 || { echo "Domain private key generation failed"; exit 1; }
openssl req -new -key domain.key -out domain.csr \
  -subj "/CN=$REGISTRY_DOMAIN" -addext "subjectAltName=DNS:$REGISTRY_DOMAIN" || { echo "CSR generation failed"; exit 1; }
openssl x509 -req -in domain.csr -CA rootCA.crt -CAkey rootCA.key -CAcreateserial \
  -out domain.crt -days 365 -sha256 -extfile <(printf "subjectAltName=DNS:$REGISTRY_DOMAIN") || { echo "Domain certificate signing failed"; exit 1; }

# Trust root certificate
echo "===== Configuring system trust ====="
cp -v rootCA.crt /etc/pki/ca-trust/source/anchors/
update-ca-trust extract

# Set local DNS resolution
sudo sed -i "/\b${REGISTRY_DOMAIN}\b/d" /etc/hosts
echo "127.0.0.1 $REGISTRY_DOMAIN" | sudo tee -a /etc/hosts >/dev/null

# 8. Start private registry
echo "===== Starting local Registry ($REGISTRY_DOMAIN:$REGISTRY_PORT) ====="

# Reliably check and clean up old containers
echo "> Cleaning up old containers..."
if docker container inspect "$REGISTRY_DOMAIN" &>/dev/null; then
    echo "> Existing Registry container found, cleaning up..."
    docker stop "$REGISTRY_DOMAIN" >/dev/null 2>&1
    docker rm "$REGISTRY_DOMAIN" >/dev/null 2>&1
    echo "> Old container removed"
    # Additional safety: remove potential lock files
    rm -f "$REGISTRY_DIR/data/.lock" >/dev/null 2>&1
else
    echo "> No existing container found"
fi

# Generate registry config
echo "> Generating configuration file..."
cat > "$REGISTRY_DIR/config.yml" <<EOF
version: 0.1
log:
  accesslog:
    disabled: false
  level: debug
storage:
  filesystem:
    rootdirectory: /var/lib/registry
http:
  addr: :$REGISTRY_PORT
  tls:
    certificate: /certs/domain.crt
    key: /certs/domain.key
EOF

# Start registry container (add --rm for auto-cleanup)
echo "> Starting new container..."
docker run -d \
  -p ${REGISTRY_PORT}:${REGISTRY_PORT} \
  --restart=always \
  --name "$REGISTRY_DOMAIN" \
  -v "$REGISTRY_DIR/certs:/certs" \
  -v "$REGISTRY_DIR/data:/var/lib/registry" \
  -v "$REGISTRY_DIR/config.yml:/etc/docker/registry/config.yml" \
  registry:2

# Verify registry startup
echo "> Verifying startup..."
for i in {1..10}; do
    if docker ps | grep -q "$REGISTRY_DOMAIN"; then
        echo "> Registry started successfully: https://$REGISTRY_DOMAIN:$REGISTRY_PORT/v2/_catalog"
        break
    elif [ $i -eq 5 ]; then
        echo "> Startup taking longer than expected..."
    elif [ $i -eq 10 ]; then
        echo "> Registry startup failed! Check logs: docker logs $REGISTRY_DOMAIN"
        exit 1
    fi
    sleep 1
done

# Push $TEST_CONTAINER_IMAGE
docker tag busybox:latest $REGISTRY_DOMAIN:$REGISTRY_PORT/busybox:latest
docker push $REGISTRY_DOMAIN:$REGISTRY_PORT/busybox:latest

# 9. Compile kata-deploy image
echo "===== Compiling kata-deploy ====="
cd "$KATA_SRC_DIR/tools/packaging/kata-deploy/local-build"
export USE_CACHE="no"
export AGENT_POLICY=no
make || {
    echo "kata-deploy abnormal terminated, please check if all components have been compiled and packaged!"
    echo "components should include(./local-build/build/): "
    echo "  kata-static-agent.tar.xz"
    echo "  kata-static-coco-guest-components.tar.xz"
    echo "  kata-static-kernel.tar.xz"
    echo "  kata-static-kernel-virtcca-confidential.tar.xz"
    echo "  kata-static-nydus.tar.xz"
    echo "  kata-static-pause-image.tar.xz"
    echo "  kata-static-qemu.tar.xz"
    echo "  kata-static-qemu-virtcca-experimental.tar.xz"
    echo "  kata-static-rootfs-image-experimental.tar.xz"
    echo "  kata-static-rootfs-image.tar.xz"
    echo "  kata-static-virtiofsd.tar.xz"
    make merge-builds
}

# 10. Build and push kata-deploy image
echo "===== Building kata-deploy image ====="
cd "$KATA_SRC_DIR/tools/packaging/kata-deploy"
cp -v ./local-build/kata-static.tar.xz ./

# Build image (set proxy to access external resources)
docker build $DOCKER_BUILD_ARGS \
    -t kata-deploy . || {
    echo "kata-deploy image build failed!"
    exit 1
}

# Tag image
docker tag kata-deploy:latest $REGISTRY_DOMAIN:$REGISTRY_PORT/$KATA_DEPLOY_IMAGE_NAME

# Verify registry health before pushing
echo "> Verifying registry health status..."
if ! curl -sk --retry 3 --retry-delay 2 "https://$REGISTRY_DOMAIN:$REGISTRY_PORT/v2/_catalog" >/dev/null; then
    echo "> Registry not responding! Attempting to restart service..."
    docker restart "$REGISTRY_DOMAIN" || {
        echo "Registry restart failed!"
        exit 1
    }
    sleep 5
fi

# Push image (bypass any proxies)
echo "> Pushing image to local Registry (bypassing proxies)..."
(
    # Temporarily unset all proxies
    unset HTTP_PROXY
    unset HTTPS_PROXY
    unset http_proxy
    unset https_proxy

    # Set timeout
    timeout 300 docker push "$REGISTRY_DOMAIN:$REGISTRY_PORT/$KATA_DEPLOY_IMAGE_NAME"
) && {
    echo "> Image pushed successfully"
} || {
    exit_code=$?
    if [ $exit_code -eq 124 ]; then
        echo "> Push operation timed out! Check Registry performance"
    else
        echo "> Image push failed! Error code: $exit_code"
    fi
    echo "> Check Registry logs: docker logs $REGISTRY_DOMAIN"
    echo "> Attempt manual push:"
    echo "    unset HTTP_PROXY HTTPS_PROXY"
    echo "    docker push $REGISTRY_DOMAIN:$REGISTRY_PORT/$KATA_DEPLOY_IMAGE_NAME"
    exit 1
}

# 11. Deploy Operator
echo "===== Deploying Operator ($OPERATOR_VERSION) ====="

if [ -n "$HTTP_PROXY" ]; then
    git config --global --replace-all https.proxy $HTTP_PROXY
    git config --global --replace-all http.proxy $HTTP_PROXY
fi
kubectl apply -k "github.com/confidential-containers/operator/config/release?ref=$OPERATOR_VERSION" || {
    echo "Operator deployment failed!"
    exit 1
}

kubectl taint nodes --all node-role.kubernetes.io/control-plane:NoSchedule- || true
kubectl label nodes --all node.kubernetes.io/worker= || true

echo "Waiting for Operator initialization (15 seconds)..."
sleep 15


# 12. Deploy VirtCCA Kata
echo "===== Deploying VirtCCA Kata Runtime ====="
set +e
kubectl apply -f $KATA_SRC_DIR/build/virtCCA_sdk/kata-v3.15.0/conf/virtcca-kata-deploy.yaml
set -e

# 13. Verify deployment
echo "===== Verifying cluster status ====="
sleep 15
kubectl get pods -A

# 14. Create test Pod
echo "===== Creating test Pod ====="
cat > "$WORK_DIR/test-kata-qemu-virtcca.yaml" <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-kata-qemu-virtcca
  annotations:
    io.containerd.cri.runtime-handler: "kata-qemu-virtcca"
    io.katacontainers.config.hypervisor.kernel_params: "agent.debug_console agent.log=debug"
spec:
  runtimeClassName: kata-qemu-virtcca
  terminationGracePeriodSeconds: 5
  containers:
  - name: box-1
    image: $REGISTRY_DOMAIN:$REGISTRY_PORT/busybox:latest
    imagePullPolicy: Always
    command:
    - sh
    tty: true
EOF

kubectl apply -f "$WORK_DIR/test-kata-qemu-virtcca.yaml" || {
    echo "Test Pod creation failed!"
    exit 1
}

echo "Waiting for test Pod startup (15 seconds)..."
sleep 15
kubectl get pods

# 15. Launching pod with ctr
mkdir -p /etc/kata-containers
cp -f /opt/kata/share/defaults/kata-containers/configuration-qemu-virtcca.toml /etc/kata-containers/configuration.toml
sed -i 's/^\([[:space:]]*shared_fs[[:space:]]*=[[:space:]]*\)"[^"]*"/\1"virtio-fs"/' /etc/kata-containers/configuration.toml
cp -f /opt/kata/bin/containerd-shim-kata-v2 /usr/bin/containerd-shim-kata-v2
cp -f /opt/kata/bin/kata-runtime /usr/bin/kata-runtime

# 16. Completion notice
echo -e "\n===== Deployment successful! ====="
echo "Test commands:"
echo "  kubectl logs test-kata-qemu-virtcca"
echo "  kubectl exec -it test-kata-qemu-virtcca -- sh"
echo -e "\nFor cleanup, run:"
echo "  kubectl delete -f $WORK_DIR/virtcca-kata-deploy.yaml"
echo "  kubectl delete -k github.com/confidential-containers/operator/config/release?ref=$OPERATOR_VERSION"

}

# Compile Confidential Containers components
function compile_coco()
{
# Clean up old containers (avoid name conflicts)
echo -e "\n\033[33m[Cleanup] Removing old container '$CONTAINER_NAME' (if exists)\033[0m"
docker rm -f $CONTAINER_NAME >/dev/null 2>&1 || true

echo -e "\n\033[32m[1] Building build environment container image\033[0m"
if [ -n "$HTTP_PROXY" ]; then
    mkdir -p $DOCKERFILE_DIR/certs
    cp "$EULER_CERTS_PATH"/* $DOCKERFILE_DIR/certs

    sed -i '/RUN curl --proto '\''=https'\'' --tlsv1.2 -sSf https:\/\/sh.rustup.rs | sh -s -- -y --default-toolchain ${RUST_TOOLCHAIN}/i \
    COPY certs/* /usr/local/share/ca-certificates/\
    RUN update-ca-certificates' $DOCKERFILE_DIR/Dockerfile
fi
docker build $DOCKER_BUILD_ARGS -t $IMAGE_NAME $DOCKERFILE_DIR
if [ $? -ne 0 ]; then
    echo -e "\033[31mImage build failed! Check Dockerfile and proxy settings\033[0m"
    exit 1
fi

echo -e "\n\033[32m[2] Creating build environment container\033[0m"
docker run -itd --name $CONTAINER_NAME -v $KATA_SRC_DIR:/coco $DOCKER_RUN_ENV $IMAGE_NAME
if [ $? -ne 0 ]; then
    echo -e "\033[31mContainer creation failed! Check for name conflicts\033[0m"
    exit 1
fi

echo -e "\n\033[32m[3] Executing compilation tasks in container\033[0m"

# Execute all compilation commands in container (non-interactive)
docker exec $CONTAINER_NAME /bin/bash -c '
set -e
echo "=== Compiling guest-components ==="
cd /coco/build/guest-components
make clean
make build TEE_PLATFORM=virtcca

echo "=== Compiling measurement report tool ==="
cd /coco/build/guest-components/attestation-agent/attester
cargo build --no-default-features --features bin,virtcca-attester --bin evidence_getter --release

echo "=== Compiling coco_keyprovider ==="
cd /coco/build/guest-components/attestation-agent/coco_keyprovider
cargo build --release

echo "=== Compiling attestation-service ==="
cd /coco/build/trustee/attestation-service
make VERIFIER=virtcca-verifier

echo "=== Compiling RVPS ==="
cd /coco/build/trustee/rvps
make build

echo "=== Compiling KBS ==="
cd /coco/build/trustee/kbs
make background-check-kbs COCO_AS_INTEGRATION_TYPE=grpc

echo "=== Compiling kata-agent ==="
cd /coco/src/agent
make SECCOMP=no

echo "=== Compiling kata-shim and kata-runtime ==="
cd /coco
make -C src/runtime

echo "=== All compilation tasks completed ===="
'

echo -e "\n\033[32m[4] Cleaning up container environment\033[0m"
docker stop $CONTAINER_NAME >/dev/null
docker rm $CONTAINER_NAME >/dev/null

# Show artifact locations
echo -e "\n\033[32m[5] Build artifacts location:\033[0m"
echo -e "guest-components:     $KATA_SRC_DIR/build/guest-components/target/aarch64-unknown-linux-musl/release/"
echo -e "Other components (kbs/rvps/etc): $KATA_SRC_DIR/build/trustee/target/release/"

echo -e "\n\033[32m[6] Compilation process completed!\033[0m"
}

# Enhanced remote attestation service startup with logging
start_service_with_logging() {
    local name=$1
    local cmd=$2
    local log_file="$COCO_LOG_DIR/$name.log"

    # Clear old logs
    > "$log_file"

    echo "Starting $name..."
    echo "Command: $cmd" >> "$log_file"
    echo "Start time: $(date)" >> "$log_file"
    echo "------------------------" >> "$log_file"

    # Start service and redirect output to log file
    # Use bash -c to correctly parse environment variables
    bash -c "$cmd" >> "$log_file" 2>&1 &
    local pid=$!

    echo "Service PID: $pid" >> "$log_file"
    echo $pid > "$COCO_LOG_DIR/$name.pid"

    # Wait for service to start
    local timeout=10
    while [ $timeout -gt 0 ]; do
        if ps -p $pid > /dev/null; then
            # Check for errors in logs
            if grep -q "Error:" "$log_file"; then
                echo " $name start failed (PID: $pid)"
                echo "Error details:"
                grep "Error:" "$log_file" | tail -n 5
                return 1
            else
                echo " $name started successfully (PID: $pid)"
                return 0
            fi
        fi
        sleep 1
        ((timeout--))
    done

    echo " $name start timed out (PID: $pid)"
    return 1
}

# Set up remote attestation services
function rats()
{
# Clean and ensure directory structure
echo "===== Preparing directory structure ====="
rm -rf "$REMOTE_ATTESTATION_DIR"
mkdir -p \
  "$REMOTE_ATTESTATION_DIR" \
  "$COCO_LOG_DIR" \
  "$COCO_CONFIG_DIR" \
  /opt/confidential-containers/{kbs/repository,attestation-service/rvps} \
  /etc/attestation/attestation-service/verifier/virtcca/ \
  /opt/confidential-containers/attestation-service/token/simple/policies/opa

# Stop any existing services
echo "===== Stopping existing services ====="
pkill -f 'grpc-as|kbs|rvps' || true
sleep 1  # Ensure services fully stop

# Copy remote attestation components
echo "===== Copying remote attestation components ====="
if [ ! -d "$KATA_SRC_DIR/build/trustee/target/release" ]; then
    echo "Error: Could not find build output directory $KATA_SRC_DIR/build/trustee/target/release"
    exit 1
fi

cd "$KATA_SRC_DIR/build/trustee/target/release"
for component in grpc-as kbs rvps; do
    if [ ! -f "$component" ]; then
        echo "Error: Could not find component $component"
        exit 1
    fi
    cp -v "$component" "$REMOTE_ATTESTATION_DIR"
done

# Generate configuration files
echo "===== Generating configuration files ====="

# kbs-config-grpc.toml
cat > "$COCO_CONFIG_DIR/kbs-config-grpc.toml" <<EOF
[http_server]
sockets = ["0.0.0.0:8080"]
insecure_http = true

[attestation_token]
insecure_key = true

[attestation_service]
type = "coco_as_grpc"
as_addr = "http://127.0.0.1:50004"
timeout = 5

[admin]
insecure_api = true

[policy_engine]
policy_path = "/opt/confidential-containers/kbs/policy.rego"

[[plugins]]
name = "resource"
type = "LocalFs"
dir_path = "/opt/confidential-containers/kbs/repository"
EOF

# rvps-config.json
cat > "$COCO_CONFIG_DIR/rvps-config.json" <<EOF
{
    "storage": {
        "type": "LocalFs",
        "file_path": "/opt/confidential-containers/attestation-service/rvps"
    }
}
EOF

# as-config.json
cat > "$COCO_CONFIG_DIR/as-config.json" <<EOF
{
    "work_dir": "/opt/confidential-containers/attestation-service",
    "rvps_config": {
        "type": "GrpcRemote",
        "address": "http://127.0.0.1:50003"
    },
    "attestation_token_broker": {
        "type": "Simple",
        "duration_min": 5
    }
}
EOF

# OPA policy file
cat > /opt/confidential-containers/attestation-service/token/simple/policies/opa/default.rego <<EOF
package policy
import future.keywords.every
import future.keywords.if
default allow := false
allow if {
    print("Full Input:", input)
    print("Rim:", input["virtcca.realm.rim"])
    print("Ref:", data.reference)
    input["virtcca.realm.rim"] in data.reference["virtcca.realm.rim"]
}
EOF

# Certificate handling
echo "===== Certificate configuration ====="
echo "Place certificate files at: /etc/attestation/attestation-service/verifier/virtcca/"
echo "Press Enter to continue, or type 'skip' to skip..."
read -r response

# Database file locking handling
echo "===== Resolving database lock issues ====="
DB_PATH="/opt/confidential-containers/attestation-service/rvps"
if [ -f "$DB_PATH/db/LOCK" ]; then
    echo "Found old LOCK file, removing..."
    rm -f "$DB_PATH/db/LOCK" || true
fi

# Ensure database directory is writable
echo "Verifying database directory permissions..."
touch "$DB_PATH/testfile" 2>/dev/null && rm -f "$DB_PATH/testfile" || {
    echo "Error: Database directory not writable: $DB_PATH"
    echo "Attempting to modify permissions..."
    sudo chown -R $(whoami) "$DB_PATH" || {
        echo "Permission modification failed, check manually"
        exit 1
    }
}

# Start services
echo "===== Starting remote attestation services ====="

# Finally start KBS (using bash -c to correctly parse environment variables)
if ! start_service_with_logging "kbs" \
    "RUST_LOG=DEBUG $REMOTE_ATTESTATION_DIR/kbs -c $COCO_CONFIG_DIR/kbs-config-grpc.toml"
then
    echo "KBS startup failed! Check logs: $COCO_LOG_DIR/kbs.log"
    tail -n 20 "$COCO_LOG_DIR/kbs.log"
    exit 1
fi

# Then start RVPS
if ! start_service_with_logging "rvps" \
    "$REMOTE_ATTESTATION_DIR/rvps -a 127.0.0.1:50003 -c $COCO_CONFIG_DIR/rvps-config.json"
then
    echo "RVPS startup failed! Check logs: $COCO_LOG_DIR/rvps.log"
    tail -n 20 "$COCO_LOG_DIR/rvps.log"
    exit 1
fi

# Finally start AS
if ! start_service_with_logging "as" \
    "$REMOTE_ATTESTATION_DIR/grpc-as -s 127.0.0.1:50004 -c $COCO_CONFIG_DIR/as-config.json"
then
    echo "AS startup failed! Check logs: $COCO_LOG_DIR/as.log"
    tail -n 20 "$COCO_LOG_DIR/as.log"
    exit 1
fi

# Let services stabilize
sleep 3

# Verify service status
echo -e "\n===== Service status ====="
echo "Service processes:"
ps -ef | grep -E 'kbs|rvps|grpc-as' | grep -v grep

echo -e "\nService log locations:"
ls -l $COCO_LOG_DIR/*.log

echo -e "\n===== Remote attestation environment deployment completed ====="
echo "KBS endpoint: http://0.0.0.0:8080"
echo "RVPS endpoint: 127.0.0.1:50003"
echo "AS endpoint: 127.0.0.1:50004"
}

# Feature demo: launching an Encrypted Image
function launch_encrypt_image()
{
mkdir encrypt && cd encrypt
mkdir output
KEY_FILE="image_key"

# Generating an Encryption Key
head -c 32 /dev/urandom | openssl enc > "$KEY_FILE"

# Create a container and use the generated key to encrypt the plaintext image within the container.
echo "If using a proxy, please ensure the ${EULER_CERTS_PATH}/Huawei_Web_Secure_Internet_Gateway_CA.crt exists"
docker run $MOUNT_GATEWAY_CA -v "$PWD/output:/output" $DOCKER_RUN_ENV $ENC_CONTAINER_IMAGE /encrypt.sh -k "$(base64 < image_key)" -i "kbs:///default/image_key/$ENC_KEY_NAME" -s "docker://$PLAIN_IMAGE:latest" -d dir:/output

# Push encrypted image to local image repository
skopeo copy dir:output "docker://$REGISTRY_DOMAIN:$REGISTRY_PORT/$PLAIN_IMAGE:encrypted"

# Deploying the Encryption Key
if [ ! -d "${KBS_ENC_KEY_PATH}" ]; then
    mkdir -p "${KBS_ENC_KEY_PATH}" || {
        echo "error: can not create directory ${KBS_ENC_KEY_PATH}" >&2
        exit 1
    }
    echo "create directory ${KBS_ENC_KEY_PATH} successfully"
fi
cp "$KEY_FILE" "$KBS_ENC_KEY_PATH/$ENC_KEY_NAME"

# Configure the KBS policy
echo "===== Configure the KBS policy ====="
mkdir -p "$KBS_SECURITY_POLICY"
cat > "$KBS_SECURITY_POLICY" <<EOF
{
    "default": [
        {
            "type": "reject"
        }
    ],
    "transports": {
        "docker": {
            "$REGISTRY_DOMAIN:$REGISTRY_PORT": [
                {
                    "type": "insecureAcceptAnything"
                }
            ]
        }
    }
}
EOF

# Create configuration for launching the encrypted image
cat > "$PWD/test-enc.yaml" <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-enc
  annotations:
    io.containerd.cri.runtime-handler: "kata-qemu-virtcca"
    io.katacontainers.config.hypervisor.kernel_params: "agent.debug_console agent.log=debug agent.image_policy_file=kbs:///default/security-policy/test agent.enable_signature_verification=true agent.guest_components_rest_api=all agent.aa_kbc_params=cc_kbc::http:$IP_ADDR:8080"
spec:
  runtimeClassName: kata-qemu-virtcca
  terminationGracePeriodSeconds: 5
  containers:
  - name: box-1
    image: $REGISTRY_DOMAIN:$REGISTRY_PORT/$PLAIN_IMAGE:encrypted
    imagePullPolicy: Always
    command:
    - sh
    tty: true
EOF

# Completion notice
echo -e "===== Complete the preparation for launching the encrypted image. ====="
echo "Test commands:"
echo "1) inspect encrypted image:"
echo    "skopeo inspect "docker://$REGISTRY_DOMAIN:$REGISTRY_PORT/$PLAIN_IMAGE:encrypted""
echo "2) launch encrypted image:"
echo    "kubectl apply -f $PWD/test-enc.yaml"
}

function install_cosign()
{
source_profile

# Check if cosign is installed
if command -v cosign &> /dev/null; then
    echo "cosign installed: $(cosign version | head -n 1)"
    return 0
fi

echo "Installing cosign ${COSIGN_VERSION}..."

# Download binary
if ! wget -q --show-progress -O "${COSIGN_TEMP_FILE}" "${DOWNLOAD_URL}"; then
    echo "Error: Download failed! Please check network connection and URL" >&2
    exit 1
fi

# Verify downloaded file
if [ ! -f "${COSIGN_TEMP_FILE}" ]; then
    echo "Error: Downloaded file not found!" >&2
    exit 1
fi

# Set execute permissions
if ! chmod +x "${COSIGN_TEMP_FILE}"; then
    echo "Error: Failed to set execute permissions!" >&2
    exit 1
fi

# Install to system directory
if ! sudo mv "${COSIGN_TEMP_FILE}" "${INSTALL_PATH}"; then
    echo "Error: Installation failed! Requires sudo privileges" >&2
    rm -f "${COSIGN_TEMP_FILE}"
    exit 1
fi

# Verify installation
if cosign version &> /dev/null; then
    echo "cosign successfully installed"
else
    echo "Warning: Installation completed but verification failed" >&2
    exit 1
fi
}

function install_skopeo()
{
source_profile

# If installed, return directly
if command -v skopeo &>/dev/null; then
    echo "[INFO]: Skopeo is already installed" >&2
    return 0
fi

# Check existing installation
if command -v go &>/dev/null; then
    echo "[INFO] Go is already installed: $(go version)"
else
    echo "[INFO] Installing Go ${GO_VERSION}..."

    # Download Go
    GO_TAR="go${GO_VERSION}.${GO_ARCH}.tar.gz"
    wget -q --show-progress -P "${TMP_DIR}" \
        "https://golang.google.cn/dl/${GO_TAR}" || {
        echo "[ERROR] Failed to download Go archive" >&2
        exit 1
    }

    # Install Go
    sudo tar -zxf "${TMP_DIR}/${GO_TAR}" -C "${GO_INSTALL_DIR}" || {
        echo "[ERROR] Failed to extract Go archive" >&2
        exit 1
    }
fi

# Environment setup
if ! grep -q "GO_HOME" /etc/profile; then
    echo "export GO_HOME=${GO_INSTALL_DIR}/go" | sudo tee -a /etc/profile >/dev/null
    echo "export GOPATH=${GOPATH_DIR}" | sudo tee -a /etc/profile >/dev/null
    echo "export PATH=\${GO_HOME}/bin:\${GOPATH}/bin:\${PATH}" | sudo tee -a /etc/profile >/dev/null
fi

# Source environment
source_profile

# Verify Go installation
if ! command -v go &>/dev/null; then
    echo "[ERROR] Go installation verification failed" >&2
    exit 1
fi

# Install build dependencies
echo "[INFO] Installing system dependencies..."
sudo yum install -y \
    gpgme-devel \
    device-mapper-devel \
    git \
    make \
    gcc || {
    echo "[ERROR] Failed to install dependencies" >&2
    exit 1
}

# Build Skopeo
SKOPEO_SRC="${GOPATH}/src/github.com/containers/skopeo"
if [[ ! -d "${SKOPEO_SRC}" ]]; then
    echo "[INFO] Cloning Skopeo ${SKOPEO_VERSION}..."
    mkdir -p "${SKOPEO_SRC}"
    git clone -q -b "${SKOPEO_VERSION}" \
        https://github.com/containers/skopeo.git "${SKOPEO_SRC}" || {
        echo "[ERROR] Failed to clone Skopeo repository" >&2
        exit 1
    }
fi

echo "[INFO] Building Skopeo..."
(
    cd "${SKOPEO_SRC}" || exit 1
    make bin/skopeo || {
        echo "[ERROR] Failed to build Skopeo" >&2
        exit 1
    }
    sudo cp -f bin/skopeo /usr/local/bin/
    sudo mkdir -p /etc/containers
    sudo cp -f default-policy.json /etc/containers/policy.json
) || exit 1

# Verify installation
if ! command -v skopeo &>/dev/null; then
    echo "[ERROR] Skopeo installation verification failed" >&2
    exit 1
fi

echo "[SUCCESS] Installation completed: $(skopeo --version)"
}

function configurate_nydus()
{
source_profile
mkdir nydus && cd nydus

# Create working directory
mkdir -p "${NYDUS_WORK_DIR}" && cd "${NYDUS_WORK_DIR}"
echo "Created working directory: ${NYDUS_WORK_DIR}"

# Install dependencies
echo "Installing system dependencies..."
sudo yum install -y wget tar gzip jq

# Install nydus tools (nydusd, nydus-image, etc.)
echo "Installing nydus tools ${NYDUS_VERSION}..."
wget -q "https://github.com/dragonflyoss/nydus/releases/download/${NYDUS_VERSION}/nydus-static-${NYDUS_VERSION}-linux-arm64.tgz"
tar -zxvf "nydus-static-${NYDUS_VERSION}-linux-arm64.tgz"
cd nydus-static
sudo install -m 755 nydusd nydus-image nydusify nydusctl nydus-overlayfs "${NYDUS_BIN_DIR}"
cd ..

# Install nydus-snapshotter
echo "Installing nydus-snapshotter ${SNAPSHOTTER_VERSION}..."
wget -q "https://github.com/containerd/nydus-snapshotter/releases/download/${SNAPSHOTTER_VERSION}/nydus-snapshotter-${SNAPSHOTTER_VERSION}-linux-arm64.tar.gz"
tar -zxvf "nydus-snapshotter-${SNAPSHOTTER_VERSION}-linux-arm64.tar.gz"
sudo install -m 755 bin/containerd-nydus-grpc "${NYDUS_BIN_DIR}"

# Install nerdctl
echo "Installing nerdctl v${NERDCTL_VERSION}..."
wget -q "https://github.com/containerd/nerdctl/releases/download/v${NERDCTL_VERSION}/nerdctl-${NERDCTL_VERSION}-linux-arm64.tar.gz"
tar -zxvf "nerdctl-${NERDCTL_VERSION}-linux-arm64.tar.gz"
sudo install -m 755 nerdctl "${NYDUS_BIN_DIR}"

# Configure nydusd
echo "Configuring nydusd..."
sudo mkdir -p /etc/nydus
sudo tee /etc/nydus/nydusd-config.fusedev.json > /dev/null <<'EOF'
{
  "device": {
    "backend": {
      "type": "registry",
      "config": {
        "scheme": "https",
        "skip_verify": false,
        "timeout": 5,
        "connect_timeout": 5,
        "retry_limit": 4,
        "auth": ""
      }
    },
    "cache": {
      "type": "blobcache",
      "config": {
        "work_dir": "cache"
      }
    }
  },
  "mode": "direct",
  "digest_validate": false,
  "iostats_files": false,
  "enable_xattr": true,
  "fs_prefetch": {
    "enable": true,
    "threads_count": 4
  }
}
EOF

# Download and modify nydus-snapshotter config
echo "Configuring nydus-snapshotter..."
wget -q "https://raw.githubusercontent.com/containerd/nydus-snapshotter/refs/tags/${SNAPSHOTTER_VERSION}/misc/snapshotter/config.toml"
sudo sed -i \
  -e "s|^root = .*|root = \"${CONTAINERD_ROOT}/io.containerd.snapshotter.v1.nydus\"|" \
  -e "s|^nydusd_path = .*|nydusd_path = \"${NYDUS_BIN_DIR}/nydusd\"|" \
  -e "s|^nydusimage_path = .*|nydusimage_path = \"${NYDUS_BIN_DIR}/nydus-image\"|" \
  config.toml

# Update virtcca-kata-deploy components
echo "Updating virtcca-kata-deploy components..."
# Stop existing nydus-snapshotter
if pgrep containerd-nydus-grpc >/dev/null; then
  sudo pkill -9 containerd-nydus-grpc
fi

# Copy updated components
sudo mkdir -p /opt/confidential-containers/{bin,share/nydus-snapshotter}
sudo cp -f bin/containerd-nydus-grpc /opt/confidential-containers/bin/
sudo cp -f config.toml /opt/confidential-containers/share/nydus-snapshotter/config-coco-guest-pulling.toml

# Configure containerd
echo "Configuring containerd..."
sudo mkdir -p /etc/containerd
if [ ! -f /etc/containerd/config.toml ]; then
  sudo containerd config default | sudo tee /etc/containerd/config.toml >/dev/null
fi

# Add nydus configuration to containerd
sed -i '/^[[:space:]]*\[proxy_plugins\][[:space:]]*$/d' /etc/containerd/config.toml

if ! grep -q "proxy_plugins.nydus" /etc/containerd/config.toml; then
  sudo tee -a /etc/containerd/config.toml > /dev/null <<'EOF'

[plugins."io.containerd.grpc.v1.cri".containerd]
  default_runtime_name = "runc"
  disable_snapshot_annotations = false
  discard_unpacked_layers = false
  ignore_rdt_not_enabled_errors = false
  no_pivot = false
  snapshotter = "nydus"

[proxy_plugins]
  [proxy_plugins.nydus]
    type = "snapshot"
    address = "/run/containerd-nydus/containerd-nydus-grpc.sock"
EOF
fi

# Enable shared_fs (virtio-fs)
echo "Enabling virtio-fs..."
sudo cp /usr/libexec/virtiofsd /opt/kata/libexec/
sudo sed -i 's/^\([[:space:]]*shared_fs[[:space:]]*=[[:space:]]*\)"[^"]*"/\1"virtio-fs"/' "${KATA_CONFIG}"

# Restart containerd
echo "Restarting containerd..."
sudo systemctl restart containerd

# Verify installation
echo "Verifying installation..."
command -v nydusd
command -v containerd-nydus-grpc
sudo containerd-nydus-grpc --version

echo "Nydus setup completed successfully!"
}

# Main command dispatcher
case "$1" in
    containerd*)
        install_containerd
        ;;
    k8s*)
        init_k8s
        ;;
    kdeploy*)
        kata_deploy
        ;;
    rats*)
        compile_coco
        rats
        install_cosign
        install_skopeo
        ;;
    encrypt*)
        launch_encrypt_image
        ;;
    nydus*)
        configurate_nydus
        ;;
    all*)
        install_containerd
        init_k8s
        kata_deploy
        compile_coco
        rats
        install_cosign
        install_skopeo
        configurate_nydus
        ;;
    *)
        echo "Error: Unknown command '$1'"
        exit 1
        ;;
esac
