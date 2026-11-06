#include "transferaccounting.h"
#include "error.h"
#include "protocol.h"

namespace dukto {
// 日期：2026-11-06；上限与冻结清单一致，旧进度可绑定非零字节而不启用逐项处置。
TransferAccounting::TransferAccounting(qint64 total, quint64 entries)
    : total_(total), entries_(entries) {
    if (total < 0 || entries > 10000000)
        throw Error(ExitCode::Config, QStringLiteral("传输计量绑定无效"), "progress");
}

// 日期：2026-11-06；先在固定大小候选中验证，任何拒绝均不能改变已接受的进度。
void TransferAccounting::restored(qint64 bytes) {
    if (bytes < 0 || bytes > total_ - bytes_)
        throw Error(ExitCode::Integrity, QStringLiteral("恢复进度超出清单"), "progress");
    auto candidate = *this;
    candidate.bytes_ += bytes;
    candidate.confirmed_ += bytes;
    candidate.restored_ += bytes;
    candidate.validate();
    *this = candidate;
}

// 日期：2026-11-06；同步增量允许包含先前片段，但不能超过当前累计收到的真实字节。
void TransferAccounting::written(qint64 bytes, qint64 confirmed) {
    if (bytes <= 0 || bytes > total_ - bytes_ || confirmed < 0 ||
        confirmed > bytes_ + bytes - confirmed_)
        throw Error(ExitCode::Integrity, QStringLiteral("写入进度超出接收范围"), "progress");
    auto candidate = *this;
    candidate.bytes_ += bytes;
    candidate.confirmed_ += confirmed;
    candidate.validate();
    *this = candidate;
}

// 日期：2026-11-06；每个条目只归结一次；空文件及目录也计数，不能借零字节重复完成。
void TransferAccounting::settled(const StrongEntry &entry, bool skipped, bool receivedBody) {
    const auto count = copiedFiles_ + copiedDirectories_ + skippedFiles_ + skippedDirectories_;
    if (!entries_ || count >= entries_ || entry.id != count + 1 || entry.bytes < 0 ||
        entry.bytes > total_ - copied_ - skipped_ ||
        (entry.directory && (entry.bytes || receivedBody)) ||
        (!entry.directory && !skipped && !receivedBody) ||
        (receivedBody && entry.bytes > confirmed_ - copied_ - discarded_))
        throw Error(ExitCode::Integrity, QStringLiteral("条目处置与接收计量不同"), "progress");
    auto candidate = *this;
    if (skipped) {
        candidate.skipped_ += entry.bytes;
        if (receivedBody)
            candidate.discarded_ += entry.bytes;
        if (entry.directory)
            ++candidate.skippedDirectories_;
        else
            ++candidate.skippedFiles_;
    } else {
        candidate.copied_ += entry.bytes;
        if (entry.directory)
            ++candidate.copiedDirectories_;
        else
            ++candidate.copiedFiles_;
    }
    candidate.validate();
    *this = candidate;
}

// 日期：2026-11-06；每个字段有独立上限，差值约束禁止把先前网络字节或跳过结果事后改类。
void TransferAccounting::accept(const QJsonObject &value) {
    if (value.size() != 10)
        throw Error(ExitCode::Integrity, QStringLiteral("传输计量字段不完整"), "progress");
    TransferAccounting candidate(total_, entries_);
    candidate.bytes_ = static_cast<qint64>(next::decimal(value["bytes"], total_));
    candidate.confirmed_ = static_cast<qint64>(next::decimal(value["confirmed"], total_));
    candidate.restored_ = static_cast<qint64>(next::decimal(value["restored"], total_));
    candidate.copied_ = static_cast<qint64>(next::decimal(value["copiedBytes"], total_));
    candidate.skipped_ = static_cast<qint64>(next::decimal(value["skippedBytes"], total_));
    candidate.discarded_ = static_cast<qint64>(next::decimal(value["discardedBytes"], total_));
    candidate.copiedFiles_ = next::decimal(value["copiedFiles"], entries_);
    candidate.copiedDirectories_ = next::decimal(value["copiedDirectories"], entries_);
    candidate.skippedFiles_ = next::decimal(value["skippedFiles"], entries_);
    candidate.skippedDirectories_ = next::decimal(value["skippedDirectories"], entries_);
    candidate.validate();
    if (candidate.bytes_ < bytes_ || candidate.confirmed_ < confirmed_ ||
        candidate.restored_ < restored_ || candidate.copied_ < copied_ ||
        candidate.skipped_ < skipped_ || candidate.discarded_ < discarded_ ||
        candidate.copiedFiles_ < copiedFiles_ ||
        candidate.copiedDirectories_ < copiedDirectories_ ||
        candidate.skippedFiles_ < skippedFiles_ ||
        candidate.skippedDirectories_ < skippedDirectories_ ||
        candidate.bytes_ - bytes_ < candidate.restored_ - restored_ ||
        candidate.confirmed_ - confirmed_ < candidate.restored_ - restored_ ||
        candidate.discarded_ - discarded_ > candidate.skipped_ - skipped_ ||
        (candidate.copied_ > copied_ && candidate.copiedFiles_ == copiedFiles_) ||
        ((candidate.skipped_ > skipped_ || candidate.discarded_ > discarded_) &&
         candidate.skippedFiles_ == skippedFiles_) ||
        candidate.handled() < handled())
        throw Error(ExitCode::Integrity, QStringLiteral("远端传输计量回退或重分类"), "progress");
    *this = candidate;
}

// 日期：2026-11-06；64位值始终编码为规范字符串，避免跨语言JSON浮点精度损失。
QJsonObject TransferAccounting::snapshot() const {
    return {{"bytes", QString::number(bytes_)},
            {"confirmed", QString::number(confirmed_)},
            {"restored", QString::number(restored_)},
            {"copiedBytes", QString::number(copied_)},
            {"skippedBytes", QString::number(skipped_)},
            {"discardedBytes", QString::number(discarded_)},
            {"copiedFiles", QString::number(copiedFiles_)},
            {"copiedDirectories", QString::number(copiedDirectories_)},
            {"skippedFiles", QString::number(skippedFiles_)},
            {"skippedDirectories", QString::number(skippedDirectories_)}};
}

// 日期：2026-11-06；先相减后相加，validate保证结果非负且不超过总字节。
qint64 TransferAccounting::handled() const {
    return confirmed_ - discarded_ + skipped_;
}

// 日期：2026-11-06；仅返回真实收到的字节，不包含准备阶段跳过的数据。
qint64 TransferAccounting::received() const {
    return bytes_;
}

// 日期：2026-11-06；该值可大于实际复制字节，调用者不能据此推断最终文件处置。
qint64 TransferAccounting::confirmed() const {
    return confirmed_;
}

// 日期：2026-11-06；恢复累计只来自本轮验证，不直接采信上轮持久进度。
qint64 TransferAccounting::restoredBytes() const {
    return restored_;
}

// 日期：2026-11-06；已收到但未同步的片段同样从网络剩余量扣除，跳过不产生虚假速率。
qint64 TransferAccounting::remaining() const {
    return total_ - skipped_ - (bytes_ - discarded_);
}

// 日期：2026-11-06；原始计数单调且守恒；最后一项结束时必须准确覆盖全部字节及处置。
void TransferAccounting::validate() const {
    const auto count = copiedFiles_ + copiedDirectories_ + skippedFiles_ + skippedDirectories_;
    if (restored_ > confirmed_ || confirmed_ > bytes_ || bytes_ > total_ ||
        discarded_ > confirmed_ || discarded_ > skipped_ || skipped_ > total_ ||
        copied_ > confirmed_ - discarded_ || bytes_ - discarded_ > total_ - skipped_ ||
        count > entries_ || (!copiedFiles_ && copied_) ||
        (!skippedFiles_ && (skipped_ || discarded_)) ||
        (entries_ && count == entries_ &&
         (bytes_ != confirmed_ || copied_ != confirmed_ - discarded_ ||
          copied_ != total_ - skipped_)))
        throw Error(ExitCode::Integrity, QStringLiteral("传输计量不满足字节或条目守恒"),
                    "progress");
}
} // namespace dukto
