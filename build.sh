#!/bin/bash
set -x

ROOT_DIR=$(cd $(dirname $0);pwd)

function attestation() {
    echo "build attestation sdk"
    cd ${ROOT_DIR}/attestation/sdk
    cmake -S . -B build
    cmake --build build
}

function sealing_key() {
    echo "build sealing key sdk"
    cd ${ROOT_DIR}/sealing_key/sdk
    cmake -S . -B build
    cmake --build build
}

case $1 in
    attest) attestation;;
    sealing) sealing_key;;
    *)
        attestation
        sealing_key
        ;;
esac