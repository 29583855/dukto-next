cmake_minimum_required(VERSION 3.20)
project(UploadScanValidation LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)
find_package(Qt5 5.15 REQUIRED COMPONENTS Core Network Sql Test)
find_package(OpenSSL REQUIRED COMPONENTS Crypto)
add_library(candidate STATIC
    src/core/service.h
    src/core/uploadmanifest.cpp
    src/core/sourcefile.cpp
    src/core/privatestore.cpp
)
target_sources(candidate PRIVATE
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/error.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/diagnostics.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/files.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/nativecommit.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/protocol.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/securechannel.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/buffercredit.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/filecredit.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/sqlitecache.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/identity.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/auth.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/sessionpolicy.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/transferscheduler.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/transferoperation.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/service.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/shares.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/browse.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/strongmanifest.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/dispositionjournal.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/taskstore.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/expiredtaskcleanup.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/clientdownloadcleanup.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/directorycleanup.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/transferitems.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/durablereceive.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/receivetree.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/receiveskip.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/receiveskipfinal.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/transferdisposition.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/fileexchange.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/paralleltransfer.cpp.o
    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/transferservice.cpp.o
    src/core/transferclient.cpp
    src/core/transferprogress.cpp
    src/core/transferaccounting.cpp
    src/core/manifest.cpp
    src/core/legacy.cpp
    src/core/tcplistener.cpp
    src/core/discovery.cpp
    src/core/endpoint.cpp
    src/core/updates.cpp
    src/core/catalog.cpp
)
target_include_directories(candidate PUBLIC src)
target_link_libraries(candidate PUBLIC Qt5::Core Qt5::Network Qt5::Sql OpenSSL::Crypto)
target_compile_definitions(candidate PUBLIC DUKTO_VERSION="0.1.0")
add_executable(upload-scan-cleanup-tests tests/upload_scan_cleanup_tests.cpp)
target_link_libraries(upload-scan-cleanup-tests PRIVATE candidate Qt5::Test)
add_executable(dukto-cli src/cli/main.cpp src/cli/input.cpp src/cli/servicecommands.cpp)
target_link_libraries(dukto-cli PRIVATE candidate)
