#pragma once

#include "privatestore.h"
#include <QDateTime>

namespace dukto {
struct StateCleanupLimits {
    int tasks = 32;
    int directoryEntries = 256;
    int milliseconds = 1000;
};

// 日期：2026-11-08；独占根内分批清理有保留期和原生证据的上传临时项，其他对象始终保留。
QJsonObject cleanupState(PrivateStore &store, const QDateTime &now, bool apply,
                         const StateCleanupLimits &limits = {},
                         const std::function<void()> &check = {});

// 日期：2026-11-08；业务打开前尝试一次短时维护；活动共享使用者优先，维护失败不阻止正常恢复。
void tryAutomaticStateCleanup(const QString &parent, const QString &relative,
                              const std::function<void()> &check = {});
} // namespace dukto
