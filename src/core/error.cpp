#include "error.h"

namespace dukto {
// 日期：2026-11-04；异常保留 UTF-8 文本，同时提供稳定的退出码。
Error::Error(ExitCode value, const QString &text, const QString &phase)
    : std::runtime_error(text.toUtf8().constData()), code(value), message(text), stage(phase) {
}

// 日期：2026-11-04；与命令行 JSON 事件共用错误字段。
QJsonObject Error::json() const {
    return {{"eventVersion", 1},
            {"event", "error"},
            {"code", static_cast<int>(code)},
            {"stage", stage},
            {"message", message}};
}
} // namespace dukto
