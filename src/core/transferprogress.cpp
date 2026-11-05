#include "transferprogress.h"
#include "error.h"
#include <cmath>
#include <limits>

namespace dukto {
// 日期：2026-11-05；进度扩展须显式协商；接收方不会同时接受对端自报的字节数。
TransferProgress::TransferProgress(next::SecureChannel &channel, quint64 correlation,
                                   const QUuid &task, const QByteArray &manifest, qint64 total,
                                   bool receiver, bool enabled,
                                   std::function<void(const QJsonObject &)> update)
    : channel_(channel), correlation_(correlation), task_(task), manifest_(manifest), total_(total),
      receiver_(receiver), enabled_(enabled), update_(std::move(update)) {
    if (!correlation || task.isNull() || manifest.size() != 32 || total < 0)
        throw Error(ExitCode::Config, QStringLiteral("字节进度绑定无效"), "progress");
    throttle_.start();
    sample_.start();
    if (enabled_ && !receiver_)
        channel_.observeProgress([this](const next::Frame &frame) {
            // 日期：2026-11-05；回调在同一控制线程内执行，生命周期由当前对象限定。
            accept(frame);
        });
}

// 日期：2026-11-05；异常退栈也清除回调，不在析构阶段发送网络消息。
TransferProgress::~TransferProgress() {
    if (enabled_ && !receiver_)
        channel_.observeProgress({});
}

// 日期：2026-11-05；每个已重验文件只加入一次；所有加法先检查剩余量避免溢出。
void TransferProgress::restored(qint64 bytes) {
    if (!receiver_ || bytes < 0 || bytes > total_ - bytes_)
        throw Error(ExitCode::Integrity, QStringLiteral("恢复进度超出清单"), "progress");
    bytes_ += bytes;
    confirmed_ += bytes;
    restored_ += bytes;
    publish();
}

// 日期：2026-11-05；块完成时确认增量可大于最后片段，但不能超过已写入总量。
void TransferProgress::written(qint64 bytes, qint64 confirmed) {
    if (!receiver_ || bytes <= 0 || bytes > total_ - bytes_ || confirmed < 0 ||
        confirmed > bytes_ + bytes - confirmed_)
        throw Error(ExitCode::Integrity, QStringLiteral("写入进度超出接收范围"), "progress");
    bytes_ += bytes;
    confirmed_ += confirmed;
    publish();
}

// 日期：2026-11-05；最多四次每秒写控制帧，固定尺寸且无待发送快照队列。
void TransferProgress::publish(bool force) {
    if (!receiver_ || (!force && throttle_.elapsed() < 250))
        return;
    if (enabled_)
        channel_.write(next::Type::Progress, correlation_,
                       {{"taskId", task_.toString(QUuid::WithoutBraces)},
                        {"manifest", QString::fromLatin1(manifest_.toHex())},
                        {"bytes", QString::number(bytes_)},
                        {"confirmed", QString::number(confirmed_)},
                        {"restored", QString::number(restored_)},
                        {"total", QString::number(total_)}});
    notify();
    throttle_.restart();
}

// 日期：2026-11-05；返回值不会包含只在内存或尚未同步的数据。
qint64 TransferProgress::confirmed() const {
    return confirmed_;
}

// 日期：2026-11-05；64 位计数使用规范十进制字符串，远端不能通过浮点舍入绕过边界。
void TransferProgress::accept(const next::Frame &frame) {
    const auto value = next::parseControl(frame.payload);
    const auto bytes = static_cast<qint64>(next::decimal(value["bytes"], total_));
    const auto confirmed = static_cast<qint64>(next::decimal(value["confirmed"], bytes));
    const auto restored = static_cast<qint64>(next::decimal(value["restored"], confirmed));
    if (frame.header.correlation != correlation_ || frame.header.type != next::Type::Progress ||
        value.size() != 6 || value["taskId"] != task_.toString(QUuid::WithoutBraces) ||
        value["manifest"] != QString::fromLatin1(manifest_.toHex()) ||
        value["total"] != QString::number(total_) || bytes < bytes_ || confirmed < confirmed_ ||
        restored < restored_ || bytes - restored < bytes_ - restored_)
        throw Error(ExitCode::Integrity, QStringLiteral("远端进度身份或计数无效"), "progress");
    bytes_ = bytes;
    confirmed_ = confirmed;
    restored_ = restored;
    notify();
}

// 日期：2026-11-05；滑动速率仅反映本次实际传输，全部数据到达仍等待摘要、命名及最终确认。
void TransferProgress::notify() {
    const qint64 network = bytes_ - restored_;
    const qint64 elapsed = sample_.elapsed();
    if (elapsed >= 250) {
        const double current = (network - previousNetwork_) * 1000.0 / elapsed;
        speed_ = speed_ == 0 ? current : speed_ * 0.5 + current * 0.5;
        previousNetwork_ = network;
        sample_.restart();
    }
    if (update_)
        update_({{"event", "byte-progress"},
                 {"taskId", task_.toString(QUuid::WithoutBraces)},
                 {"state", "transferring"},
                 {"bytes", QString::number(confirmed_)},
                 {"receivedBytes", QString::number(bytes_)},
                 {"restoredBytes", QString::number(restored_)},
                 {"total", QString::number(total_)},
                 {"bytesPerSecond", speed_},
                 {"etaSeconds", speed_ > 0 ? QJsonValue(std::ceil((total_ - bytes_) / speed_))
                                           : QJsonValue(QJsonValue::Null)}});
}
} // namespace dukto
