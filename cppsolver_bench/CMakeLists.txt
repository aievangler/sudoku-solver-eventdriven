cmake_minimum_required(VERSION 3.20)
project(cppsolver LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Apple Silicon friendly flags
if(CMAKE_BUILD_TYPE STREQUAL "Release")
    add_compile_options(-O3 -march=native -flto)
else()
    add_compile_options(-O0 -g)
endif()

# Sanitizers for Debug builds (optional)
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
    if (APPLE)
        add_link_options(-fsanitize=address,undefined)
        add_compile_options(-fsanitize=address,undefined)
    endif()
endif()

add_library(cppsolver_lib
    src/geometry.cpp
    src/state.cpp
    src/trail.cpp
    src/propagation.cpp
    src/scoring.cpp
    src/dfs.cpp
    src/solver.cpp
)

target_include_directories(cppsolver_lib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

add_executable(cppsolver src/main.cpp)
target_link_libraries(cppsolver PRIVATE cppsolver_lib)
