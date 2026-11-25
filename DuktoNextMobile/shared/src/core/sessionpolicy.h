#pragma once

#include "privatestore.h"
#include <QElapsedTimer>
#include <QJsonObject>

namespace dukto {
constexpr int DefaultSessionSeconds = 86400;

// 日期：2026-11-05；只接受 1–86400 的规范十进制字符串，不用帧超时替代认证会话寿命。
int checkedSessionSeconds(const QJsonValue &value);
// 日期：2026-11-05；缺省为 24 小时，已有策略必须是受保护的完整、版本正确的记录。
int loadSessionSeconds(const PrivateStore &store);
// 日期：2026-11-05；原子保存本机管理策略，改变只影响之后成功认证的新连接。
void setSessionSeconds(const PrivateStore &store, const QJsonValue &value);
// 日期：2026-11-05；公开事件只含时长和使用说明，GUI/CLI 共用同一策略读取规则。
QJsonObject sessionPolicyInfo(const PrivateStore &store);

class AuthenticatedSession final {
  public:
    // 日期：2026-11-05；成功配对/认证后建立一次单调截止时间，心跳和凭据轮换均不重置。
    explicit AuthenticatedSession(int seconds);
    // 日期：2026-11-05；到期统一返回 permission/session，调用方保留检查点并要求重新认证恢复。
    void check() const;

  private:
    QElapsedTimer elapsed_;
    qint64 milliseconds_;
};
} // namespace dukto
