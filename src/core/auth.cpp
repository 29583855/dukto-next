#include "auth.h"
#include "error.h"
#include "identity.h"
#include "protocol.h"

#include <QCryptographicHash>
#include <QDirIterator>
#include <QJsonDocument>
#include <QLockFile>
#include <QRegularExpression>
#include <QSet>
#include <algorithm>
#include <limits>
#include <vector>

namespace dukto {
namespace {
// 日期：2026-11-04；不区分凭据不存在、错误或已撤销，避免向未授权客户端泄漏账户状态。
[[noreturn]] void denied() {
    throw Error(ExitCode::Permission, QStringLiteral("配对或认证被拒绝，请核对凭据、有效期和授权"),
                "auth");
}

// 日期：2026-11-04；秘密不进入文件名，使用完整随机令牌的 SHA256 派生不可枚举的记录键。
QString ticketName(const QByteArray &credential) {
    if (credential.size() != 32)
        denied();
    return "pair-" +
           QString::fromLatin1(
               QCryptographicHash::hash(credential, QCryptographicHash::Sha256).toHex()) +
           ".json";
}

// 日期：2026-11-04；UUID 规范化后才用于私有键名，不能把任意远端字符串拼接成本地路径。
QString clientName(const QUuid &client) {
    if (client.isNull())
        denied();
    return "client-" + client.toString(QUuid::WithoutBraces) + ".json";
}

// 日期：2026-11-04；磁盘仅保存访问令牌摘要，任何空值或截断秘密都不会进入比较。
QByteArray credentialHash(const QByteArray &credential) {
    if (credential.size() != 32)
        denied();
    return QCryptographicHash::hash(credential, QCryptographicHash::Sha256).toHex();
}

// 日期：2026-11-05；活动与已撤销主体使用相同元数据校验，列表不能把损坏记录显示成空权限或正常身份。
Principal metadata(const QJsonObject &record, const QUuid &client) {
    const auto encodedHash = record["credentialHash"].toString().toLatin1();
    const auto hash = QByteArray::fromHex(encodedHash);
    if (record["version"] != 1 || record["client"] != client.toString(QUuid::WithoutBraces) ||
        !record["revoked"].isBool() || !record["credentialHash"].isString() || hash.size() != 32 ||
        encodedHash != hash.toHex() || !record["grants"].isArray())
        denied();
    const auto revision = next::decimal(record["revision"], std::numeric_limits<quint64>::max());
    if (!revision)
        denied();
    return {client, revision, decodeGrants(record["grants"].toArray())};
}

// 日期：2026-11-05；读取元数据前仍统一拒绝错误秘密和撤销，列表与认证复用同一格式约束。
Principal principal(const QJsonObject &record, const QUuid &client, const QByteArray &hash) {
    if (record["revoked"] != QJsonValue(false) ||
        !secureEqual(record["credentialHash"].toString().toLatin1(), hash))
        denied();
    return metadata(record, client);
}

// 日期：2026-11-04；修改权限或撤销在同一锁内提交，序号不允许回绕导致旧通道误认为权限未变。
void increment(QJsonObject &record) {
    const auto value = next::decimal(record["revision"], std::numeric_limits<quint64>::max() - 1);
    record["revision"] = QString::number(value + 1);
}
} // namespace

// 日期：2026-11-04；命名约束与授权、共享配置及远程请求一致，不使用本机大小写规则匹配。
QString validateShareName(const QString &name) {
    static const QRegularExpression allowed("\\A[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\\z");
    if (!allowed.match(name).hasMatch())
        throw Error(ExitCode::Config, QStringLiteral("共享名称无效"), "auth");
    return name;
}

// 日期：2026-11-04；客户端得到的只读与上传授权分别编码，不能把可浏览默认为可上传。
QJsonArray encodeGrants(const QList<Grant> &grants) {
    if (grants.isEmpty() || grants.size() > 16)
        throw Error(ExitCode::Config, QStringLiteral("授权共享数量必须在 1 到 16 之间"), "auth");
    QJsonArray array;
    QSet<QString> names;
    for (const auto &grant : grants) {
        validateShareName(grant.share);
        if ((!grant.browse && !grant.download && !grant.upload) || names.contains(grant.share))
            throw Error(ExitCode::Config, QStringLiteral("共享授权为空或名称重复"), "auth");
        names.insert(grant.share);
        array.append(QJsonObject{{"share", grant.share},
                                 {"browse", grant.browse},
                                 {"download", grant.download},
                                 {"upload", grant.upload}});
    }
    return array;
}

// 日期：2026-11-04；远端传来的字符串/数字不能被 Qt 的布尔缺省值静默接受。
QList<Grant> decodeGrants(const QJsonArray &array) {
    if (array.isEmpty() || array.size() > 16)
        denied();
    QList<Grant> result;
    for (const auto &value : array) {
        if (!value.isObject())
            denied();
        const auto object = value.toObject();
        if (object.size() != 4 || !object["share"].isString() || !object["browse"].isBool() ||
            !object["download"].isBool() || !object["upload"].isBool())
            denied();
        result.append({object["share"].toString(), object["browse"].toBool(),
                       object["download"].toBool(), object["upload"].toBool()});
    }
    encodeGrants(result);
    return result;
}

// 日期：2026-11-04；所有可公开授权状态均不含凭据或其摘要，适用于 GUI/CLI 显示。
QJsonObject Principal::publicInfo() const {
    return {{"client", client.toString(QUuid::WithoutBraces)},
            {"revision", QString::number(revision)},
            {"grants", encodeGrants(grants)}};
}

// 日期：2026-11-04；目录级原生权限生命周期由调用方 PrivateStore 持有，服务工作线程独立实例。
AuthStore::AuthStore(PrivateStore &store) : store_(store) {
}

// 日期：2026-11-04；只计数不加载全部记录内容，达到固定上限后明确拒绝创建而非无限增长。
void AuthStore::checkCount(const QString &prefix) const {
    QDirIterator iterator(store_.directory(), {prefix + "*.json"}, QDir::Files | QDir::Hidden);
    int count = 0;
    while (iterator.hasNext()) {
        iterator.next();
        if (++count >= 1024)
            throw Error(ExitCode::Disk,
                        QStringLiteral("身份记录配额已满，请清理过期配对或停用身份"), "auth");
    }
}

// 日期：2026-11-04；短时配对记录只存摘要与授权，明文配对凭据由本地调用方安全交付。
PairingOffer AuthStore::issue(const QList<Grant> &grants, int lifetimeSeconds) {
    const auto encoded = encodeGrants(grants);
    if (lifetimeSeconds < 30 || lifetimeSeconds > 600)
        throw Error(ExitCode::Config, QStringLiteral("配对有效期必须在 30 到 600 秒之间"), "auth");
    QLockFile lock(store_.directory() + "/auth.lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("身份状态正在修改，请重试"), "auth");
    checkCount("pair-");
    const auto credential = randomCredential();
    const auto name = ticketName(credential);
    if (store_.exists(name))
        throw Error(ExitCode::Runtime, QStringLiteral("随机配对记录冲突"), "auth");
    const auto expires = QDateTime::currentDateTimeUtc().addSecs(lifetimeSeconds);
    store_.write(name, next::encodeControl({{"version", 1},
                                            {"state", "issued"},
                                            {"expires", expires.toString(Qt::ISODate)},
                                            {"grants", encoded}}));
    return {credential, expires};
}

// 日期：2026-11-04；先绑定票据再发布客户端记录；同身份/同令牌的重试可修复绑定后崩溃。
Principal AuthStore::pair(const QByteArray &pairingCredential, const QUuid &client,
                          const QByteArray &accessCredential) {
    const auto ticket = ticketName(pairingCredential);
    const auto key = clientName(client);
    const auto hash = credentialHash(accessCredential);
    QLockFile lock(store_.directory() + "/auth.lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("身份状态正在修改，请重试"), "auth");
    if (!store_.exists(ticket))
        denied();
    auto record = next::parseControl(store_.read(ticket));
    if (record["version"] != 1 || !record["grants"].isArray())
        denied();
    decodeGrants(record["grants"].toArray());
    const bool issued = record["state"] == "issued";
    if (issued) {
        const auto expires = QDateTime::fromString(record["expires"].toString(), Qt::ISODate);
        if (!expires.isValid() || expires <= QDateTime::currentDateTimeUtc() || store_.exists(key))
            denied();
        checkCount("client-");
        record["state"] = "bound";
        record["client"] = client.toString(QUuid::WithoutBraces);
        record["credentialHash"] = QString::fromLatin1(hash);
        store_.write(ticket, next::encodeControl(record));
    } else if (record["state"] != "bound" ||
               record["client"] != client.toString(QUuid::WithoutBraces) ||
               !record["credentialHash"].isString() ||
               !secureEqual(record["credentialHash"].toString().toLatin1(), hash)) {
        denied();
    }
    if (store_.exists(key)) {
        const auto existing = next::parseControl(store_.read(key));
        if (existing["pairing"] != ticket)
            denied();
        return principal(existing, client, hash);
    }
    const QJsonObject account{{"version", 1},
                              {"client", client.toString(QUuid::WithoutBraces)},
                              {"revision", "1"},
                              {"credentialHash", QString::fromLatin1(hash)},
                              {"grants", record["grants"]},
                              {"pairing", ticket},
                              {"revoked", false}};
    store_.write(key, next::encodeControl(account));
    return principal(account, client, hash);
}

// 日期：2026-11-04；持有者必须证明完整的随机令牌，任务序号、client UUID 或配对凭据均不能替代。
Principal AuthStore::authenticate(const QUuid &client, const QByteArray &accessCredential) const {
    const auto key = clientName(client);
    const auto hash = credentialHash(accessCredential);
    if (!store_.exists(key))
        denied();
    return principal(next::parseControl(store_.read(key)), client, hash);
}

// 日期：2026-11-05；原凭据在同一锁内重验，撤销和并发轮换不能被旧认证快照覆盖。
Principal AuthStore::rotate(const QUuid &client, const QByteArray &currentCredential,
                            const QByteArray &nextCredential) {
    const auto current = credentialHash(currentCredential);
    const auto replacement = credentialHash(nextCredential);
    if (secureEqual(current, replacement))
        throw Error(ExitCode::Config, QStringLiteral("新凭据必须与原凭据不同"), "auth");
    QLockFile lock(store_.directory() + "/auth.lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("身份状态正在修改，请重试"), "auth");
    const auto key = clientName(client);
    if (!store_.exists(key))
        denied();
    auto record = next::parseControl(store_.read(key));
    principal(record, client, current);
    increment(record);
    record["credentialHash"] = QString::fromLatin1(replacement);
    store_.write(key, next::encodeControl(record));
    return principal(record, client, replacement);
}

// 日期：2026-11-04；撤销后不允许用授权修改接口重新启用，重新授权须建立明确的新客户端身份。
void AuthStore::setGrants(const QUuid &client, const QList<Grant> &grants) {
    const auto encoded = encodeGrants(grants);
    QLockFile lock(store_.directory() + "/auth.lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("身份状态正在修改，请重试"), "auth");
    const auto key = clientName(client);
    if (!store_.exists(key))
        denied();
    auto record = next::parseControl(store_.read(key));
    if (record["version"] != 1 || !record["revoked"].isBool() || record["revoked"].toBool())
        denied();
    increment(record);
    record["grants"] = encoded;
    store_.write(key, next::encodeControl(record));
}

// 日期：2026-11-04；重复撤销幂等成功，已有 bound 配对票据仍不能把已撤销的同一身份重新激活。
void AuthStore::revoke(const QUuid &client) {
    QLockFile lock(store_.directory() + "/auth.lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("身份状态正在修改，请重试"), "auth");
    const auto key = clientName(client);
    if (!store_.exists(key))
        denied();
    auto record = next::parseControl(store_.read(key));
    if (record["version"] != 1 || !record["revoked"].isBool())
        denied();
    if (record["revoked"].toBool())
        return;
    increment(record);
    record["revoked"] = true;
    store_.write(key, next::encodeControl(record));
}

// 日期：2026-11-05；流式枚举时仅保留下页 101 个键；公开页同时限制 100 条和控制帧长度。
QJsonObject AuthStore::clients(const QString &after) const {
    const QUuid cursor(after);
    if (!after.isEmpty() && (cursor.isNull() || after != cursor.toString(QUuid::WithoutBraces)))
        throw Error(ExitCode::Config, QStringLiteral("客户端列表游标必须为规范 UUID"), "auth");
    std::vector<QString> candidates;
    candidates.reserve(101);
    QDirIterator iterator(store_.directory(), {"client-*.json"},
                          QDir::Files | QDir::Hidden | QDir::System);
    int count = 0;
    while (iterator.hasNext()) {
        iterator.next();
        if (++count > 1024)
            throw Error(ExitCode::Disk, QStringLiteral("客户端身份记录超出配额"), "auth");
        const auto name = iterator.fileName();
        const auto text = name.mid(7, name.size() - 12);
        const QUuid id(text);
        if (id.isNull() || text != id.toString(QUuid::WithoutBraces))
            throw Error(ExitCode::Integrity, QStringLiteral("客户端记录名称无效"), "auth");
        if (text <= after)
            continue;
        auto position = std::lower_bound(candidates.begin(), candidates.end(), text);
        if (position != candidates.end() || candidates.size() < 101)
            candidates.insert(position, text);
        if (candidates.size() > 101)
            candidates.pop_back();
    }
    QJsonArray entries;
    auto following = after;
    for (const auto &text : candidates) {
        if (entries.size() >= 100)
            break;
        const QUuid id(text);
        const auto record = next::parseControl(store_.read(clientName(id)));
        auto info = metadata(record, id).publicInfo();
        info["revoked"] = record["revoked"];
        auto proposed = entries;
        proposed.append(info);
        // 日期：2026-11-05；预留外层字段余量；到字节上限时不吞掉尚未返回的候选身份。
        if (QJsonDocument(QJsonObject{{"entries", proposed}})
                .toJson(QJsonDocument::Compact)
                .size() > next::ControlLimit - 512)
            break;
        entries = proposed;
        following = text;
    }
    return {{"eventVersion", 1},
            {"event", "clients"},
            {"entries", entries},
            {"after", following},
            {"more", entries.size() < static_cast<int>(candidates.size())},
            {"message", QStringLiteral("客户端 %1 项；包含已撤销身份").arg(entries.size())}};
}
} // namespace dukto
