# 日期：2026-11-25；原生分享扩展单独构建，不加载Qt或传输核心。
cmake_minimum_required(VERSION 3.22)
project(DuktoShare LANGUAGES CXX OBJCXX)
add_executable(DuktoShare MACOSX_BUNDLE ShareController.mm Inbox.mm)
target_compile_features(DuktoShare PRIVATE cxx_std_14)
target_compile_options(DuktoShare PRIVATE -fobjc-arc -fapplication-extension)
target_link_libraries(DuktoShare PRIVATE "-framework Foundation" "-framework UIKit" "-framework UniformTypeIdentifiers")
set_target_properties(DuktoShare PROPERTIES
    XCODE_PRODUCT_TYPE "com.apple.product-type.app-extension"
    BUNDLE_EXTENSION "appex"
    OBJCXX_STANDARD 14
    OBJCXX_STANDARD_REQUIRED YES
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist"
    XCODE_ATTRIBUTE_PRODUCT_BUNDLE_IDENTIFIER "org.duktonext.mobile.share"
    XCODE_ATTRIBUTE_WRAPPER_EXTENSION "appex"
    XCODE_ATTRIBUTE_APPLICATION_EXTENSION_API_ONLY "YES"
    XCODE_ATTRIBUTE_CODE_SIGN_ENTITLEMENTS "${CMAKE_CURRENT_SOURCE_DIR}/DuktoShare.entitlements"
    XCODE_ATTRIBUTE_TARGETED_DEVICE_FAMILY "1,2"
    XCODE_ATTRIBUTE_SKIP_INSTALL "YES")
