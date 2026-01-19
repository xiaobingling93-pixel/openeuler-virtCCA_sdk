#!/bin/bash
set -x

ROOT_DIR=$(cd $(dirname $0);pwd)

function attestation() {
    echo "build attestation sdk"
    cd ${ROOT_DIR}/attestation/sdk
    cmake -S . -B build
    cmake --build build
}

function image_key() {
    echo "build image key sdk"
    cd ${ROOT_DIR}/image_key/sdk
    cmake -S . -B build
    cmake --build build
}

case $1 in
    attest) attestation;;
    image) image_key;;
    *)
        attestation
        image_key
        ;;
esac