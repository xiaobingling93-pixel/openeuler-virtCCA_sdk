file(GLOB_RECURSE COMMON_SRCS ${CMAKE_CURRENT_LIST_DIR}/*.cc)

add_library(kcal_middle ${COMMON_SRCS})
target_link_libraries(kcal_middle PUBLIC lib_kcal)

install(TARGETS kcal_middle
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib
)
