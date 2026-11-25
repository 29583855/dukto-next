# 日期：2026-11-25；qmake负责移动平台插件和部署，核心使用CMake独立构建。
TEMPLATE = app
TARGET = DuktoNextMobile
CONFIG += c++14
QT += core gui network sql qml quick quickcontrols2
SOURCES += $$PWD/app/main.cpp
RESOURCES += $$PWD/app/mobile.qrc
INCLUDEPATH += $$PWD/shared/src $$OPENSSL_PREFIX/include
isEmpty(CORE_BUILD): error("Pass CORE_BUILD=/absolute/core-build")
isEmpty(OPENSSL_PREFIX): error("Pass OPENSSL_PREFIX=/absolute/openssl")
LIBS += -L$$CORE_BUILD -ldukto-core -ldukto-sql-driver -ldukto-sqlite
LIBS += -L$$OPENSSL_PREFIX/lib -lssl -lcrypto
unix:!ios: LIBS += -ldl -lpthread
android {
    ANDROID_MIN_SDK_VERSION = 29
    ANDROID_TARGET_SDK_VERSION = 35
    ANDROID_ABIS = arm64-v8a
    QMAKE_LFLAGS += -Wl,-z,max-page-size=16384
    ANDROID_PACKAGE_SOURCE_DIR = $$PWD/platform/android
}
ios {
    QMAKE_IOS_DEPLOYMENT_TARGET = 15.0
    QMAKE_APPLE_DEVICE_ARCHS = arm64
    QMAKE_INFO_PLIST = $$PWD/platform/ios/Info.plist
    QMAKE_BUNDLE = org.duktonext.mobile
    QMAKE_IOS_TARGETED_DEVICE_FAMILY = 1,2
    QMAKE_LFLAGS += -Wl,-dead_strip
}
