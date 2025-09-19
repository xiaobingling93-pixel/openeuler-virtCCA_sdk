cmake_minimum_required(VERSION 3.5.1)
project(migcvm-agent)

set(CMAKE_C_FLAGS "-fPIE ${CMAKE_C_FLAGS}")

# Set source file
set(SOURCES src/rats-mig-agent.c 
    src/token_parse.c 
    src/token_validate.c 
    src/platform_verify.c
    src/ima_measure.c
    src/event_log.c
    src/rem.c
    src/firmware_state.c
    src/binary_blob.c
    src/verify.c
    src/config.c
    src/host_socket_agent.c
    src/utils.c)

# Generate bin file
add_executable(${PROJECT_NAME} ${SOURCES})

# Debug tool
set(DEBUG_TOOL debug/socket-tool.c)
add_executable(socket-tool ${DEBUG_TOOL})

target_include_directories(${PROJECT_NAME} PRIVATE
    rats-tls/src/include
    inc/
    /usr/local/include/qcbor
    /usr/include
    /usr/local/lib
    /usr/include/openssl
    /usr/local/include/t_cose
)

link_directories(/lib64/
                /usr/lib/rats-tls/
                /usr/lib64
                /usr/local/lib64)

find_package(OpenSSL REQUIRED)
find_library(RATS_TLS_LIB rats_tls PATHS /usr/lib/rats-tls/)
find_library(QCBOR_LIB qcbor)
find_library(T_COSE_LIB t_cose)

target_link_libraries(${PROJECT_NAME} PRIVATE 
    m
    OpenSSL::Crypto
    ${T_COSE_LIB}
    ${QCBOR_LIB}
    ${RATS_TLS_LIB}
)

install(TARGETS ${PROJECT_NAME}
        DESTINATION ${RATS_TLS_INSTALL_BIN_PATH})