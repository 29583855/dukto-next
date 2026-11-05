#pragma once

#include "privatestore.h"
#include "taskstore.h"

namespace dukto {
// 日期：2026-11-05；严格验证公开失败证据；旧端缺少能力时不要求新增可选字段。
void validateItemFailure(const QJsonObject &item, bool available);
// 日期：2026-11-05；只读分页显示持久接收证据；不重验正文、不改变任务或接收日志。
QJsonObject transferItems(PrivateStore &store, const TransferTask &task,
                          const QString &manifestName, const QString &root, quint64 after = 0);
// 日期：2026-11-05；下载明细先绑定已认证服务、主体、请求及本地目标，缺少本机记录明确返回不可用。
QJsonObject localDownloadItems(PrivateStore &store, const QUuid &server, const QUuid &client,
                               const TransferTask &task, quint64 after = 0);
} // namespace dukto
