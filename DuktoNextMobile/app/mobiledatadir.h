#pragma once

#include "core/error.h"
#include <QDir>
#include <QFileInfo>
#include <QStandardPaths>

namespace mobile {
// 日期：2026-11-25；仅规范化系统提供的私有沙箱根，消除Android/iOS系统别名；用户路径仍逐级拒绝链接。
inline QString applicationDataDirectory() {
    const auto supplied = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    if (supplied.isEmpty() || !QDir().mkpath(supplied))
        throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("无法创建应用私有目录"),
                           "mobile-storage");
    const auto canonical = QFileInfo(supplied).canonicalFilePath();
    if (canonical.isEmpty() || !QFileInfo(canonical).isDir())
        throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("无法解析应用私有目录"),
                           "mobile-storage");
    return canonical;
}
} // namespace mobile
