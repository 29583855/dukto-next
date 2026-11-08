#include "error.h"
#include "privatestore.h"
#include "statedomain.h"
#include <QCryptographicHash>
#include <QtEndian>
#include <limits>

namespace dukto {
namespace {
// 日期：2026-11-08；固定汇总整数不回绕；观察过大明确失败，已持久占用不因失败退款。
void accumulate(qint64 &total, qint64 value) {
    if (value < 0 || total > std::numeric_limits<qint64>::max() - value)
        throw Error(ExitCode::Integrity, QStringLiteral("已有状态占用合计溢出"),
                    "state-accounting");
    total += value;
}

// 日期：2026-11-08；根登记代数、原生卷/身份及名称共同定位保守观察，不能据此推定任务归属或删除资格。
QByteArray observationKey(const StateDomain::Binding &root, const NativeDirectoryEntry &entry) {
    if ((entry.identityPlatform != 1 && entry.identityPlatform != 2) || entry.name.isEmpty() ||
        entry.bytes < 0 || entry.allocatedBytes < 0 || !entry.links)
        throw Error(ExitCode::Integrity, QStringLiteral("已有状态原生观察不完整"),
                    "state-accounting");
    QByteArray numbers(16, '\0');
    qToLittleEndian(quint64(entry.identityPlatform), reinterpret_cast<uchar *>(numbers.data()));
    qToLittleEndian(entry.volume, reinterpret_cast<uchar *>(numbers.data() + 8));
    QCryptographicHash hash(QCryptographicHash::Sha256);
    hash.addData("dukto-unknown-observation-v1", 28);
    hash.addData(root.key);
    hash.addData(root.registration.toRfc4122());
    hash.addData(numbers);
    hash.addData(reinterpret_cast<const char *>(entry.identity.data()), int(entry.identity.size()));
    hash.addData(entry.name.toUtf8());
    return hash.result();
}
} // namespace

// 日期：2026-11-08；逐项读取属性后短锁记账，目录枚举和取消均在账本锁外；缺失、缩小和改名不退款。
QJsonObject StateDomain::accountUnknown(const PrivateStore &member) {
    if (!store_.maintenance() || !member.maintenance())
        throw Error(ExitCode::Permission, QStringLiteral("已有状态计量需要协调根与成员根独占维护"),
                    "state-accounting");
    const auto binding = root(member);
    if (binding.coordinatorRoot)
        throw Error(ExitCode::Config, QStringLiteral("协调控制区不能作为业务根计量"),
                    "state-accounting");
    const auto before = usage();
    qint64 files = 0, logical = 0, allocated = 0, charged = 0, controls = 0;
    qint64 directories = 0, links = 0, other = 0, hardLinks = 0;
    member.visitStorageEntries(
        [&](const NativeDirectoryEntry &entry) {
            // 日期：2026-11-08；子目录、链接及特殊项保留并报告未覆盖，不遍历、不打开正文、不自动删除。
            if (entry.kind != NativeDirectoryEntry::Kind::Regular) {
                if (entry.kind == NativeDirectoryEntry::Kind::Directory)
                    accumulate(directories, 1);
                else if (entry.kind == NativeDirectoryEntry::Kind::Link)
                    accumulate(links, 1);
                else
                    accumulate(other, 1);
                return;
            }
            const auto key = observationKey(binding, entry);
            auto charge = qMax(entry.bytes, entry.allocatedBytes);
            if (entry.name == "state-domain.bin") {
                // 日期：2026-11-08；已验证根标记的256字节已入Metadata，只将真实分配超出部分计入Unknown。
                if (entry.bytes != MarkerBytes)
                    throw Error(ExitCode::Integrity, QStringLiteral("根标记长度在计量期间变化"),
                                "state-accounting");
                charge -= MarkerBytes;
                accumulate(controls, MarkerBytes);
            }
            budget_->accountExisting(key, charge);
            accumulate(files, 1);
            accumulate(logical, entry.bytes);
            accumulate(allocated, entry.allocatedBytes);
            accumulate(charged, charge);
            if (entry.links > 1)
                accumulate(hardLinks, 1);
        },
        check_);
    verify(member, binding);
    const auto after = usage();
    if (after.totalCommitted < before.totalCommitted || after.totalReserved != before.totalReserved)
        throw Error(ExitCode::Integrity, QStringLiteral("已有状态计量不得减少或覆盖未决占用"),
                    "state-accounting");
    return {{"scope", "one-bound-root-direct-regular-files"},
            {"regularFiles", QString::number(files)},
            {"logicalBytes", QString::number(logical)},
            {"allocatedBytes", QString::number(allocated)},
            {"observedUnknownCharge", QString::number(charged)},
            {"alreadyChargedControlBytes", QString::number(controls)},
            {"newlyChargedBytes", QString::number(after.totalCommitted - before.totalCommitted)},
            {"directoriesUnaccounted", QString::number(directories)},
            {"linksUnaccounted", QString::number(links)},
            {"otherUnaccounted", QString::number(other)},
            {"hardLinkedNames", QString::number(hardLinks)},
            {"allDirectEntriesRegular", directories == 0 && links == 0 && other == 0},
            {"priorUnknownChargesRetained", true},
            {"businessOwnershipEstablished", false},
            {"automaticDeletionAllowed", false},
            {"wholeDomainAccounted", false},
            {"productionQuotaEnforced", false}};
}
} // namespace dukto
