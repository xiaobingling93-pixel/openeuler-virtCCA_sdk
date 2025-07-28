# CMake version
cmake_minimum_required(VERSION 3.16)
# Project
project(gen_rim_ref LANGUAGES C)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
find_package(OpenSSL REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GLIB REQUIRED glib-2.0)
pkg_check_modules(GOBJECT REQUIRED gobject-2.0)

# Build mode
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Debug CACHE STRING "Build type" FORCE)
endif()
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")

# Build options
option(BUILD_RIM_GEN "Compile rim reference generator" ON)

# Config of golang qemu_generator
set(GO_LIB_OUTPUT_DIR ${CMAKE_SOURCE_DIR}/lib)
set(GO_LIB_SRC_DIR ${CMAKE_SOURCE_DIR}/inc/qemu_generator/src)
set(GO_LIB_NAME libQemuGen)

# Generate Go lib
add_custom_command(
    OUTPUT ${GO_LIB_OUTPUT_DIR}/${GO_LIB_NAME}.a
    COMMAND ${CMAKE_COMMAND} -E remove_directory ${GO_LIB_OUTPUT_DIR}
    COMMAND ${CMAKE_COMMAND} -E make_directory ${GO_LIB_OUTPUT_DIR}
    COMMAND cd ${GO_LIB_SRC_DIR} &&
            go build -buildmode=c-archive -trimpath -o ${GO_LIB_OUTPUT_DIR}/${GO_LIB_NAME}.a
    COMMENT "Building Go library..."
)
add_custom_target(libQemuGen DEPENDS ${GO_LIB_OUTPUT_DIR}/${GO_LIB_NAME}.a)

# Set source file
file(GLOB SOURCES
    src/gen_rim_ref.c
    src/gen_dtb.c
    src/cJSON.c
)

# Set include directory
include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/inc
    ${CMAKE_CURRENT_SOURCE_DIR}/lib  # include lib/libQemuGen.h
    ${GLIB_INCLUDE_DIRS}
    ${GOBJECT_INCLUDE_DIRS}
)

# Generate excutable
add_executable(${PROJECT_NAME} ${SOURCES})
add_dependencies(${PROJECT_NAME} libQemuGen)

# Link library
target_link_libraries(${PROJECT_NAME} PRIVATE
    OpenSSL::SSL
    OpenSSL::Crypto
    ${GLIB_LIBRARIES}
    ${GOBJECT_LIBRARIES}
    ${GO_LIB_OUTPUT_DIR}/${GO_LIB_NAME}.a  # static lib at the end
)
target_compile_definitions(${PROJECT_NAME} PRIVATE LOG_PRINT=0)

# Set install path
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/output)
set_directory_properties(PROPERTIES
    ADDITIONAL_MAKE_CLEAN_FILES "${CMAKE_RUNTIME_OUTPUT_DIRECTORY};${GO_LIB_OUTPUT_DIR}"
)

if(BUILD_RIM_GEN)
    message(STATUS "Build gen_rim_ref: on")
endif()
