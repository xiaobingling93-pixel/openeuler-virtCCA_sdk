cmake_minimum_required(VERSION 3.16)
project(tsi-samples
    LANGUAGES C)

find_package(OpenSSL REQUIRED)

include_directories(
    include
    QCBOR/inc
    t_cose/inc
)

set(COMMON_SOURCES
    src/binary_blob.c
    src/event_log.c
    src/firmware_state.c
    src/verify.c
    src/rem.c
)

add_executable(server 
    src/server.c
    src/utils.c
)
target_link_libraries(server vccaattestation)

add_executable(client 
    src/client.c 
    src/token_parse.c 
    src/token_validate.c 
    src/platform_verify.c
    src/utils.c
    ${COMMON_SOURCES}
)

target_link_libraries(client t_cose qcbor)
target_link_libraries(client OpenSSL::Crypto)
target_link_libraries(client m)

target_link_directories(client PRIVATE QCBOR t_cose/build)
