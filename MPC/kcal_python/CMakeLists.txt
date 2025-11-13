cmake_minimum_required(VERSION 3.15...4.0)
project(kcal_python)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if (DEFINED ENV{CONDA_PREFIX})
    set(Python3_ROOT_DIR $ENV{CONDA_PREFIX})
endif ()

find_package(Python3 COMPONENTS Interpreter Development REQUIRED)
message(STATUS "Python3_EXECUTABLE: ${Python3_EXECUTABLE}")
message(STATUS "Python3_INCLUDE_DIRS: ${Python3_INCLUDE_DIRS}")
message(STATUS "Python3_LIBRARIES: ${Python3_LIBRARIES}")

# pybind11
set(PYBIND11_FINDPYTHON ON)
find_package(pybind11 CONFIG REQUIRED)

# kcal
set(KCAL_LIBS
        data_guard_common
        data_guard
        hitls_bsl
        hitls_crypto
        mpc_tee
        securec
)
set(LIB_SEARCH_DIR "${CMAKE_CURRENT_LIST_DIR}/lib")
set(KCAL_LIB_PATHS "")
foreach (lib_name IN LISTS KCAL_LIBS)
    find_library(found_path
            NAMES ${lib_name}
            PATHS ${LIB_SEARCH_DIR}
            NO_DEFAULT_PATH
    )
    if (NOT found_path)
        message(FATAL_ERROR "Cannot find ${lib_name} in ${LIB_SEARCH_DIR}")
    endif ()
    list(APPEND KCAL_LIB_PATHS ${found_path})
endforeach ()

# middleware
set(KCAL_MIDDLEWARE_ROOT ${CMAKE_CURRENT_LIST_DIR}/../middleware)
file(GLOB_RECURSE KCAL_MIDDLEWARE_SRCS ${CMAKE_CURRENT_LIST_DIR}/../middleware/kcal/**/*.cc)

include_directories(${CMAKE_CURRENT_LIST_DIR}/include)

add_subdirectory(src)
