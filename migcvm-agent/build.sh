#!/bin/bash

# 
BUILD_TYPE="Release"
BUILD_DEBUG_TOOL=false
CLEAN=false

for arg in "$@"; do
    case $arg in
        --clean)
            CLEAN=true
            ;;
        *)
            echo "Unknown argument: $arg"
            exit 1
            ;;
    esac
done

# 
if [[ $CLEAN == true ]]; then
    echo "Cleaning build directory..."
    rm -rf build
    exit 1
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
    make migcvm-agent || {
        echo "Build failed"
        exit 1
    }
echo "Build successful! Executable is located at: build/migvm_agent"