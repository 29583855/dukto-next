#include "uploadmanifest.h"
#include "error.h"
#include "protocol.h"
#include "service.h"
#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>

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
    bool created = false;
    try {
        manifest_.reset(new StrongManifest(store, database, true, checkpoint));
        created = true;
        manifest_->scan(paths, cancel, checkpoint);
        const auto mapping = sourceMapping(*manifest_, checkpoint);
        checkpoint();
        store.write(record, next::encodeControl({{"version", 1},
                                                 {"binding", binding},
                                                 {"manifest", manifest_->summary()},
                                                 {"sourceMappingSha256", mapping}}));
    } catch (...) {
        // 日期：2026-11-06；正常扫描失败只回收本次自建库；若冻结记录已发布则完整保留原证据。
        manifest_.reset();
        try {
            if (created && !store.exists(record))
                for (const auto &name : {database, database + "-journal"})
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
} // namespace dukto
