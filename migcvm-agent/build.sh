#!/bin/bash

# 
BUILD_TYPE="Release"
BUILD_DEBUG_TOOL=false
CLEAN=false

for arg in "$@"; do
    case $arg in
        --debug)
            BUILD_TYPE="Debug"
            ;;
        --build-debug-tool)
            BUILD_DEBUG_TOOL=true
            ;;
        --clean)
            CLEAN=true
            ;;
    esac
done

# 
if [[ $CLEAN == true ]]; then
    echo "Cleaning build directory..."
    rm -rf build
fi

# 
mkdir -p build
cd build || exit

# cmake
echo "Running cmake with build type: ${BUILD_TYPE}..."
cmake -DCMAKE_BUILD_TYPE=${BUILD_TYPE} .. || {
    echo "CMake failed"
    exit 1
}

# 
echo "Building project..."
if [[ $BUILD_DEBUG_TOOL == true ]]; then
    echo "Building debug tool only..."
    make socket-send tsi_test || {
        echo "Debug tool build failed"
        exit 1
    }
    echo "Debug tool built successfully! Executable is located at: build/socket-send"
elif [[ $BUILD_TYPE == "Debug" ]]; then
    echo "Building in debug mode (both main agent and debug tool)..."
    make migvm_agent socket-send tsi-test || {
        echo "Build failed"
        exit 1
    }
    echo "Build successful! Executables are located at: build/migvm_agent and build/socket-send"
else
    make migvm_agent || {
        echo "Build failed"
        exit 1
    }
    echo "Build successful! Executable is located at: build/migvm_agent"
fi

