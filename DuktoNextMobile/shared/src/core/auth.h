#pragma once

#include "privatestore.h"
#include <QDateTime>
#include <QJsonArray>
#include <QList>
#include <QUuid>

namespace dukto {
struct Grant {
    QString share;
    bool browse = false;
    bool download = false;
    bool upload = false;
};
struct Principal {
    QUuid client;
    quint64 revision = 1;
    QList<Grant> grants;
    // 日期：2026-11-04；只输出主体 ID、权限和修订号，不包含令牌或其摘要。
    QJsonObject publicInfo() const;
};
struct PairingOffer {
    QByteArray credential;
    QDateTime expires;
};

// 日期：2026-11-04；共享名只允许有界 ASCII 标识，名称不能用于编码原生目录路径。
QString validateShareName(const QString &name);
// 日期：2026-11-04；校验并显式编码授权数组，最多 16 个共享，不接受空权限或重复共享名。
QJsonArray encodeGrants(const QList<Grant> &grants);
// 日期：2026-11-04；严格解析本地/网络授权字段，不接受隐式布尔值或未知字段。
QList<Grant> decodeGrants(const QJsonArray &array);

class AuthStore final {
  public:
    // 日期：2026-11-04；所有凭据记录保存在已经通过原生权限核验的私有状态根。
    explicit AuthStore(PrivateStore &store);
    // 日期：2026-11-04；服务端本地颁发一次性 256 位配对凭据，限定 30–600 秒及明确权限。
    PairingOffer issue(const QList<Grant> &grants, int lifetimeSeconds = 300);
    // 日期：2026-11-04；客户端先持久保存自己的随机访问凭据再配对，确认丢失可用同一身份安全重试。
    Principal pair(const QByteArray &pairingCredential, const QUuid &client,
                   const QByteArray &accessCredential);
    // 日期：2026-11-04；每次连接和敏感操作重查凭据摘要与撤销状态，未授权统一拒绝。
    Principal authenticate(const QUuid &client, const QByteArray &accessCredential) const;
    // 日期：2026-11-05；在修改锁内复核原凭据并原子替换摘要，保留主体/授权且立即拒绝旧凭据。
    Principal rotate(const QUuid &client, const QByteArray &currentCredential,
                     const QByteArray &nextCredential);
    // 日期：2026-11-04；本地管理员修改授权立即递增修订号，活动通道须重查后继续操作。
    void setGrants(const QUuid &client, const QList<Grant> &grants);
    // 日期：2026-11-04；撤销记录持久化后所有新连接、任务查询和恢复均拒绝，不能通过重新配对复活。
    void revoke(const QUuid &client);
    // 日期：2026-11-05；本地管理员按规范 UUID
    // 游标分页查看主体/授权/撤销，不返回秘密、摘要或配对键。
    QJsonObject clients(const QString &after = QString()) const;

  private:
    // 日期：2026-11-04；跨进程修改锁和每类型 1024 记录的固定上限限制状态规模。
    void checkCount(const QString &prefix) const;
    PrivateStore &store_;
};
} // namespace dukto
