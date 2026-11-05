#include "transferdisposition.h"
#include "error.h"
#include "protocol.h"

namespace dukto {
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
