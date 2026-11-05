#include "sessionpolicy.h"
#include "error.h"
#include "protocol.h"

namespace dukto {
// 日期：2026-11-05；协议和本机配置共用上界及规范十进制校验，拒绝 0/负数/浮点/溢出。
int checkedSessionSeconds(const QJsonValue &value) {
    const auto seconds = next::decimal(value, DefaultSessionSeconds);
    if (!seconds)
        throw Error(ExitCode::Config, QStringLiteral("会话有效期须为 1 到 86400 秒"), "session");
    return static_cast<int>(seconds);
}

// 日期：2026-11-05；只读单个私有键，未知字段或版本不可静默回到默认宽松策略。
int loadSessionSeconds(const PrivateStore &store) {
    if (!store.exists("session-policy.json"))
        return DefaultSessionSeconds;
    const auto object = next::parseControl(store.read("session-policy.json"));
    if (object.size() != 2 || object["version"] != 1 || !object.contains("seconds"))
        throw Error(ExitCode::Config, QStringLiteral("认证会话策略损坏或版本不支持"), "session");
    return checkedSessionSeconds(object["seconds"]);
}

// 日期：2026-11-05；只有完整有效的策略才发布，失败不覆盖原值，不修改已有会话的截止时间。
void setSessionSeconds(const PrivateStore &store, const QJsonValue &value) {
    const auto seconds = checkedSessionSeconds(value);
    store.write("session-policy.json",
                next::encodeControl({{"version", 1}, {"seconds", QString::number(seconds)}}));
}

// 日期：2026-11-05；事件明确新连接生效和同任务恢复，避免把访问秘密或会话到期混同凭据撤销。
QJsonObject sessionPolicyInfo(const PrivateStore &store) {
    const auto seconds = loadSessionSeconds(store);
    return {
        {"eventVersion", 1},
        {"event", "session-policy"},
        {"seconds", QString::number(seconds)},
        {"message", QStringLiteral("认证会话有效期 %1 秒，新连接生效；到期后使用相同资料继续原任务")
                        .arg(seconds)}};
}

// 日期：2026-11-05；整数乘法提升为 64 位，单调时钟不受系统日期或时区修改影响。
AuthenticatedSession::AuthenticatedSession(int seconds) : milliseconds_(qint64(seconds) * 1000) {
    checkedSessionSeconds(QString::number(seconds));
    elapsed_.start();
}

// 日期：2026-11-05；本类没有续期入口，普通业务、心跳和轮换不能把已过期连接变成新会话。
void AuthenticatedSession::check() const {
    if (elapsed_.elapsed() >= milliseconds_)
        throw Error(ExitCode::Permission,
                    QStringLiteral("认证会话已到期，请用相同资料重新连接并继续原任务"), "session");
}
} // namespace dukto
