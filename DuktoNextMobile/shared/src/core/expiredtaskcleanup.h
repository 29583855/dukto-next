#pragma once

#include "taskstore.h"
#include <functional>

namespace dukto {
// 日期：2026-11-07；本机独占维护服务器上传任务；保留元数据、幂等键、目录与最终文件。
QJsonObject cleanupExpiredUpload(PrivateStore &store, const QUuid &owner, const QUuid &id,
                                 const QDateTime &now, bool apply, quint64 after = 0,
                                 const std::function<void()> &check = {});
} // namespace dukto
