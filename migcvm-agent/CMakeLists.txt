cmake_minimum_required(VERSION 3.5.1)
project(migcvm-agent)

set(CMAKE_C_FLAGS "-fPIE ${CMAKE_C_FLAGS}")

add_subdirectory(src/attest)
add_subdirectory(src/migcvm_tsi)

set(SOURCES src/migcvm-agent.c
    src/socket/host_socket_agent.c)

add_executable(${PROJECT_NAME} ${SOURCES})

target_include_directories(${PROJECT_NAME} PRIVATE
    rats-tls/src/include
    inc/attest/
    inc/socket/
    inc/migcvm_tsi
)

target_link_libraries(${PROJECT_NAME} PRIVATE 
    attest
    migcvm-tsi
)

add_executable(tsi-controller
    debug/tsi-controller.c)

target_include_directories(tsi-controller PRIVATE
    inc/migcvm_tsi
    rats-tls/src/include)

target_link_libraries(tsi-controller PRIVATE migcvm-tsi)


add_executable(socket-tool
    debug/socket-tool.c)

target_include_directories(socket-tool PRIVATE
    inc/socket
    rats-tls/src/include)

target_link_libraries(socket-tool PRIVATE)

install(TARGETS ${PROJECT_NAME} tsi-controller socket-tool
        DESTINATION ${RATS_TLS_INSTALL_BIN_PATH})
