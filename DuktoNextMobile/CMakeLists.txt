cmake_minimum_required(VERSION 3.20)
# 日期：2026-11-09；在编译器初始化前固定Mac部署目标，避免继承构建机的macOS 15版本。
if(CMAKE_HOST_APPLE AND NOT CMAKE_SYSTEM_NAME STREQUAL "iOS" AND NOT DEFINED CMAKE_OSX_DEPLOYMENT_TARGET)
    set(CMAKE_OSX_DEPLOYMENT_TARGET "12.0" CACHE STRING "Minimum supported macOS version")
endif()
project(DuktoNextMobile VERSION 0.1.0 LANGUAGES C CXX)

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
set(DUKTO_SQLITE_VENDOR "${CMAKE_CURRENT_SOURCE_DIR}/shared/third-party/sqlite-runtime")
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
add_library(dukto-sqlite STATIC shared/src/core/sqliteplatform.c)
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
add_library(dukto-sql-driver STATIC shared/src/core/sqliteruntime.cpp shared/src/core/sqlitevfs.cpp
    "${DUKTO_SQLITE_VENDOR}/qt-5.15.2/qsql_sqlite.cpp"
    "${DUKTO_SQLITE_VENDOR}/qt-5.15.2/qsql_sqlite_p.h")
set_target_properties(dukto-sql-driver PROPERTIES POSITION_INDEPENDENT_CODE ON CXX_VISIBILITY_PRESET hidden)
target_include_directories(dukto-sql-driver PRIVATE shared/src "${DUKTO_SQLITE_VENDOR}/qt-5.15.2")
target_compile_definitions(dukto-sql-driver PRIVATE QT_PLUGIN QSQLiteDriver=DuktoSQLiteDriver
    QSQLiteDriverPrivate=DuktoSQLiteDriverPrivate QSQLiteResult=DuktoSQLiteResult
    QSQLiteResultPrivate=DuktoSQLiteResultPrivate)
target_link_libraries(dukto-sql-driver PUBLIC Qt5::Sql dukto-sqlite PRIVATE Qt5::SqlPrivate)

add_library(dukto-core STATIC
    shared/src/core/error.cpp
    shared/src/core/diagnostics.cpp
    shared/src/core/files.cpp
    shared/src/core/nativecommit.cpp
    shared/src/core/sourcefile.cpp
    shared/src/core/protocol.cpp
    shared/src/core/securechannel.cpp
    shared/src/core/buffercredit.cpp
    shared/src/core/filecredit.cpp
    shared/src/core/sqlitecache.cpp
    shared/src/core/privatestore.cpp
    shared/src/core/stateinventory.cpp
    shared/src/core/statebudget.cpp
    shared/src/core/statedomain.cpp
    shared/src/core/stateaccounting.cpp
    shared/src/core/historybudget.cpp
    shared/src/core/statesession.cpp
    shared/src/core/statecleanup.cpp
    shared/src/core/identity.cpp
    shared/src/core/auth.cpp
    shared/src/core/sessionpolicy.cpp
    shared/src/core/transferscheduler.cpp
    shared/src/core/transferoperation.cpp
    shared/src/core/service.cpp
    shared/src/core/shares.cpp
    shared/src/core/browse.cpp
    shared/src/core/strongmanifest.cpp
    shared/src/core/uploadmanifest.cpp
    shared/src/core/dispositionjournal.cpp
    shared/src/core/taskstore.cpp
    shared/src/core/expiredtaskcleanup.cpp
    shared/src/core/clientdownloadcleanup.cpp
    shared/src/core/directorycleanup.cpp
    shared/src/core/transferitems.cpp
    shared/src/core/durablereceive.cpp
    shared/src/core/receivetree.cpp
    shared/src/core/receiveskip.cpp
    shared/src/core/receiveskipfinal.cpp
    shared/src/core/transferdisposition.cpp
    shared/src/core/fileexchange.cpp
    shared/src/core/paralleltransfer.cpp
    shared/src/core/transferservice.cpp
    shared/src/core/transferclient.cpp
    shared/src/core/transferprogress.cpp
    shared/src/core/transferaccounting.cpp
    shared/src/core/manifest.cpp
    shared/src/core/legacy.cpp
    shared/src/core/tcplistener.cpp
    shared/src/core/discovery.cpp
    shared/src/core/endpoint.cpp
    shared/src/core/updates.cpp
    shared/src/core/catalog.cpp
    shared/src/core/historystate.cpp
)
target_include_directories(dukto-core PUBLIC shared/src)
target_link_libraries(dukto-core PUBLIC Qt5::Core Qt5::Network Qt5::Sql)
target_link_libraries(dukto-core PUBLIC dukto-sql-driver PRIVATE OpenSSL::Crypto)
if(WIN32)
    target_link_libraries(dukto-core PRIVATE advapi32 ws2_32 iphlpapi)
endif()
target_compile_definitions(dukto-core PUBLIC DUKTO_VERSION="${PROJECT_VERSION}")


set_target_properties(dukto-core PROPERTIES POSITION_INDEPENDENT_CODE ON)

# 日期：2026-11-25；主机门禁编译完整移动控制器并实际加载QML，不替代手机设备验收。
option(DUKTO_MOBILE_HOST_CHECK "Compile mobile UI using host-only provider stubs" OFF)
if(DUKTO_MOBILE_HOST_CHECK)
    find_package(Qt5 5.15 REQUIRED COMPONENTS Gui Qml Quick QuickControls2 QuickTemplates2)
    add_executable(dukto-mobile-host app/mobilelifecycle.cpp app/mobilelifecycle.h app/main.cpp app/mobilefiles.cpp app/importstore.cpp app/importregistry.cpp
        tests/platformfiles_stub.cpp shared/src/app/controller.cpp shared/src/app/controller.h
        shared/src/app/serverpanel.cpp shared/src/app/serverpanel.h
        shared/src/app/avatars.cpp shared/src/app/avatars.h
        shared/src/app/stablescrollbar.cpp shared/src/app/stablescrollbar.h
        app/mobilefiles.h app/mobile.qrc shared/resources/app.qrc)
    target_include_directories(dukto-mobile-host PRIVATE app shared/src/app)
    target_link_libraries(dukto-mobile-host PRIVATE dukto-core Qt5::Gui Qt5::Qml Qt5::Quick
        Qt5::QuickControls2 Qt5::QuickTemplates2 Qt5::QuickPrivate Qt5::QuickTemplates2Private)
endif()

# 日期：2026-11-25；测试专用命令行探针与同一移动核心链接，验证真实多进程网络与磁盘结果。
if(DUKTO_MOBILE_HOST_CHECK)
    add_executable(dukto-mobile-probe tools/main.cpp tools/input.cpp
        tools/servicecommands.cpp tools/statecommands.cpp)
    target_link_libraries(dukto-mobile-probe PRIVATE dukto-core)
endif()
