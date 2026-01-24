cmake_minimum_required(VERSION 3.5.1)
project(migcvm-agent)
set(CMAKE_C_FLAGS "-fPIE ${CMAKE_C_FLAGS}")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fstack-protector-strong -D_FORTIFY_SOURCE=2")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -fPIE -Wl,-z,relro -Wl,-z,now -Wl,-z,noexecstack -s")
add_subdirectory(src/attest)
add_subdirectory(src/migcvm_tsi)

set(SOURCES src/migcvm-agent.c
    src/socket/host_socket_agent.c
    src/socket/host_server_ip.c
    src/rats_tls_handler/rats_tls_handler.c
    src/integrity_check/integrity_check_handler.c)

add_executable(${PROJECT_NAME} ${SOURCES})

target_include_directories(${PROJECT_NAME} PRIVATE
    rats-tls/src/include
    inc/attest/
    inc/socket/
    inc/migcvm_tsi
    inc/rats_tls_handler
    inc/integrity_check
    inc
)

target_link_libraries(${PROJECT_NAME} PRIVATE 
    attest
    migcvm-tsi
)
