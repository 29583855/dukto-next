#pragma once

#include "auth.h"
#include "securechannel.h"

namespace dukto {
// 日期：2026-11-04；独立认证控制连接查询/暂停/取消/准备恢复；持有租约才可确认实际停止。
QJsonObject manageTransfer(PrivateStore &store, const Principal &principal,
                           const QJsonObject &request, next::Type type);
// 日期：2026-11-04；在已认证控制连接中创建/恢复持久传输任务，传输方向不改变连接发起方向。
void serveTransfer(next::SecureChannel &channel, PrivateStore &store, const Principal &principal,
                   const std::function<Principal()> &reauthenticate, const QJsonObject &request,
                   next::Type type, quint64 correlation);
} // namespace dukto
