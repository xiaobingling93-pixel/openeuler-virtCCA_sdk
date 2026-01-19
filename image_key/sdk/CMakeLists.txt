cmake_minimum_required(VERSION 3.16)
project(virtcca-sdk
    LANGUAGES C)

set(CMAKE_INSTALL_PREFIX /usr/local)
set(targetname imagekey)

add_library(${targetname} SHARED)

target_sources(${targetname} PRIVATE src/image_key.c)

target_include_directories(${targetname} PUBLIC inc)

set_target_properties(${targetname} PROPERTIES PUBLIC_HEADER inc/image_key.h)

install(TARGETS ${targetname}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        PUBLIC_HEADER ${CMAKE_INSTALL_INCLUDEDIR}
)