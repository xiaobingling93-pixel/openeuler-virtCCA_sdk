# src/migcvm_tsi/CMakeLists.txt

add_library(migcvm-tsi STATIC migcvm_tsi.c)

target_compile_options(migcvm-tsi PRIVATE -fPIE)

target_include_directories(migcvm-tsi PUBLIC
    ${PROJECT_SOURCE_DIR}/inc/migcvm_tsi
)