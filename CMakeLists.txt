cmake_minimum_required(VERSION 3.20)
# 日期：2026-11-09；在编译器初始化前固定Mac部署目标，避免继承构建机的macOS 15版本。
if(CMAKE_HOST_APPLE AND NOT DEFINED CMAKE_OSX_DEPLOYMENT_TARGET)
    set(CMAKE_OSX_DEPLOYMENT_TARGET "12.0" CACHE STRING "Minimum supported macOS version")
endif()
project(DuktoNext VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_INCLUDE_CURRENT_DIR ON)

# 日期：2026-11-09；新SDK的高版本API必须显式做可用性保护，不能悄悄破坏部署基线。
if(APPLE)
    add_compile_options(-Werror=unguarded-availability-new)
endif()

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

# 日期：2026-11-07；固定上游原件并离线解压，外部C/Qt源保持原编码和格式。
set(DUKTO_SQLITE_VENDOR "${CMAKE_CURRENT_SOURCE_DIR}/third-party/sqlite-runtime")
file(SHA256 "${DUKTO_SQLITE_VENDOR}/sqlite-amalgamation-3530400.zip" DUKTO_SQLITE_SHA256)
if(NOT DUKTO_SQLITE_SHA256 STREQUAL "1e71ddf93849c6a6ecf58b827c0692073d2dd7ee40196158068f7b29f422e87d")
    message(FATAL_ERROR "SQLite upstream archive digest mismatch")
endif()
file(SHA256 "${DUKTO_SQLITE_VENDOR}/qt-5.15.2/qsql_sqlite.cpp" DUKTO_QSQL_SOURCE_SHA256)
file(SHA256 "${DUKTO_SQLITE_VENDOR}/qt-5.15.2/qsql_sqlite_p.h" DUKTO_QSQL_HEADER_SHA256)
if(NOT DUKTO_QSQL_SOURCE_SHA256 STREQUAL "fb7073dd4a5d715aff57cb8bc5efb946b5ebec2667fd780c42b2d986c013c562"
   OR NOT DUKTO_QSQL_HEADER_SHA256 STREQUAL "8c2925c9691cc2022501e2bf5abf290697f073f2a2e29af8dea5bede0f2f0215")
    message(FATAL_ERROR "Qt SQLite driver upstream source digest mismatch")
endif()
if(NOT TARGET Qt5::SqlPrivate)
    message(FATAL_ERROR "Qt5 Sql private development headers are required; install qtbase5-private-dev on Debian/Ubuntu")
endif()
set(DUKTO_SQLITE_EXTRACTED "${CMAKE_BINARY_DIR}/sqlite-runtime-source")
if(NOT EXISTS "${DUKTO_SQLITE_EXTRACTED}/sqlite-amalgamation-3530400/sqlite3.c")
    file(ARCHIVE_EXTRACT INPUT "${DUKTO_SQLITE_VENDOR}/sqlite-amalgamation-3530400.zip"
        DESTINATION "${DUKTO_SQLITE_EXTRACTED}")
endif()
# 日期：2026-11-07；提取内容同样逐件固定，构建目录残留或篡改不能绕过原归档摘要。
file(SHA256 "${DUKTO_SQLITE_EXTRACTED}/sqlite-amalgamation-3530400/sqlite3.c" DUKTO_SQLITE_MEMBER_SHA256)
if(NOT DUKTO_SQLITE_MEMBER_SHA256 STREQUAL "b1dd5d74ec7f29055a6684fa06fb3c2f6821c87dd38f9a458dfd2e8a1db28189")
    message(FATAL_ERROR "SQLite extracted source digest mismatch: sqlite3.c")
endif()
file(SHA256 "${DUKTO_SQLITE_EXTRACTED}/sqlite-amalgamation-3530400/sqlite3.h" DUKTO_SQLITE_MEMBER_SHA256)
if(NOT DUKTO_SQLITE_MEMBER_SHA256 STREQUAL "919e7f2e8ed1d8f56ac17b412b8971c76aa5d1a879752cc6058f75e7d5910e1d")
    message(FATAL_ERROR "SQLite extracted source digest mismatch: sqlite3.h")
endif()
file(SHA256 "${DUKTO_SQLITE_EXTRACTED}/sqlite-amalgamation-3530400/sqlite3ext.h" DUKTO_SQLITE_MEMBER_SHA256)
if(NOT DUKTO_SQLITE_MEMBER_SHA256 STREQUAL "ac9645e5c9ff0cf176efdd6e75cb5e98f46295d38e02db5c4d208826a39ab4be")
    message(FATAL_ERROR "SQLite extracted source digest mismatch: sqlite3ext.h")
endif()
# 日期：2026-11-08；适配与原SQLite同单元编译，原提取文件不改字节，原生类型由编译器直接核验。
add_library(dukto-sqlite STATIC src/core/sqliteplatform.c)
set_target_properties(dukto-sqlite PROPERTIES AUTOMOC OFF C_STANDARD 99 C_STANDARD_REQUIRED ON
    POSITION_INDEPENDENT_CODE ON C_VISIBILITY_PRESET hidden)
target_include_directories(dukto-sqlite PUBLIC "${DUKTO_SQLITE_EXTRACTED}/sqlite-amalgamation-3530400")
find_package(Threads REQUIRED)
target_link_libraries(dukto-sqlite PUBLIC Threads::Threads)
if(UNIX)
    target_link_libraries(dukto-sqlite PUBLIC m)
endif()
target_compile_definitions(dukto-sqlite PRIVATE SQLITE_THREADSAFE=1 SQLITE_ENABLE_COLUMN_METADATA
    SQLITE_ENABLE_FTS3 SQLITE_ENABLE_FTS3_PARENTHESIS SQLITE_ENABLE_FTS4 SQLITE_ENABLE_FTS5
    SQLITE_ENABLE_RTREE SQLITE_ENABLE_UNLOCK_NOTIFY SQLITE_SECURE_DELETE SQLITE_OMIT_LOAD_EXTENSION)
if(MSVC)
    target_compile_options(dukto-sqlite PRIVATE /w)
else()
    target_compile_options(dukto-sqlite PRIVATE -w)
    target_link_libraries(dukto-sqlite PUBLIC ${CMAKE_DL_LIBS})
endif()
# 日期：2026-11-07；原Qt完整驱动仅更换内部类名，与平台QSQLITE插件互不覆盖。
add_library(dukto-sql-driver STATIC src/core/sqliteruntime.cpp src/core/sqlitevfs.cpp
    "${DUKTO_SQLITE_VENDOR}/qt-5.15.2/qsql_sqlite.cpp"
    "${DUKTO_SQLITE_VENDOR}/qt-5.15.2/qsql_sqlite_p.h")
set_target_properties(dukto-sql-driver PROPERTIES POSITION_INDEPENDENT_CODE ON CXX_VISIBILITY_PRESET hidden)
target_include_directories(dukto-sql-driver PRIVATE src "${DUKTO_SQLITE_VENDOR}/qt-5.15.2")
target_compile_definitions(dukto-sql-driver PRIVATE QT_PLUGIN QSQLiteDriver=DuktoSQLiteDriver
    QSQLiteDriverPrivate=DuktoSQLiteDriverPrivate QSQLiteResult=DuktoSQLiteResult
    QSQLiteResultPrivate=DuktoSQLiteResultPrivate)
target_link_libraries(dukto-sql-driver PUBLIC Qt5::Sql dukto-sqlite PRIVATE Qt5::SqlPrivate)

add_library(dukto-core
    src/core/error.cpp
    src/core/diagnostics.cpp
    src/core/files.cpp
    src/core/nativecommit.cpp
    src/core/sourcefile.cpp
    src/core/protocol.cpp
    src/core/securechannel.cpp
    src/core/buffercredit.cpp
    src/core/filecredit.cpp
    src/core/sqlitecache.cpp
    src/core/privatestore.cpp
    src/core/stateinventory.cpp
    src/core/statebudget.cpp
    src/core/statedomain.cpp
    src/core/stateaccounting.cpp
    src/core/historybudget.cpp
    src/core/statesession.cpp
    src/core/statecleanup.cpp
    src/core/identity.cpp
    src/core/auth.cpp
    src/core/sessionpolicy.cpp
    src/core/transferscheduler.cpp
    src/core/transferoperation.cpp
    src/core/service.cpp
    src/core/shares.cpp
    src/core/browse.cpp
    src/core/strongmanifest.cpp
    src/core/uploadmanifest.cpp
    src/core/dispositionjournal.cpp
    src/core/taskstore.cpp
    src/core/expiredtaskcleanup.cpp
    src/core/clientdownloadcleanup.cpp
    src/core/directorycleanup.cpp
    src/core/transferitems.cpp
    src/core/durablereceive.cpp
    src/core/receivetree.cpp
    src/core/receiveskip.cpp
    src/core/receiveskipfinal.cpp
    src/core/transferdisposition.cpp
    src/core/fileexchange.cpp
    src/core/paralleltransfer.cpp
    src/core/transferservice.cpp
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
    src/core/historystate.cpp
)
target_include_directories(dukto-core PUBLIC src)
target_link_libraries(dukto-core PUBLIC Qt5::Core Qt5::Network Qt5::Sql)
target_link_libraries(dukto-core PUBLIC dukto-sql-driver PRIVATE OpenSSL::Crypto)
if(WIN32)
    target_link_libraries(dukto-core PRIVATE advapi32 ws2_32 iphlpapi)
endif()
target_compile_definitions(dukto-core PUBLIC DUKTO_VERSION="${PROJECT_VERSION}")

add_executable(dukto-cli src/cli/main.cpp src/cli/input.cpp src/cli/servicecommands.cpp src/cli/statecommands.cpp)
target_link_libraries(dukto-cli PRIVATE dukto-core)
install(TARGETS dukto-cli RUNTIME DESTINATION bin)

if(DUKTO_BUILD_GUI)
    find_package(Qt5 5.15 REQUIRED COMPONENTS Widgets Quick Qml QuickWidgets)
    add_executable(dukto-gui WIN32 MACOSX_BUNDLE src/app/main.cpp src/app/controller.cpp src/app/avatars.cpp src/app/serverpanel.cpp src/app/boundedfiledialog.cpp resources/app.qrc)
    target_link_libraries(dukto-gui PRIVATE dukto-core Qt5::Widgets Qt5::QuickWidgets Qt5::Quick Qt5::Qml)
    set_target_properties(dukto-gui PROPERTIES MACOSX_BUNDLE_BUNDLE_NAME "Dukto Next"
        MACOSX_BUNDLE_GUI_IDENTIFIER "org.duktonext.desktop")
    if(APPLE)
        set_target_properties(dukto-gui PROPERTIES
            MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/resources/macos/Info.plist.in")
    endif()
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
    add_executable(upload-scan-cleanup-tests tests/upload_scan_cleanup_tests.cpp)
    target_link_libraries(upload-scan-cleanup-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(upload-scan-cleanup-tests)
    add_executable(state-storage-tests tests/state_storage_tests.cpp)
    target_link_libraries(state-storage-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(state-storage-tests)
    # 日期：2026-11-05；单独诊断系统主机名查询成本，不注册为放宽 UDP 门槛的替代测试。
    add_executable(discovery-signature-probe tests/discovery_signature_probe.cpp)
    target_link_libraries(discovery-signature-probe PRIVATE Qt5::Core Qt5::Network)
    add_executable(discovery-identity-tests tests/discovery_identity_tests.cpp)
    target_link_libraries(discovery-identity-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(discovery-identity-tests)
    add_executable(protocol-tests tests/protocol_tests.cpp)
    target_link_libraries(protocol-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(protocol-tests)
    add_executable(buffer-credit-tests tests/buffer_credit_tests.cpp)
    target_link_libraries(buffer-credit-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(buffer-credit-tests)
    add_executable(sqlite-cache-tests tests/sqlite_cache_tests.cpp)
    target_link_libraries(sqlite-cache-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(sqlite-cache-tests)
    add_executable(sqlite-vfs-tests tests/sqlite_vfs_tests.cpp)
    target_link_libraries(sqlite-vfs-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(sqlite-vfs-tests)
    add_executable(sqlite-file-info-tests tests/sqlite_file_info_tests.cpp)
    target_link_libraries(sqlite-file-info-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(sqlite-file-info-tests)
    add_executable(state-budget-tests tests/state_budget_tests.cpp)
    target_link_libraries(state-budget-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(state-budget-tests)
    add_executable(state-domain-tests tests/state_domain_tests.cpp)
    target_link_libraries(state-domain-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(state-domain-tests)
    add_executable(budget-configuration-tests tests/budget_configuration_tests.cpp)
    target_link_libraries(budget-configuration-tests PRIVATE dukto-core Qt5::Test)
    add_dependencies(budget-configuration-tests dukto-cli)
    dukto_add_qt_test(budget-configuration-tests)
    add_executable(state-session-tests tests/state_session_tests.cpp)
    target_link_libraries(state-session-tests PRIVATE dukto-core Qt5::Test)
    add_dependencies(state-session-tests dukto-cli)
    dukto_add_qt_test(state-session-tests)
    add_executable(state-accounting-tests tests/state_accounting_tests.cpp)
    target_link_libraries(state-accounting-tests PRIVATE dukto-core Qt5::Test)
    add_dependencies(state-accounting-tests dukto-cli)
    dukto_add_qt_test(state-accounting-tests)
    add_executable(identity-tests tests/identity_tests.cpp)
    target_link_libraries(identity-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(identity-tests)
    add_executable(browse-tests tests/browse_tests.cpp)
    target_link_libraries(browse-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(browse-tests)
    add_executable(strong-manifest-tests tests/strong_manifest_tests.cpp)
    target_link_libraries(strong-manifest-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(strong-manifest-tests)
    add_executable(disposition-journal-tests tests/disposition_journal_tests.cpp)
    target_link_libraries(disposition-journal-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(disposition-journal-tests)
    add_executable(transfer-accounting-tests tests/transfer_accounting_tests.cpp)
    target_link_libraries(transfer-accounting-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(transfer-accounting-tests)
    add_executable(task-store-tests tests/task_store_tests.cpp)
    target_link_libraries(task-store-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(task-store-tests)
    add_executable(expired-task-cleanup-tests tests/expired_task_cleanup_tests.cpp)
    target_link_libraries(expired-task-cleanup-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(expired-task-cleanup-tests)
    add_executable(client-download-cleanup-tests tests/client_download_cleanup_tests.cpp)
    target_link_libraries(client-download-cleanup-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(client-download-cleanup-tests)
    add_executable(directory-cleanup-tests tests/directory_cleanup_tests.cpp)
    target_link_libraries(directory-cleanup-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(directory-cleanup-tests)
    add_executable(transfer-items-tests tests/transfer_items_tests.cpp)
    target_link_libraries(transfer-items-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(transfer-items-tests)
    add_executable(transfer-operation-tests tests/transfer_operation_tests.cpp)
    target_link_libraries(transfer-operation-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(transfer-operation-tests)
    add_executable(transfer-scheduler-tests tests/transfer_scheduler_tests.cpp)
    target_link_libraries(transfer-scheduler-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(transfer-scheduler-tests)
    add_executable(durable-receive-tests tests/durable_receive_tests.cpp)
    target_link_libraries(durable-receive-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(durable-receive-tests)
    add_executable(receive-skip-tests tests/receive_skip_tests.cpp)
    target_link_libraries(receive-skip-tests PRIVATE dukto-core Qt5::Test)
    dukto_add_qt_test(receive-skip-tests)
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
        add_executable(controller-tests tests/controller_tests.cpp src/app/controller.cpp src/app/avatars.cpp src/app/serverpanel.cpp src/app/boundedfiledialog.cpp)
        target_link_libraries(controller-tests PRIVATE dukto-core Qt5::Widgets Qt5::Test)
        dukto_add_qt_test(controller-tests)
        set_tests_properties(controller-tests PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
        add_executable(avatars-tests tests/avatars_tests.cpp src/app/avatars.cpp)
        target_include_directories(avatars-tests PRIVATE src)
        target_link_libraries(avatars-tests PRIVATE dukto-core Qt5::Gui Qt5::Network Qt5::Test)
        dukto_add_qt_test(avatars-tests)
        add_executable(ui-tests tests/ui_tests.cpp src/app/controller.cpp src/app/avatars.cpp src/app/serverpanel.cpp src/app/boundedfiledialog.cpp resources/app.qrc)
        target_link_libraries(ui-tests PRIVATE dukto-core Qt5::QuickWidgets Qt5::Quick Qt5::Qml Qt5::Widgets Qt5::Test)
        dukto_add_qt_test(ui-tests)
        set_tests_properties(ui-tests PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
        add_executable(server-panel-tests tests/server_panel_tests.cpp src/app/serverpanel.cpp src/app/boundedfiledialog.cpp resources/app.qrc)
        target_link_libraries(server-panel-tests PRIVATE dukto-core Qt5::QuickWidgets Qt5::Quick Qt5::Qml Qt5::Widgets Qt5::Test)
        add_dependencies(server-panel-tests dukto-cli)
        dukto_add_qt_test(server-panel-tests)
        set_tests_properties(server-panel-tests PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
        add_executable(server-panel-process-probe tests/server_panel_process_probe.cpp src/app/serverpanel.cpp src/app/boundedfiledialog.cpp resources/app.qrc)
        target_link_libraries(server-panel-process-probe PRIVATE dukto-core Qt5::QuickWidgets Qt5::Quick Qt5::Qml Qt5::Widgets Qt5::Test)
    endif()
endif()
