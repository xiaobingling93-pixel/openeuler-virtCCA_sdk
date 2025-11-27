# src/migcvm_tsi/CMakeLists.txt
set(CMAKE_C_FLAGS "-fPIE ${CMAKE_C_FLAGS}")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fstack-protector-strong -D_FORTIFY_SOURCE=2 -Wall -Wextra")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -fPIE -Wl,-z,relro -Wl,-z,now -Wl,-z,noexecstack")
add_library(migcvm-tsi STATIC migcvm_tsi.c)

target_compile_options(migcvm-tsi PRIVATE -fPIE)

target_include_directories(migcvm-tsi PUBLIC
    ${PROJECT_SOURCE_DIR}/inc/migcvm_tsi
)