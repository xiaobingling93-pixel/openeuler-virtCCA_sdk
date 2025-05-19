cmake_minimum_required(VERSION 3.22)
project(mpc_demo)

set(CMAKE_CXX_STANDARD 14)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -g")
set(CMAKE_C_FLAGS "-g ${CMAKE_C_FLAGS}")

add_executable(${PROJECT_NAME} TestMPCTee.cpp)

add_definitions(-DLIBFUSE_BUILT_WITH_VERSIONED_SYMBOLS)

target_include_directories(${PROJECT_NAME}
	PUBLIC /usr/local/include/
        )

target_link_directories(${PROJECT_NAME}
       PUBLIC /usr/local/lib
        )
target_link_libraries(${PROJECT_NAME} data_guard data_guard_common hitls_bsl hitls_crypto securec mpc_tee)
