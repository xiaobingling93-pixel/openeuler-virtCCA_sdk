cmake_minimum_required(VERSION 3.16)

project(kcal_middleware LANGUAGES C CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(libkcal REQUIRED)

add_subdirectory(kcal)

install(
  DIRECTORY kcal
  DESTINATION include
  FILES_MATCHING
  PATTERN "*.h")

install(
  EXPORT kcal_middlewareTargets
  FILE kcal_middleConfig.cmake
  DESTINATION lib/cmake/kcal_middle)
