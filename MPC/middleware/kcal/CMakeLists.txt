file(GLOB_RECURSE COMMON_SRCS ${CMAKE_CURRENT_LIST_DIR}/*.cc)

add_library(kcal_middle ${COMMON_SRCS})
target_include_directories(
  kcal_middle PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/..>
                     $<INSTALL_INTERFACE:include>)
target_link_libraries(kcal_middle PUBLIC lib_kcal)

install(
  TARGETS kcal_middle
  EXPORT kcal_middlewareTargets
  LIBRARY DESTINATION lib
  ARCHIVE DESTINATION lib
  INCLUDES
  DESTINATION include)
