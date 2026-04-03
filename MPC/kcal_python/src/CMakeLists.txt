pybind11_add_module(kcal kcal_wrapper.cc context_ext.cc ${KCAL_MIDDLEWARE_SRCS})
target_include_directories(
  kcal PRIVATE $<BUILD_INTERFACE:${KCAL_MIDDLEWARE_ROOT}>
               $<INSTALL_INTERFACE:include>)
target_link_libraries(kcal PRIVATE ${KCAL_LIB_PATHS} pthread)
