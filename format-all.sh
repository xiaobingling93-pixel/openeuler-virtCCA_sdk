#!/bin/bash

# Check if clang-format exists
if ! command -v clang-format &> /dev/null; then
    echo "clang-format not found"
    exit 1
fi

# Check if cmake-format exists
if ! command -v cmake-format &> /dev/null; then
    echo "cmake-format not found"
    exit 1
fi

# format c/c++ code
find . -name "*.cpp" -o -name "*.hpp" -o -name "*.h" | xargs clang-format -i

# format cmake code
find . -name "CMakeLists.txt" -exec cmake-format -i {} \;
