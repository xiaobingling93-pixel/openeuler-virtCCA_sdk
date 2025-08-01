cmake_minimum_required(VERSION 3.16)

project(kcal_middleware LANGUAGES C CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(libkcal)

include_directories(${CMAKE_CURRENT_SOURCE_DIR})

add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/kcal)

install(DIRECTORY kcal
        DESTINATION include
        FILES_MATCHING PATTERN "*.h"
)
