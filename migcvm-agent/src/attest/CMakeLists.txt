set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fstack-protector-strong -D_FORTIFY_SOURCE=2")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -fPIE -Wl,-z,relro -Wl,-z,now -Wl,-z,noexecstack ")
add_library(attest STATIC
    token_parse.c 
    token_validate.c 
    platform_verify.c
    ima_measure.c
    event_log.c
    rem.c
    firmware_state.c
    binary_blob.c
    verify.c
    config.c
    utils.c
)

target_include_directories(attest PRIVATE
    ${CMAKE_SOURCE_DIR}/rats-tls/src/include
    ${CMAKE_SOURCE_DIR}/inc/attest/
    /usr/local/include/qcbor
    /usr/include
    /usr/local/lib
    /usr/include/openssl
    /usr/local/include/t_cose
)

find_package(OpenSSL REQUIRED)
find_library(RATS_TLS_LIB rats_tls PATHS /usr/lib/rats-tls/)
find_library(QCBOR_LIB qcbor)
find_library(T_COSE_LIB t_cose)

target_link_libraries(attest PRIVATE 
    m
    OpenSSL::Crypto
    ${T_COSE_LIB}
    ${QCBOR_LIB}
    ${RATS_TLS_LIB}
)
