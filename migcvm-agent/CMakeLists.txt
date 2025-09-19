cmake_minimum_required(VERSION 3.5.1)
project(migcvm-agent)

set(CMAKE_C_FLAGS "-fPIE ${CMAKE_C_FLAGS}")

add_subdirectory(src/attest)

set(SOURCES src/migcvm-agent.c
    src/socket/host_socket_agent.c)

add_executable(${PROJECT_NAME} ${SOURCES})

target_include_directories(${PROJECT_NAME} PRIVATE
    rats-tls/src/include
    inc/attest/
    inc/socket/
)

target_link_libraries(${PROJECT_NAME} PRIVATE 
    attest
)

install(TARGETS ${PROJECT_NAME}
        DESTINATION ${RATS_TLS_INSTALL_BIN_PATH})
