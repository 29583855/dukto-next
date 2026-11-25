cmake_minimum_required(VERSION 3.20)
project(DuktoMobileStorageTests LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
find_package(Qt5 5.15 REQUIRED COMPONENTS Core Test)
enable_testing()
add_executable(mobile-storage-tests importstore_tests.cpp ../app/importstore.cpp)
target_include_directories(mobile-storage-tests PRIVATE ../app)
target_link_libraries(mobile-storage-tests PRIVATE Qt5::Core Qt5::Test)
add_test(NAME mobile-storage COMMAND mobile-storage-tests)

# 日期：2026-11-25；沙箱分页与路径隔离使用真实协调器，原生提供器只使用明确失败的替身。
add_executable(mobile-files-tests mobilefiles_tests.cpp ../shared/src/core/error.cpp ../app/mobilefiles.cpp ../app/importregistry.cpp platformfiles_stub.cpp)
target_include_directories(mobile-files-tests PRIVATE ../app ../shared/src)
target_link_libraries(mobile-files-tests PRIVATE Qt5::Core Qt5::Test)
add_test(NAME mobile-files COMMAND mobile-files-tests)

# 日期：2026-11-25；重启恢复、目标绑定、引用损坏和清理边界直接检验磁盘结果。
add_executable(mobile-import-registry-tests importregistry_tests.cpp ../app/importregistry.cpp)
target_include_directories(mobile-import-registry-tests PRIVATE ../app)
target_link_libraries(mobile-import-registry-tests PRIVATE Qt5::Core Qt5::Test)
add_test(NAME mobile-import-registry COMMAND mobile-import-registry-tests)
