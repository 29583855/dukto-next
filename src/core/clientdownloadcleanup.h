#pragma once

#include "privatestore.h"
#include <QJsonObject>
#include <QUuid>
#include <functional>

namespace dukto {
// 日期：2026-11-07；只清理身份可验证的未完成下载文件，保留最终文件和任务历史。
QJsonObject cleanupClientDownload(PrivateStore &store, const QUuid &task, bool apply,
                                  quint64 after = 0, const std::function<void()> &check = {});
} // namespace dukto
