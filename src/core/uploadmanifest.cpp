#include "uploadmanifest.h"
#include "error.h"
#include "protocol.h"
#include "service.h"
#include "sourcefile.h"
#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>
#include <QRegularExpression>
#include <QSqlError>
#include <QSqlQuery>

namespace dukto {
namespace {
// 日期：2026-11-06；仅散列本机路径文字，不查询文件是否存在；长度编码避免路径拼接歧义。
void addPath(QCryptographicHash &hash, const QString &path) {
    const auto bytes = path.toUtf8();
    hash.addData(QByteArray::number(bytes.size()));
    hash.addData(":", 1);
    hash.addData(bytes);
}

// 日期：2026-11-06；本机绝对源映射不进入网络强身份，单项读取另行绑定，内存不随条目增长。
QString sourceMapping(StrongManifest &manifest, const std::function<void()> &check) {
    QCryptographicHash hash(QCryptographicHash::Sha256);
    const auto count = next::decimal(manifest.summary()["entries"], 10000000);
    for (quint64 id = 1; id <= count; ++id) {
        check();
        const auto entry = manifest.entry(id);
        if (!QDir::isAbsolutePath(entry.source) || QDir::cleanPath(entry.source) != entry.source)
            throw Error(ExitCode::Integrity, QStringLiteral("上传冻结源映射无效"), "manifest");
        hash.addData(QByteArray::number(id));
        hash.addData(":", 1);
        addPath(hash, entry.source);
    }
    return QString::fromLatin1(hash.result().toHex());
}

// 日期：2026-11-07；SourceFile的对象编码以冒号结尾，原生删除编码不含尾分隔，统一后持久绑定。
QByteArray scanIdentity(PrivateStore &store, const QString &name) {
    store.validateFile(name);
    SourceFile file(QDir(store.directory()).filePath(name), SourceFile::OpenPolicy::PrivateState);
    auto identity = file.objectIdentity();
    if (!identity.endsWith(':'))
        throw Error(ExitCode::Integrity, QStringLiteral("源扫描对象身份编码无效"), "cleanup");
    identity.chop(1);
    return identity;
}

// 日期：2026-11-07；预览和执行均计量普通库与回滚旁路，不把未知WAL或超额文件当作可删缓存。
qint64 scanBytes(PrivateStore &store, const QString &name) {
    qint64 bytes = store.validateFile(name);
    for (const auto &suffix : QStringList{"-journal", "-wal", "-shm"}) {
        if (!store.exists(name + suffix))
            continue;
        const auto size = suffix == "-journal" ? store.validateSqliteJournal(name + suffix)
                                               : store.validateFile(name + suffix);
        if (suffix != "-journal" || size > MaxMetadataBytes - bytes)
            throw Error(ExitCode::Config, QStringLiteral("源扫描旁路类型或预算无效"), "cleanup");
        bytes += size;
    }
    if (bytes > MaxMetadataBytes)
        throw Error(ExitCode::Disk, QStringLiteral("源扫描库及旁路超出预算"), "cleanup");
    return bytes;
}

// 日期：2026-11-07；让SQLite自行恢复本库DELETE回滚日志；不手工删除journal/WAL或接管未知架构。
void recoverScanJournal(PrivateStore &store, const QString &name) {
    scanBytes(store, name);
    const auto connection = QUuid::createUuid().toString();
    // 日期：2026-11-07；先申请缓存授信，额度不足时不能留下未进入清理作用域的Qt连接。
    SqliteCacheCredit credit(1024);
    auto database = QSqlDatabase::addDatabase("QSQLITE", connection);
    try {
        database.setDatabaseName(QDir(store.directory()).filePath(name));
        database.setConnectOptions("QSQLITE_BUSY_TIMEOUT=1000");
        if (!database.open())
            throw Error(ExitCode::Disk, QStringLiteral("无法恢复源扫描日志"), "cleanup");
        credit.configure(database);
        QSqlQuery query(database);
        if (!query.exec("PRAGMA journal_mode") || !query.next() ||
            query.value(0).toString().compare("delete", Qt::CaseInsensitive) != 0)
            throw Error(ExitCode::Integrity, QStringLiteral("源扫描日志模式无效"), "cleanup");
        query.finish();
        for (const auto &statement :
             {"SELECT id,relative,source,directory,bytes,sha,pathkey FROM entries LIMIT 0",
              "SELECT file,block,bytes,sha FROM blocks LIMIT 0",
              "SELECT value FROM metadata LIMIT 0", "BEGIN IMMEDIATE", "COMMIT"}) {
            if (!query.exec(statement))
                throw Error(ExitCode::Integrity, QStringLiteral("源扫描架构或回滚恢复失败"),
                            "cleanup");
            query.finish();
        }
    } catch (...) {
        database.close();
        database = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection);
        throw;
    }
    database.close();
    database = QSqlDatabase();
    QSqlDatabase::removeDatabase(connection);
    if (store.exists(name + "-journal"))
        throw Error(ExitCode::Integrity, QStringLiteral("源扫描回滚日志尚未恢复，保留原件"),
                    "cleanup");
}
} // namespace

// 日期：2026-11-06；先固定请求/主体/目标/原路径，再校验磁盘清单及本地源映射；缺失证据不能重建冒充原件。
UploadManifest::UploadManifest(PrivateStore &store, const QUuid &request,
                               const ClientProfile &profile, const QString &share,
                               const QString &relative, ConflictPolicy conflict,
                               const QStringList &paths, const std::atomic_bool *cancel,
                               const std::function<void()> &check) {
    const auto checkpoint = [&]() {
        // 日期：2026-11-06；目录扫描、清单重验及源映射摘要均响应同一取消及总期限。
        if (check)
            check();
        if (cancel && cancel->load())
            throw Error(ExitCode::Cancelled, QStringLiteral("上传清单操作已取消"), "manifest");
    };
    checkpoint();
    if (request.isNull() || profile.server.isNull() || profile.client.isNull() || paths.isEmpty())
        throw Error(ExitCode::Config, QStringLiteral("上传清单请求、身份或源路径无效"), "manifest");
    const auto stem = "upload-source-" + request.toString(QUuid::WithoutBraces);
    const auto database = stem + ".sqlite";
    const auto record = stem + ".json";
    const auto scanRecord = stem + ".scan.json";
    ownership_.reset(new QLockFile(QDir(store.directory()).filePath(stem + ".lock")));
    ownership_->setStaleLockTime(0);
    if (!ownership_->tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("本地同一上传源清单正在使用"), "manifest");
    QCryptographicHash roots(QCryptographicHash::Sha256);
    for (const auto &path : paths) {
        checkpoint();
        if (path.isEmpty())
            throw Error(ExitCode::Config, QStringLiteral("上传源路径为空"), "manifest");
        addPath(roots, QDir::cleanPath(QFileInfo(path).absoluteFilePath()));
    }
    const QJsonObject binding{{"request", request.toString(QUuid::WithoutBraces)},
                              {"server", profile.server.toString(QUuid::WithoutBraces)},
                              {"client", profile.client.toString(QUuid::WithoutBraces)},
                              {"share", share},
                              {"path", relative},
                              {"conflict", conflictPolicyName(conflict)},
                              {"roots", QString::fromLatin1(roots.result().toHex())},
                              {"rootCount", QString::number(paths.size())}};
    if (store.exists(record)) {
        const auto saved = next::parseControl(store.read(record));
        if (saved["version"] != 1 || saved["binding"] != binding || !store.exists(database))
            throw Error(ExitCode::Integrity, QStringLiteral("上传冻结清单绑定不同或原库缺失"),
                        "manifest");
        manifest_.reset(new StrongManifest(store, database, false, checkpoint));
        if (saved["manifest"] != manifest_->summary() ||
            saved["sourceMappingSha256"] != sourceMapping(*manifest_, checkpoint))
            throw Error(ExitCode::Integrity, QStringLiteral("上传冻结内容或源映射已变化"),
                        "manifest");
        checkpoint();
        return;
    }
    if (store.exists(database))
        throw Error(ExitCode::Integrity, QStringLiteral("上传源库缺少原冻结记录，已保留供检查"),
                    "manifest");
    if (store.exists(scanRecord))
        throw Error(ExitCode::Integrity, QStringLiteral("上传源扫描有待恢复清理记录"), "manifest");
    bool created = false;
    try {
        manifest_.reset(new StrongManifest(store, database, true, checkpoint));
        created = true;
        store.write(scanRecord,
                    next::encodeControl(
                        {{"version", 1},
                         {"request", request.toString(QUuid::WithoutBraces)},
                         {"binding", binding},
                         {"created", QString::number(QDateTime::currentSecsSinceEpoch())},
                         {"rootIdentity",
                          QString::fromLatin1(receivedDirectoryIdentity(store.directory()))},
                         {"native", QString::fromLatin1(scanIdentity(store, database))},
                         {"phase", "scanning"}}));
        manifest_->scan(paths, cancel, checkpoint);
        const auto mapping = sourceMapping(*manifest_, checkpoint);
        checkpoint();
        store.write(record, next::encodeControl({{"version", 1},
                                                 {"binding", binding},
                                                 {"manifest", manifest_->summary()},
                                                 {"sourceMappingSha256", mapping}}));
        store.remove(scanRecord);
    } catch (...) {
        // 日期：2026-11-06；正常扫描失败只回收本次自建库；若冻结记录已发布则完整保留原证据。
        manifest_.reset();
        try {
            if (created && !store.exists(record))
                for (const auto &name : {database, database + "-journal", scanRecord})
                    if (store.exists(name))
                        store.remove(name);
        } catch (...) {
            qWarning("上传扫描失败后的源库回收失败，已保留状态供检查");
        }
        throw;
    }
}

// 日期：2026-11-06；源库始终已冻结且归当前请求独占，传输线程通过原有只读机制获取分块身份。
StrongManifest &UploadManifest::get() const {
    return *manifest_;
}

// 日期：2026-11-07；先保留删除意图再按原生身份删除，清理后退出可重入，未知/已冻结请求不被重建。
QJsonObject cleanupUploadScan(PrivateStore &store, const QUuid &request, const QDateTime &now,
                              bool apply, const std::function<void()> &check) {
    if (!store.maintenance() || request.isNull() || !now.isValid())
        throw Error(ExitCode::Config, QStringLiteral("源扫描清理需要独占维护与有效请求"),
                    "cleanup");
    const auto checkpoint = [&]() {
        // 日期：2026-11-07；只在持久意图和原生删除的安全边界观察取消，不清空已有恢复证据。
        if (check)
            check();
    };
    checkpoint();
    const auto key = request.toString(QUuid::WithoutBraces);
    const auto stem = "upload-source-" + key;
    const auto name = stem + ".sqlite";
    const auto marker = stem + ".scan.json";
    QLockFile ownership(QDir(store.directory()).filePath(stem + ".lock"));
    ownership.setStaleLockTime(0);
    QLockFile databaseLock(QDir(store.directory()).filePath(name + ".lock"));
    databaseLock.setStaleLockTime(0);
    if (!ownership.tryLock(0) || !databaseLock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("源扫描仍有活动执行者"), "cleanup");
    QJsonObject result{{"eventVersion", 1}, {"event", "upload-scan-cleanup"},
                       {"requestId", key},  {"applied", apply},
                       {"eligible", false}, {"retentionSeconds", "604800"}};
    if (store.exists(stem + ".json") || store.exists("upload-request-" + key + ".json")) {
        result["action"] = "preserved-published";
        return result;
    }
    if (!store.exists(marker)) {
        result["action"] = store.exists(name) ? "preserved-unknown" : "absent";
        return result;
    }
    const auto raw = store.read(marker);
    auto proof = next::parseControl(raw);
    const auto created = proof["created"].toString();
    bool valid = false;
    const auto seconds = created.toLongLong(&valid);
    const auto identity = proof["native"].toString().toLatin1();
    const auto root = proof["rootIdentity"].toString().toLatin1();
    const auto phase = proof["phase"].toString();
    const auto binding = proof["binding"].toObject();
    const QUuid server(binding["server"].toString());
    const QUuid client(binding["client"].toString());
    const auto rootCount = binding["rootCount"].toString();
    bool countValid = false;
    const auto count = rootCount.toLongLong(&countValid);
    static const QRegularExpression native("\\A[0-9]+:[0-9]+(?::[0-9]+)?\\z");
    static const QRegularExpression hash("\\A[0-9a-f]{64}\\z");
    if (raw != next::encodeControl(proof) || proof.size() != 7 || proof["version"] != 1 ||
        proof["request"] != key || !proof["binding"].isObject() || binding.size() != 8 ||
        binding["request"] != key || server.isNull() || client.isNull() ||
        binding["server"] != server.toString(QUuid::WithoutBraces) ||
        binding["client"] != client.toString(QUuid::WithoutBraces) || !binding["path"].isString() ||
        !binding["share"].isString() || !hash.match(binding["roots"].toString()).hasMatch() ||
        !countValid || count < 1 || rootCount != QString::number(count) || !valid || seconds < 0 ||
        created != QString::number(seconds) ||
        !native.match(QString::fromLatin1(identity)).hasMatch() ||
        !native.match(QString::fromLatin1(root)).hasMatch() ||
        (phase != "scanning" && phase != "cleaning") ||
        root != receivedDirectoryIdentity(store.directory()))
        throw Error(ExitCode::Integrity, QStringLiteral("源扫描清理凭据无效，保留原件"), "cleanup");
    validateShareName(binding["share"].toString());
    if (!binding["path"].toString().isEmpty())
        validateRelativePath(binding["path"].toString());
    checkedConflictPolicy(binding["conflict"].toString());
    const bool eligible = phase == "cleaning" || (now.toSecsSinceEpoch() >= seconds &&
                                                  now.toSecsSinceEpoch() - seconds >= 604800);
    result["eligible"] = eligible;
    result["created"] = created;
    if (!eligible) {
        result["action"] = "retained";
        return result;
    }
    if (!store.exists(name)) {
        if (phase != "cleaning")
            throw Error(ExitCode::Integrity, QStringLiteral("源扫描正文缺失且无删除意图"),
                        "cleanup");
        for (const auto &suffix : QStringList{"-journal", "-wal", "-shm"})
            if (store.exists(name + suffix))
                throw Error(ExitCode::Integrity, QStringLiteral("源扫描缺失但仍有旁路文件"),
                            "cleanup");
    } else {
        if (scanIdentity(store, name) != identity)
            throw Error(ExitCode::Integrity, QStringLiteral("源扫描库已被替换"), "cleanup");
        result["bytes"] = QString::number(scanBytes(store, name));
        if (apply) {
            checkpoint();
            recoverScanJournal(store, name);
            if (scanIdentity(store, name) != identity)
                throw Error(ExitCode::Integrity, QStringLiteral("源扫描恢复期间身份变化"),
                            "cleanup");
        }
    }
    result["action"] = apply ? "cleaned" : "pending-cleanup";
    if (!apply)
        return result;
    if (store.exists(stem + ".json") || store.exists("upload-request-" + key + ".json"))
        throw Error(ExitCode::Integrity, QStringLiteral("源扫描请求已发布，保留原件"), "cleanup");
    proof["phase"] = "cleaning";
    store.write(marker, next::encodeControl(proof));
    checkpoint();
    if (store.exists(stem + ".json") || store.exists("upload-request-" + key + ".json"))
        throw Error(ExitCode::Integrity, QStringLiteral("源扫描请求在清理期间已发布"), "cleanup");
    if (store.exists(name)) {
        removeReceivedTemporary(QDir(store.directory()).filePath(name), identity, false, root);
    }
    checkpoint();
    store.remove(marker);
    return result;
}
} // namespace dukto
