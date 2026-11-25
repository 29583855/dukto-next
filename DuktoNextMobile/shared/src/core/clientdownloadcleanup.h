#pragma once

#include "privatestore.h"
#include <QDateTime>
#include <QJsonObject>
#include <QUuid>
#include <functional>

namespace dukto {
// 日期：2026-11-07；只清理身份可验证的未完成下载文件，保留最终文件和任务历史。
QJsonObject cleanupClientDownload(PrivateStore &store, const QUuid &task, bool apply,
                                  quint64 after = 0, const std::function<void()> &check = {});

// 日期：2026-11-09；执行者核对接收日志后记录活动时间；旧任务没有凭据时不会自动回收。
void noteClientDownloadActivity(PrivateStore &store, const QUuid &task, const QByteArray &manifest,
                                const QDateTime &now);

// 日期：2026-11-09；独占维护按七天保留期逐批回收下载临时正文，凭据不授予文件删除资格。
QJsonObject cleanupExpiredClientDownload(PrivateStore &store, const QUuid &task,
                                         const QDateTime &now, bool apply, int maximumEntries = 32,
                                         const std::function<void()> &check = {});
} // namespace dukto
