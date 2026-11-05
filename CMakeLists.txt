cmake_minimum_required(VERSION 3.20)
project(DuktoNext VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_INCLUDE_CURRENT_DIR ON)

option(DUKTO_BUILD_GUI "Build desktop application" ON)
option(DUKTO_BUILD_TESTS "Build validation tests" ON)
find_package(Qt5 5.15 REQUIRED COMPONENTS Core Network Sql)
# 日期：2026-11-04；服务身份由同平台的原生 OpenSSL Crypto 生成，不调用外部 shell 或携带私钥参数。
if(WIN32 AND NOT DEFINED OPENSSL_ROOT_DIR AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/.tools/openssl/Library")
    set(OPENSSL_ROOT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/.tools/openssl/Library")
endif()
find_package(OpenSSL 1.1.1 REQUIRED COMPONENTS Crypto)
if(MSVC)
    add_compile_options(/utf-8 /W4 /permissive-)
else()
    add_compile_options(-Wall -Wextra -Wpedantic)
endif()

add_library(dukto-core
    src/core/error.cpp
    src/core/files.cpp
    src/core/nativecommit.cpp
    src/core/sourcefile.cpp
    src/core/protocol.cpp
    src/core/securechannel.cpp
    src/core/buffercredit.cpp
    src/core/sqlitecache.cpp
    src/core/privatestore.cpp
    src/core/identity.cpp
    src/core/auth.cpp
    src/core/sessionpolicy.cpp
    src/core/transferscheduler.cpp
    src/core/transferoperation.cpp
    src/core/service.cpp
    src/core/shares.cpp
    src/core/browse.cpp
    src/core/strongmanifest.cpp
    src/core/taskstore.cpp
    src/core/durablereceive.cpp
    src/core/receivetree.cpp
    src/core/fileexchange.cpp
    src/core/paralleltransfer.cpp
    src/core/transferservice.cpp
    src/core/transferclient.cpp
    src/core/transferprogress.cpp
    src/core/manifest.cpp
    src/core/legacy.cpp
    src/core/discovery.cpp
    src/core/endpoint.cpp
    src/core/updates.cpp
    src/core/catalog.cpp
)
target_include_directories(dukto-core PUBLIC src)
target_link_libraries(dukto-core PUBLIC Qt5::Core Qt5::Network Qt5::Sql)
target_link_libraries(dukto-core PRIVATE OpenSSL::Crypto)
if(WIN32)
    target_link_libraries(dukto-core PRIVATE advapi32)
endif()
target_compile_definitions(dukto-core PUBLIC DUKTO_VERSION="${PROJECT_VERSION}")

add_executable(dukto-cli src/cli/main.cpp src/cli/input.cpp src/cli/servicecommands.cpp)
target_link_libraries(dukto-cli PRIVATE dukto-core)
install(TARGETS dukto-cli RUNTIME DESTINATION bin)

if(DUKTO_BUILD_GUI)
    find_package(Qt5 5.15 REQUIRED COMPONENTS Widgets Quick Qml QuickWidgets)
    add_executable(dukto-gui WIN32 MACOSX_BUNDLE src/app/main.cpp src/app/controller.cpp src/app/avatars.cpp src/app/serverpanel.cpp resources/app.qrc)
    target_link_libraries(dukto-gui PRIVATE dukto-core Qt5::Widgets Qt5::QuickWidgets Qt5::Quick Qt5::Qml)
    set_target_properties(dukto-gui PROPERTIES MACOSX_BUNDLE_BUNDLE_NAME "Dukto Next"
        MACOSX_BUNDLE_GUI_IDENTIFIER "org.duktonext.desktop")
    install(TARGETS dukto-gui BUNDLE DESTINATION . RUNTIME DESTINATION bin)
endif()

if(DUKTO_BUILD_TESTS)
    enable_testing()
    find_package(Qt5 5.15 REQUIRED COMPONENTS Test)
    # 日期：2026-11-04；Windows 的 QtTest 不保证标准输出可见，显式保存文本及 UTF-8 XML 诊断。
    file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/Testing/QtTest")
    function(dukto_add_qt_test name)
        add_test(NAME ${name} COMMAND ${name}
            -o "${CMAKE_BINARY_DIR}/Testing/QtTest/${name}.log,txt"
            -o "${CMAKE_BINARY_DIR}/Testing/QtTest/${name}.xml,junitxml")
    endfunction()
    add_executable(core-tests tests/core_tests.cpp)
    target_link_libraries(core-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(core-tests)
    add_executable(protocol-tests tests/protocol_tests.cpp)
    target_link_libraries(protocol-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(protocol-tests)
    add_executable(buffer-credit-tests tests/buffer_credit_tests.cpp)
    target_link_libraries(buffer-credit-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(buffer-credit-tests)
    add_executable(sqlite-cache-tests tests/sqlite_cache_tests.cpp)
    target_link_libraries(sqlite-cache-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(sqlite-cache-tests)
    add_executable(identity-tests tests/identity_tests.cpp)
    target_link_libraries(identity-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(identity-tests)
    add_executable(browse-tests tests/browse_tests.cpp)
    target_link_libraries(browse-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(browse-tests)
    add_executable(strong-manifest-tests tests/strong_manifest_tests.cpp)
    target_link_libraries(strong-manifest-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(strong-manifest-tests)
    add_executable(task-store-tests tests/task_store_tests.cpp)
    target_link_libraries(task-store-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(task-store-tests)
    add_executable(transfer-operation-tests tests/transfer_operation_tests.cpp)
    target_link_libraries(transfer-operation-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(transfer-operation-tests)
    add_executable(transfer-scheduler-tests tests/transfer_scheduler_tests.cpp)
    target_link_libraries(transfer-scheduler-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(transfer-scheduler-tests)
    add_executable(durable-receive-tests tests/durable_receive_tests.cpp)
    target_link_libraries(durable-receive-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(durable-receive-tests)
    add_executable(file-exchange-tests tests/file_exchange_tests.cpp)
    target_link_libraries(file-exchange-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(file-exchange-tests)
    add_executable(task-store-probe tests/task_store_probe.cpp)
    target_link_libraries(task-store-probe PRIVATE dukto-core)
    add_executable(runtime-probe tests/runtime_probe.cpp)
    target_link_libraries(runtime-probe PRIVATE dukto-core)
    add_test(NAME runtime-probe COMMAND runtime-probe)
    add_executable(tls-probe tests/tls_probe.cpp)
    target_link_libraries(tls-probe PRIVATE dukto-core)
    add_executable(secure-channel-probe tests/secure_channel_probe.cpp)
    target_link_libraries(secure-channel-probe PRIVATE dukto-core)
    add_executable(updates-tests tests/updates_tests.cpp)
    target_link_libraries(updates-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(updates-tests)
    if(DUKTO_BUILD_GUI)
        add_executable(controller-tests tests/controller_tests.cpp src/app/controller.cpp src/app/avatars.cpp src/app/serverpanel.cpp)
        target_link_libraries(controller-tests PRIVATE dukto-core Qt5::Widgets Qt5::Test)
        dukto_add_qt_test(controller-tests)
        set_tests_properties(controller-tests PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
        add_executable(avatars-tests tests/avatars_tests.cpp src/app/avatars.cpp)
        target_include_directories(avatars-tests PRIVATE src)
        target_link_libraries(avatars-tests PRIVATE Qt5::Gui Qt5::Network Qt5::Test)
        dukto_add_qt_test(avatars-tests)
        add_executable(ui-tests tests/ui_tests.cpp src/app/controller.cpp src/app/avatars.cpp src/app/serverpanel.cpp resources/app.qrc)
        target_link_libraries(ui-tests PRIVATE dukto-core Qt5::QuickWidgets Qt5::Quick Qt5::Qml Qt5::Widgets Qt5::Test)
        dukto_add_qt_test(ui-tests)
        set_tests_properties(ui-tests PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
        add_executable(server-panel-tests tests/server_panel_tests.cpp src/app/serverpanel.cpp resources/app.qrc)
        target_link_libraries(server-panel-tests PRIVATE dukto-core Qt5::QuickWidgets Qt5::Quick Qt5::Qml Qt5::Widgets Qt5::Test)
        dukto_add_qt_test(server-panel-tests)
        set_tests_properties(server-panel-tests PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
        add_executable(server-panel-process-probe tests/server_panel_process_probe.cpp src/app/serverpanel.cpp resources/app.qrc)
        target_link_libraries(server-panel-process-probe PRIVATE dukto-core Qt5::QuickWidgets Qt5::Quick Qt5::Qml Qt5::Widgets Qt5::Test)
    endif()
endif()
