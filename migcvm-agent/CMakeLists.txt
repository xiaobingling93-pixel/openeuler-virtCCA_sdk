cmake_minimum_required(VERSION 3.10)
project(MIGVM_Agent)

# Set build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Release" CACHE STRING "Choose the type of build" FORCE)
    set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS "Debug" "Release" "MinSizeRel" "RelWithDebInfo")
endif()

message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")

# Set C standard
set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Use host compiler
message(STATUS "Using host compiler")

# Add executable
# Main executable
add_executable(migvm_agent 
    migvm_agent.c
    migcvm_tsi/migcvm_tsi.c
    socket_agent/host_socket_agent.c
)

# Debug tool
add_executable(socket-send
    debug/socket-send.c
)
target_include_directories(socket-send PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/socket_agent
)

add_executable(tsi-test
    debug/tsi-test.c
    migcvm_tsi/migcvm_tsi.c
)
target_include_directories(tsi-test PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/migcvm_tsi
)

# Build debug tool in debug mode
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
    add_dependencies(migvm_agent socket-send tsi-test)
endif()

# Include directories
target_include_directories(migvm_agent PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/migcvm_tsi
    ${CMAKE_CURRENT_SOURCE_DIR}/socket_agent
)

# Common compile options
target_compile_options(migvm_agent PRIVATE
    $<$<CONFIG:Debug>:-O0 -g3 -DDEBUG>
    $<$<NOT:$<CONFIG:Debug>>:-O2 -DNDEBUG>
    -Wall
    -Wextra
    -Werror
    -fPIC
)

target_compile_options(socket-send PRIVATE
    -g3 -O0 -DDEBUG
    -Wall
    -Wextra
    -fPIC
)

target_compile_options(tsi-test PRIVATE
    -g3 -O0 -DDEBUG
    -Wall
    -Wextra
    -fPIC
)

# General Compiler Options
target_compile_options(migvm_agent PRIVATE
    -Wall
    -Wextra
    -Werror
    -fPIC
)

target_link_options(migvm_agent PRIVATE
    -Wl,--no-undefined
)

# Link libraries
target_link_libraries(migvm_agent PRIVATE
    pthread
)

# Install target
install(TARGETS migvm_agent
    RUNTIME DESTINATION bin
)

