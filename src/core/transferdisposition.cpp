#include "transferdisposition.h"
#include "dispositionjournal.h"
#include "error.h"
#include "protocol.h"
#include "sourcefile.h"
#include <QDir>

namespace dukto {
// 日期：2026-11-06；历史跳过只证明原决定，复制目录固定原生句柄，正文按固定片段重算冻结SHA。
QJsonObject
verifyCompletedSource(StrongManifest &manifest, DispositionJournal &outcomes,
                      const std::function<void()> &check,
                      const std::function<QString(const StrongEntry &)> &sourceForCopied) {
    const auto summary = outcomes.summary(true, check);
    const auto info = manifest.summary();
    if (summary["manifest"] != info["sha256"] || summary["totalEntries"] != info["entries"] ||
        summary["totalBytes"] != info["bytes"])
        throw Error(ExitCode::Integrity, QStringLiteral("发送历史与冻结清单不同"), "completion");
    const auto count = next::decimal(info["entries"], 10000000);
    for (quint64 id = 1; id <= count; ++id) {
        if (check)
            check();
        const auto item = outcomes.item(id);
        if (item["disposition"] == "skipped")
            continue;
        if (item["disposition"] != "copied")
            throw Error(ExitCode::Integrity, QStringLiteral("发送历史包含未完成处置"),
                        "completion");
        const auto entry = manifest.entry(id);
        const auto source = sourceForCopied ? sourceForCopied(entry) : entry.source;
        if (!QDir::isAbsolutePath(source) ||
            QDir::cleanPath(source) != QDir::cleanPath(entry.source))
            throw Error(ExitCode::Integrity, QStringLiteral("发送历史源映射与冻结清单不同"),
                        "completion");
        if (entry.directory) {
#ifdef Q_OS_WIN
            NativeDirectoryLock held(source, false);
#else
            PosixDirectory held(source, false);
            held.verify();
#endif
            if (check)
                check();
            continue;
        }
        SourceFile input(source);
        if (input.device().size() != entry.bytes)
            throw Error(ExitCode::Integrity, QStringLiteral("发送历史源大小已变化"), "completion");
        QCryptographicHash hash(QCryptographicHash::Sha256);
        qint64 remaining = entry.bytes;
        while (remaining > 0) {
            if (check)
                check();
            input.verify();
            const auto bytes = input.device().read(qMin(remaining, BufferSize));
            if (bytes.isEmpty())
                throw Error(ExitCode::Disk, QStringLiteral("发送历史源重读失败"), "completion");
            hash.addData(bytes);
            remaining -= bytes.size();
        }
        input.verify();
        if (check)
            check();
        if (hash.result() != entry.sha256)
            throw Error(ExitCode::Integrity, QStringLiteral("发送历史源正文已变化"), "completion");
    }
    return summary;
}

// 日期：2026-11-06；统一发送准备和最终处置，复制不能携带跳过根，跳过不能丢失原始根。
void addTransferDisposition(QJsonObject &object, const DurableReceive::Preparation &value,
                            bool final) {
    if (value.skipped != (value.skippedRoot != 0))
        throw Error(ExitCode::Integrity, QStringLiteral("传输处置根与决定不同"), "disposition");
    object["path"] = validateRelativePath(value.path);
    object["disposition"] =
        value.skipped ? (final ? "skipped" : "skip") : (final ? "copied" : "receive");
    object["skippedRoot"] = QString::number(value.skippedRoot);
}

// 日期：2026-11-06；每次仅读取本项和最多一个祖先，目录规模不会增加内存；历史决定不得反转。
DurableReceive::Preparation readTransferDisposition(const QJsonObject &object,
                                                    StrongManifest &manifest, quint64 file,
                                                    bool final,
                                                    const DurableReceive::Preparation *prepared) {
    const auto entry = manifest.entry(file);
    const auto action = object["disposition"].toString();
    const bool skipped = action == (final ? "skipped" : "skip");
    const auto root = next::decimal(object["skippedRoot"], file);
    if (!object["path"].isString() || object["path"] != entry.relative ||
        (!skipped && action != (final ? "copied" : "receive")) || skipped != (root != 0))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项处置与冻结清单不同"), "disposition");
    if (skipped && root != file) {
        const auto ancestor = manifest.entry(root);
        if (!ancestor.directory || !entry.relative.startsWith(ancestor.relative + '/'))
            throw Error(ExitCode::Integrity, QStringLiteral("跳过根不是清单祖先目录"),
                        "disposition");
    }
    const DurableReceive::Preparation result{validateRelativePath(object["path"].toString()),
                                             skipped, root};
    if (prepared && (prepared->path != result.path ||
                     (prepared->skipped && (!result.skipped || prepared->skippedRoot != root)) ||
                     (!prepared->skipped && skipped && root != file)))
        throw Error(ExitCode::Integrity, QStringLiteral("最终处置不能反转原准备决定"),
                    "disposition");
    return result;
}
} // namespace dukto
