project(PackageTest CXX)
cmake_minimum_required(VERSION 3.0)

include(${CMAKE_BINARY_DIR}/conanbuildinfo.cmake)
conan_basic_setup(TARGETS)

add_executable(example example.cpp)

target_link_libraries(example CONAN_PKG::Boost CONAN_PKG::Gearman)

