# 日期：2026-11-25；qmake负责移动平台插件和部署，核心使用CMake独立构建。
TEMPLATE = app
TARGET = DuktoNextMobile
CONFIG += c++14
QT += core gui network sql qml quick quickcontrols2 quick-private quicktemplates2-private
SOURCES += $$PWD/app/popupcontextguard.cpp $$PWD/app/mobilelifecycle.cpp $$PWD/app/main.cpp $$PWD/app/mobilefiles.cpp $$PWD/app/importstore.cpp $$PWD/app/importregistry.cpp \
    $$PWD/shared/src/app/controller.cpp $$PWD/shared/src/app/serverpanel.cpp \
    $$PWD/shared/src/app/avatars.cpp $$PWD/shared/src/app/stablescrollbar.cpp
HEADERS += $$PWD/app/popupcontextguard.h $$PWD/app/mobilelifecycle.h $$PWD/app/mobilefiles.h $$PWD/app/importstore.h $$PWD/app/importregistry.h $$PWD/app/platformfiles.h \
    $$PWD/shared/src/app/controller.h $$PWD/shared/src/app/serverpanel.h \
    $$PWD/shared/src/app/avatars.h $$PWD/shared/src/app/stablescrollbar.h
RESOURCES += $$PWD/app/mobile.qrc $$PWD/shared/resources/app.qrc
INCLUDEPATH += $$PWD/app $$PWD/shared/src/app $$PWD/shared/src $$OPENSSL_PREFIX/include
isEmpty(CORE_BUILD): error("Pass CORE_BUILD=/absolute/core-build")
isEmpty(OPENSSL_PREFIX): error("Pass OPENSSL_PREFIX=/absolute/openssl")
LIBS += -L$$CORE_BUILD -ldukto-core -ldukto-sql-driver -ldukto-sqlite
LIBS += -L$$OPENSSL_PREFIX/lib -lssl -lcrypto
# 日期：2026-11-25；Android线程符号由Bionic提供，不链接独立pthread库。
unix:!ios:!android: LIBS += -ldl -lpthread
android: LIBS += -ldl
android {
    QT += androidextras
    SOURCES += $$PWD/platform/android/platformfiles.cpp
    ANDROID_MIN_SDK_VERSION = 29
    ANDROID_TARGET_SDK_VERSION = 35
    ANDROID_ABIS = arm64-v8a
    QMAKE_LFLAGS += -Wl,-z,max-page-size=16384
    isEmpty(ANDROID_PACKAGE_SOURCE_DIR): ANDROID_PACKAGE_SOURCE_DIR = $$PWD/platform/android
}
ios {
    OBJECTIVE_SOURCES += $$PWD/platform/ios/presenter.mm $$PWD/platform/ios/platformfiles.mm $$PWD/platform/ios/share/Inbox.mm
    QMAKE_OBJECTIVE_CXXFLAGS += -fobjc-arc
    LIBS += -framework UIKit -framework UniformTypeIdentifiers
    QMAKE_ENTITLEMENTS = $$PWD/platform/ios/DuktoNextMobile.entitlements
    QMAKE_IOS_DEPLOYMENT_TARGET = 15.0
    QMAKE_APPLE_DEVICE_ARCHS = arm64
    QMAKE_INFO_PLIST = $$PWD/platform/ios/Info.plist
    QMAKE_BUNDLE = org.duktonext.mobile
    QMAKE_IOS_TARGETED_DEVICE_FAMILY = 1,2
    QMAKE_LFLAGS += -Wl,-dead_strip
}
