#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.
set -euo pipefail

###############################################################################
# build_rpm.sh — One-click RPM packaging for KDC
#
# Produces:
#   output/<arch>/kdcagent-<version>-<release>.<arch>.rpm
#   output/<arch>/kdcproxy-<version>-<release>.<arch>.rpm
#
# Usage:
#   ./scripts/build_rpm.sh              # Normal build (arch check enabled)
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$PROJECT_ROOT/conf/common.json"
SPECS_DIR="$PROJECT_ROOT/conf/specs"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Parse common.json ────────────────────────────────────────────────────────
if [[ ! -f "$CONFIG_FILE" ]]; then
    error "Config file not found: $CONFIG_FILE"
    exit 1
fi

VERSION=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['version'])")
RELEASE=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['release'])")

if [[ -z "$VERSION" || -z "$RELEASE" ]]; then
    error "Failed to parse version/release from $CONFIG_FILE"
    exit 1
fi

info "Version: $VERSION, Release: $RELEASE"

# ── Architecture check ───────────────────────────────────────────────────────
ARCH=$(uname -m)

if [[ "${KDC_SKIP_ARCH_CHECK:-0}" != "1" && "$ARCH" != "aarch64" ]]; then
    error "KDC only supports aarch64 architecture. Current: $ARCH"
    error "Please run this script on a KunPeng (aarch64) server."
    exit 1
fi

info "Architecture: $ARCH"

# ── Prerequisites check ──────────────────────────────────────────────────────
for cmd in rpmbuild cargo; do
    if ! command -v "$cmd" &>/dev/null; then
        error "Required command not found: $cmd"
        exit 1
    fi
done

# ── Clean previous RPM output ──────────────────────────────────────────────
info "Cleaning previous RPM output..."

rm -rf "$PROJECT_ROOT/output"

info "Clean complete."

# ── Build all artifacts ──────────────────────────────────────────────────────
info "Building kdc_agent (release)..."
cargo build --release --package kdc_agent

info "Building kdc_proxy (release)..."
cargo build --release --package kdc_proxy

# ── Verify build artifacts ───────────────────────────────────────────────────
info "Verifying build artifacts..."

REQUIRED_FILES=(
    "$PROJECT_ROOT/target/release/kdc_agent"
    "$PROJECT_ROOT/target/release/libkdc_agent.so"
    "$PROJECT_ROOT/target/release/libkdc_proxy.so"
)

for f in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$f" ]]; then
        error "Missing required artifact: $f"
        exit 1
    fi
done

info "All build artifacts present."

# ── Prepare rpmbuild workspace ───────────────────────────────────────────────
RPMBUILD_DIR=$(mktemp -d /tmp/kdc-rpmbuild.XXXXXX)
trap 'rm -rf "$RPMBUILD_DIR"' EXIT

mkdir -p "$RPMBUILD_DIR"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

# ── Stage kdcagent tarball ──────────────────────────────────────────────────
KDCAGENT_STAGE="$RPMBUILD_DIR/kdcagent-$VERSION"
mkdir -p "$KDCAGENT_STAGE"

cp "$PROJECT_ROOT/target/release/kdc_agent"         "$KDCAGENT_STAGE/"
cp "$PROJECT_ROOT/target/release/libkdc_agent.so"   "$KDCAGENT_STAGE/"
cp "$PROJECT_ROOT/kdc_agent/conf/agent_conf.json"   "$KDCAGENT_STAGE/"

cp "$PROJECT_ROOT/kdc_agent/conf/kdcagent_launcher.service" \
   "$KDCAGENT_STAGE/kdcagent.service"

cd "$RPMBUILD_DIR"
tar czf "SOURCES/kdcagent-$VERSION.tar.gz" "kdcagent-$VERSION"

# ── Stage kdcproxy tarball ──────────────────────────────────────────────────
KDCPROXY_STAGE="$RPMBUILD_DIR/kdcproxy-$VERSION"
mkdir -p "$KDCPROXY_STAGE"

cp "$PROJECT_ROOT/target/release/libkdc_proxy.so"   "$KDCPROXY_STAGE/"

tar czf "SOURCES/kdcproxy-$VERSION.tar.gz" "kdcproxy-$VERSION"

# ── Copy spec files ──────────────────────────────────────────────────────────
cp "$SPECS_DIR/kdcagent.spec" "$RPMBUILD_DIR/SPECS/"
cp "$SPECS_DIR/kdcproxy.spec" "$RPMBUILD_DIR/SPECS/"

# ── Build RPMs ───────────────────────────────────────────────────────────────
RPMBUILD_COMMON=(
    --define "_topdir $RPMBUILD_DIR"
    --define "kdc_version $VERSION"
    --define "kdc_release $RELEASE"
    --define "debug_package %{nil}"
)

info "Building kdcagent RPM..."
rpmbuild -bb "$RPMBUILD_DIR/SPECS/kdcagent.spec" "${RPMBUILD_COMMON[@]}"

info "Building kdcproxy RPM..."
rpmbuild -bb "$RPMBUILD_DIR/SPECS/kdcproxy.spec" "${RPMBUILD_COMMON[@]}"

# ── Collect output ───────────────────────────────────────────────────────────
OUTPUT_DIR="$PROJECT_ROOT/output/$ARCH"
mkdir -p "$OUTPUT_DIR"

find "$RPMBUILD_DIR/RPMS" -name '*.rpm' -exec cp {} "$OUTPUT_DIR/" \;

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
info "========================================="
info "  RPM Build Complete"
info "========================================="
info "  Version : $VERSION-$RELEASE"
info "  Arch    : $ARCH"
info "  Output  : $OUTPUT_DIR/"
echo ""

for rpm_file in "$OUTPUT_DIR"/*.rpm; do
    if [[ -f "$rpm_file" ]]; then
        size=$(du -h "$rpm_file" | cut -f1)
        info "  $(basename "$rpm_file") ($size)"
    fi
done

echo ""
info "Install commands:"
info "  sudo rpm -ivh $OUTPUT_DIR/kdcagent-$VERSION-$RELEASE.$ARCH.rpm"
info "  sudo rpm -ivh $OUTPUT_DIR/kdcproxy-$VERSION-$RELEASE.$ARCH.rpm"
