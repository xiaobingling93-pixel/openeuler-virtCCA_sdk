
#!/bin/sh

set -eux

PROXY_CERT_PATH="/etc/pki/ca-trust/source/anchors"

TARGET_PATH=(
	"tools/osbuilder/image-builder"
	"tools/osbuilder/rootfs-builder/ubuntu"
	"tools/packaging"
	"tools/packaging/kata-deploy"
	"tools/packaging/kata-deploy/local-build/dockerbuild"
	"tools/packaging/static-build/agent"
	"tools/packaging/static-build/coco-guest-components"
	"tools/packaging/static-build/initramfs"
	"tools/packaging/static-build/kernel"
	"tools/packaging/static-build/pause-image"
	"tools/packaging/static-build/qemu"
	"tools/packaging/static-build/shim-v2"
	"tools/packaging/static-build/virtiofsd/musl"
)

function deploy_proxy_certs()
{
	for dir in "${TARGET_PATH[@]}"; do
		mkdir -p "${dir}/certs"
		cp "$PROXY_CERT_PATH"/* "${dir}/certs"/
	done
}

deploy_proxy_certs
