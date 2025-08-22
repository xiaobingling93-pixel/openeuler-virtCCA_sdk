#!/bin/bash

IP_ADDRESS=$(hostname -I | awk '{print $1}')
CONFIG_FILE="kubeadm-init.yaml"

sed -i "s/^  advertiseAddress: .*/  advertiseAddress: ${IP_ADDRESS}/" "$CONFIG_FILE"
sed -i "s|criSocket: unix:///var/run/containerd/containerd.sock|criSocket: unix:///run/containerd/containerd.sock|" "$CONFIG_FILE"
sed -i "s/^kubernetesVersion: .*/kubernetesVersion: 1.32.4/" "$CONFIG_FILE"
sed -i '/serviceSubnet: 10.96.0.0\/12/a\  podSubnet: 10.244.0.0/16' "$CONFIG_FILE"
sed -i '/imagePullSerial: true/d' "$CONFIG_FILE"

cat <<EOF >> "$CONFIG_FILE"
---
kind: KubeletConfiguration
apiVersion: kubelet.config.k8s.io/v1beta1
cgroupDriver: cgroupfs
EOF