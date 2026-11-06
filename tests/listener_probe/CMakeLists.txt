cmake_minimum_required(VERSION 3.16)
project(DuktoListenerProbe LANGUAGES CXX)

if(NOT UNIX)
    message(FATAL_ERROR "This native socket diagnostic requires a POSIX host")
endif()

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
find_package(Qt5 5.15 REQUIRED COMPONENTS Core Network)

# 日期：2026-11-06；独立探针直接编译当前生产监听器，不修改主工程或原始测试。
add_executable(listener-probe main.cpp ../../src/core/tcplistener.cpp)
target_include_directories(listener-probe PRIVATE ../../src/core)
target_link_libraries(listener-probe PRIVATE Qt5::Core Qt5::Network)
