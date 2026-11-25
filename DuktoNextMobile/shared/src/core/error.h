#pragma once

#include <QJsonObject>
#include <QString>
#include <stdexcept>

namespace dukto {
enum class ExitCode {
    Success = 0,
    Runtime = 1,
    Config = 2,
    Network = 3,
    Permission = 4,
    Disk = 5,
    Integrity = 6,
    Cancelled = 7
};

class Error final : public std::runtime_error {
  public:
    // 日期：2026-11-04；保存统一错误码、阶段及可供 GUI/CLI 展示的说明。
    Error(ExitCode code, const QString &message, const QString &stage = QString());
    // 日期：2026-11-04；生成不包含凭据或文件正文的结构化错误。
    QJsonObject json() const;
    ExitCode code;
    QString message;
    QString stage;
};
} // namespace dukto
