#pragma once

#include "privatestore.h"
#include <QJsonObject>
#include <QSslCertificate>
#include <QSslConfiguration>
#include <QSslKey>
#include <QStringList>
#include <QUuid>

namespace dukto {
struct ServiceIdentity {
    QUuid id;
    QSslCertificate certificate;
    QSslKey key;
    // 日期：2026-11-04；构造服务 TLS 配置，普通启动只使用已持久化身份，不临时替换身份。
    QSslConfiguration configuration() const;
    // 日期：2026-11-04；仅返回可公开核对的 ID、叶证书指纹、有效期及 SAN，不返回私钥。
    QJsonObject publicInfo() const;
};

// 日期：2026-11-04；产生操作系统密码学随机的 256 位凭据，失败时不得回退到弱随机。
QByteArray randomCredential();
// 日期：2026-11-04；固定长度秘密比较避免按第一个不同字节提前返回。
bool secureEqual(const QByteArray &first, const QByteArray &second);
// 日期：2026-11-04；初始化独立 RSA3072/SHA256 自签身份并原子保存，已有身份明确拒绝覆盖。
ServiceIdentity initializeIdentity(PrivateStore &store, const QStringList &names,
                                   int validDays = 365);
// 日期：2026-11-04；核对受保护记录、证书私钥匹配与期限，损坏/过期/缺失均拒绝普通启动。
ServiceIdentity loadIdentity(const PrivateStore &store);
// 日期：2026-11-05；允许查看过期/尚未生效身份的公开材料，仍拒绝损坏或私钥不匹配的记录。
QJsonObject inspectIdentity(const PrivateStore &store);
// 日期：2026-11-05；旧指纹显式绑定并串行原子续期，保留UUID、授权与任务；监听器须重新创建才采用新证书。
QJsonObject renewIdentity(PrivateStore &store, const QByteArray &expectedFingerprint,
                          const QStringList &names = {}, int validDays = 365);
} // namespace dukto
