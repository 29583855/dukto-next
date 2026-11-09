#include "browse.h"
#include "error.h"
#include "files.h"
#include "identity.h"
#include "protocol.h"
#include "sourcefile.h"

#include <QDirIterator>
#include <QFileInfo>
#include <QJsonDocument>
#include <QLockFile>
#include <QMessageAuthenticationCode>
#include <QRegularExpression>
#include <limits>

namespace dukto {
namespace {
#ifdef Q_OS_WIN
using Directory = NativeDirectoryLock;
#else
using Directory = PosixDirectory;
#endif

// 日期：2026-11-04；快照键由服务随机产生，远端游标不能指定任意私有文件名。
QString snapshotName(const QString &id) {
    const QUuid uuid(id);
    if (uuid.isNull() || uuid.toString(QUuid::WithoutBraces) != id)
        throw Error(ExitCode::Permission, QStringLiteral("浏览游标身份无效"), "browse");
    return "browse-" + id;
}

// 日期：2026-11-09；名称仅定位凭据，不能凭前缀授予快照删除资格。
QString retentionName(const QUuid &snapshot) {
    if (snapshot.isNull())
        throw Error(ExitCode::Config, QStringLiteral("浏览快照身份无效"), "cleanup");
    return "snapshot-retention-" + snapshot.toString(QUuid::WithoutBraces) + ".json";
}

// 日期：2026-11-09；源句柄身份去掉内部尾分隔符，与原生删除接口使用同一编码。
QByteArray snapshotIdentity(SourceFile &file) {
    auto identity = file.objectIdentity();
    if (!identity.endsWith(':'))
        throw Error(ExitCode::Integrity, QStringLiteral("浏览对象身份编码无效"), "cleanup");
    identity.chop(1);
    return identity;
}

// 日期：2026-11-09；在发布说明后记录两个实际普通对象身份；老快照无凭据时不进入新自动回收。
void noteRetention(PrivateStore &store, const QString &id) {
    const auto base = snapshotName(id);
    store.validateFile(base + ".data");
    store.validateFile(base + ".json");
    SourceFile data(QDir(store.directory()).filePath(base + ".data"),
                    SourceFile::OpenPolicy::PrivateState);
    SourceFile metadata(QDir(store.directory()).filePath(base + ".json"),
                        SourceFile::OpenPolicy::PrivateState);
    const auto value = next::parseControl(store.read(base + ".json"));
    store.write(
        retentionName(QUuid(id)),
        next::encodeControl({{"version", 1},
                             {"snapshot", id},
                             {"root", QString::fromLatin1(store.identity().toHex())},
                             {"data", QString::fromLatin1(snapshotIdentity(data).toHex())},
                             {"metadata", QString::fromLatin1(snapshotIdentity(metadata).toHex())},
                             {"expires", value["expires"]},
                             {"phase", "ready"}}));
}

// 日期：2026-11-09；身份须规范编码且有界，空身份不能被原生删除接口当成授权。
QByteArray identityField(const QJsonValue &value) {
    const auto text = value.toString().toLatin1();
    const auto result = QByteArray::fromHex(text);
    if (!value.isString() || result.isEmpty() || result.size() > 256 || result.toHex() != text)
        throw Error(ExitCode::Integrity, QStringLiteral("浏览回收原生身份无效"), "cleanup");
    return result;
}

// 日期：2026-11-09；预先核对全部仍存在的对象，删除首项之前拒绝同名换代或不安全权限。
void verifySnapshotObject(PrivateStore &store, const QString &name, const QByteArray &identity) {
    if (!store.exists(name))
        return;
    store.validateFile(name);
    SourceFile file(QDir(store.directory()).filePath(name), SourceFile::OpenPolicy::PrivateState);
    if (snapshotIdentity(file) != identity)
        throw Error(ExitCode::Integrity, QStringLiteral("浏览快照对象已换代，保留原数据"),
                    "cleanup");
}

// 日期：2026-11-04；游标包含不可伪造的快照/偏移 HMAC，偏移只使用规范十进制。
QString cursorFor(const QString &id, quint64 offset, const QByteArray &key) {
    const auto body = id.toLatin1() + '.' + QByteArray::number(offset);
    const auto mac =
        QMessageAuthenticationCode::hash(body, key, QCryptographicHash::Sha256).toHex();
    return QString::fromLatin1(body + '.' + mac);
}

// 日期：2026-11-04；列表不跟随链接取外部目标属性，跨平台非法名字明确标记为不可传输。
QJsonObject entry(const QString &path) {
    const QFileInfo info(path);
    QJsonObject result{{"name", info.fileName()}, {"bytes", "0"}};
    if (isLinkedPath(path))
        result["type"] = "link";
    else if (info.isDir())
        result["type"] = "directory";
    else if (info.isFile()) {
        result["type"] = "file";
        result["bytes"] = QString::number(info.size());
    } else {
        result["type"] = "special";
    }
    try {
        validateRelativePath(info.fileName());
    } catch (const Error &) {
        result["type"] = "unsupported-name";
    }
    return result;
}
// 日期：2026-11-09；仅由独占维护或持browse.lock的创建入口调用，同一校验覆盖两条回收路径。
QJsonObject cleanupSnapshot(PrivateStore &store, const QUuid &snapshot, const QDateTime &now,
                            bool apply, const std::function<void()> &check) {
    if (!now.isValid() || now.timeSpec() != Qt::UTC)
        throw Error(ExitCode::Config, QStringLiteral("浏览回收需要独占根和UTC时钟"), "cleanup");
    const auto checkpoint = [&]() {
        // 日期：2026-11-09；取消不回滚已持久的删除意图，后续批次重新验证原对象再继续。
        if (check)
            check();
    };
    checkpoint();
    const auto name = retentionName(snapshot);
    if (!store.exists(name))
        return {{"eligible", false}, {"action", "no-retention-evidence"}};
    const auto raw = store.read(name, 4096);
    auto value = next::parseControl(raw);
    const auto expiry = QDateTime::fromString(value["expires"].toString(), Qt::ISODate);
    if (value.size() != 7 || raw != next::encodeControl(value) || value["version"] != 1 ||
        value["snapshot"] != snapshot.toString(QUuid::WithoutBraces) ||
        (value["phase"] != "ready" && value["phase"] != "deleting") || !expiry.isValid() ||
        expiry.timeSpec() != Qt::UTC || expiry.toString(Qt::ISODate) != value["expires"].toString())
        throw Error(ExitCode::Integrity, QStringLiteral("浏览回收凭据损坏，保留原数据"), "cleanup");
    const auto root = identityField(value["root"]);
    const auto data = identityField(value["data"]);
    const auto metadata = identityField(value["metadata"]);
    if (store.identity() != root)
        throw Error(ExitCode::Integrity, QStringLiteral("浏览回收状态根已换代"), "cleanup");
    if (value["phase"] == "ready" && expiry > now)
        return {{"eligible", false}, {"action", "retained"}};
    const auto base = snapshotName(snapshot.toString(QUuid::WithoutBraces));
    verifySnapshotObject(store, base + ".data", data);
    verifySnapshotObject(store, base + ".json", metadata);
    checkpoint();
    if (!apply)
        return {{"eligible", true}, {"action", "expired-preview"}};
    if (value["phase"] == "ready") {
        value["phase"] = "deleting";
        store.write(name, next::encodeControl(value));
    }
    checkpoint();
    removeReceivedTemporary(QDir(store.directory()).filePath(base + ".data"), data, false, root);
    checkpoint();
    removeReceivedTemporary(QDir(store.directory()).filePath(base + ".json"), metadata, false,
                            root);
    checkpoint();
    QByteArray marker;
    {
        SourceFile file(QDir(store.directory()).filePath(name),
                        SourceFile::OpenPolicy::PrivateState);
        if (store.read(name, 4096) != next::encodeControl(value))
            throw Error(ExitCode::Integrity, QStringLiteral("浏览删除意图已换代"), "cleanup");
        marker = snapshotIdentity(file);
    }
    removeReceivedTemporary(QDir(store.directory()).filePath(name), marker, false, root);
    checkpoint();
    return {{"eligible", true}, {"action", "cleaned"}};
}

} // namespace

// 日期：2026-11-09；外部自动维护必须持独占根；普通共享会话不能调用此入口删除快照。
QJsonObject cleanupExpiredBrowseSnapshot(PrivateStore &store, const QUuid &snapshot,
                                         const QDateTime &now, bool apply,
                                         const std::function<void()> &check) {
    if (!store.maintenance())
        throw Error(ExitCode::Config, QStringLiteral("浏览回收需要独占状态根"), "cleanup");
    return cleanupSnapshot(store, snapshot, now, apply, check);
}

// 日期：2026-11-04；实例不缓存授权或完整目录条目，跨连接权限变化会在 list 重新核对。
BrowseStore::BrowseStore(PrivateStore &store, const std::atomic_bool *cancel,
                         std::function<void()> reauthorize)
    : store_(store), cancel_(cancel), reauthorize_(std::move(reauthorize)) {
    authorizationClock_.start();
}

// 日期：2026-11-04；不会因为扫描海量小文件而无法取消当前浏览请求。
void BrowseStore::check() const {
    if (cancel_ && cancel_->load())
        throw Error(ExitCode::Cancelled, QStringLiteral("目录浏览已取消"), "browse");
    if (reauthorize_ && authorizationClock_.elapsed() >= 250) {
        reauthorize_();
        authorizationClock_.restart();
    }
}

// 日期：2026-11-09；持有浏览修改锁时复用身份凭据；无凭据的老快照保持，旁路不会无限积累。
void BrowseStore::collect() const {
    QDirIterator iterator(store_.directory(), {"snapshot-retention-*.json"},
                          QDir::Files | QDir::Hidden);
    while (iterator.hasNext()) {
        check();
        iterator.next();
        const auto name = iterator.fileInfo().fileName();
        const auto text = name.mid(19, 36);
        const QUuid id(text);
        if (id.isNull() || id.toString(QUuid::WithoutBraces) != text || name != retentionName(id))
            continue;
        cleanupSnapshot(store_, id, QDateTime::currentDateTimeUtc(), true, [this]() {
            // 日期：2026-11-09；逐个原生删除边界同样观察浏览取消，删除意图可交给后续维护继续。
            check();
        });
    }
}

// 日期：2026-11-04；单个目录项一行，流式落盘；发布元数据之前不让客户端获得有效游标。
QString BrowseStore::create(const Principal &principal, const QString &share,
                            const QString &relative) {
    QLockFile lock(store_.directory() + "/browse.lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("浏览快照正在建立，请重试"), "browse");
    collect();
    auto root = Shares(store_).open(principal, share, Access::Browse);
    const auto path = root->resolve(relative);
    Directory directory(path, false);
    const auto stamp = directory.stamp();
    qint64 used = 0;
    int snapshots = 0;
    int owned = 0;
    QDirIterator quota(store_.directory(), QDir::Files | QDir::Hidden | QDir::System);
    while (quota.hasNext()) {
        check();
        quota.next();
        const auto info = quota.fileInfo();
        if (isLinkedPath(info.absoluteFilePath()))
            throw Error(ExitCode::Permission, QStringLiteral("私有状态含非法链接"), "browse");
        if (info.size() > MaxMetadataBytes - used)
            throw Error(ExitCode::Disk, QStringLiteral("浏览与身份状态磁盘总预算已满"), "browse");
        used += info.size();
        if (info.fileName().startsWith("browse-") && info.suffix() == "json") {
            ++snapshots;
            const auto metadata = next::parseControl(store_.read(info.fileName()));
            if (metadata["client"] == principal.client.toString(QUuid::WithoutBraces))
                ++owned;
        }
    }
    if (snapshots >= 4 || owned >= 2)
        throw Error(ExitCode::Permission,
                    QStringLiteral("浏览快照数量已达上限，请复用游标或等待过期"), "browse");
    const auto id = QUuid::createUuid().toString(QUuid::WithoutBraces);
    const auto base = snapshotName(id);
    QString committed;
    try {
        IncomingFile snapshot(QDir(store_.directory()).filePath(base + ".data"));
        QDirIterator iterator(path, QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden |
                                        QDir::System);
        qint64 bytes = 0;
        qint64 entries = 0;
        while (iterator.hasNext()) {
            check();
            const auto line = next::encodeControl(entry(iterator.next())) + '\n';
            if (++entries > 10000000 || line.size() > MaxMetadataBytes - used - bytes - 4096)
                throw Error(ExitCode::Disk, QStringLiteral("目录浏览快照超过磁盘预算"), "browse");
            writeAll(snapshot.device(), line);
            bytes += line.size();
        }
        root->verify();
        if (directory.stamp() != stamp)
            throw Error(ExitCode::Integrity, QStringLiteral("目录在建立快照期间已变化，请重试"),
                        "browse");
        if (reauthorize_)
            reauthorize_();
        committed = snapshot.commit();
        if (committed != QDir(store_.directory()).filePath(base + ".data"))
            throw Error(ExitCode::Disk, QStringLiteral("浏览快照名称冲突"), "browse");
        store_.write(
            base + ".json",
            next::encodeControl(
                {{"version", 1},
                 {"client", principal.client.toString(QUuid::WithoutBraces)},
                 {"share", share},
                 {"path", relative},
                 {"stamp", QString::fromLatin1(stamp.toHex())},
                 {"cursorKey", QString::fromLatin1(randomCredential().toHex())},
                 {"bytes", QString::number(bytes)},
                 {"entries", QString::number(entries)},
                 {"expires", QDateTime::currentDateTimeUtc().addSecs(300).toString(Qt::ISODate)}}));
        noteRetention(store_, id);
    } catch (...) {
        if (!committed.isEmpty())
            QFile::remove(committed);
        throw;
    }
    return id;
}

// 日期：2026-11-04；响应同时限制 100 项和序列化 64 KiB，过大下一项留到下一页，游标可幂等重试。
QJsonObject BrowseStore::list(const Principal &principal, const QString &share,
                              const QString &relative, const QString &cursor) {
    check();
    if (reauthorize_)
        reauthorize_();
    if (!relative.isEmpty())
        validateRelativePath(relative);
    QString id;
    quint64 offset = 0;
    if (cursor.isEmpty()) {
        id = create(principal, share, relative);
    } else {
        const auto parts = cursor.split('.');
        if (parts.size() != 3 || cursor.size() > 128)
            throw Error(ExitCode::Permission, QStringLiteral("浏览游标格式无效"), "browse");
        id = parts[0];
        snapshotName(id);
        offset = next::decimal(parts[1], MaxMetadataBytes);
    }
    const auto base = snapshotName(id);
    if (!store_.exists(base + ".json"))
        throw Error(ExitCode::Permission, QStringLiteral("浏览游标不存在或已过期"), "browse");
    const auto meta = next::parseControl(store_.read(base + ".json"));
    const auto expires = QDateTime::fromString(meta["expires"].toString(), Qt::ISODate);
    const auto key = QByteArray::fromHex(meta["cursorKey"].toString().toLatin1());
    if (meta["version"] != 1 || meta["client"] != principal.client.toString(QUuid::WithoutBraces) ||
        meta["share"] != share || meta["path"] != relative || !expires.isValid() ||
        expires <= QDateTime::currentDateTimeUtc() || key.size() != 32 ||
        (!cursor.isEmpty() &&
         !secureEqual(cursor.toLatin1(), cursorFor(id, offset, key).toLatin1())))
        throw Error(ExitCode::Permission, QStringLiteral("浏览游标越权、损坏或已过期"), "browse");
    auto root = Shares(store_).open(principal, share, Access::Browse);
    Directory directory(root->resolve(relative), false);
    if (QString::fromLatin1(directory.stamp().toHex()) != meta["stamp"].toString())
        throw Error(ExitCode::Integrity, QStringLiteral("目录已变化，请重新浏览"), "browse");
    SourceFile source(QDir(store_.directory()).filePath(base + ".data"));
    auto &file = source.device();
    if (file.size() != static_cast<qint64>(next::decimal(meta["bytes"], MaxMetadataBytes)) ||
        offset > static_cast<quint64>(file.size()) || !file.seek(static_cast<qint64>(offset)))
        throw Error(ExitCode::Integrity, QStringLiteral("浏览快照文件长度或偏移无效"), "browse");
    QJsonArray array;
    QJsonObject response{{"share", share}, {"path", relative}, {"entries", array},
                         {"snapshot", id}, {"cursor", ""},     {"expiresUtc", meta["expires"]}};
    while (!file.atEnd() && array.size() < 100) {
        check();
        const auto position = file.pos();
        const auto line = file.readLine(16385);
        if (!line.endsWith('\n') || line.size() > 16384)
            throw Error(ExitCode::Integrity, QStringLiteral("浏览快照条目损坏"), "browse");
        array.append(next::parseControl(line));
        response["entries"] = array;
        if (QJsonDocument(response).toJson(QJsonDocument::Compact).size() >
            next::ControlLimit - 256) {
            if (array.size() == 1)
                throw Error(ExitCode::Config, QStringLiteral("单条浏览项超过响应预算"), "browse");
            array.removeLast();
            if (!file.seek(position))
                throw Error(ExitCode::Disk, QStringLiteral("浏览快照分页定位失败"), "browse");
            break;
        }
    }
    response["entries"] = array;
    response["cursor"] =
        file.atEnd() ? QString() : cursorFor(id, static_cast<quint64>(file.pos()), key);
    source.verify();
    root->verify();
    if (QString::fromLatin1(directory.stamp().toHex()) != meta["stamp"].toString())
        throw Error(ExitCode::Integrity, QStringLiteral("目录在分页读取期间已变化，请重新浏览"),
                    "browse");
    next::encodeControl(response);
    if (reauthorize_)
        reauthorize_();
    return response;
}
} // namespace dukto
