#include "transferprogress.h"
#include "error.h"
#include <cmath>

namespace dukto {
namespace {
const QStringList DispositionFields{"copiedBytes",       "skippedBytes",      "discardedBytes",
                                    "copiedFiles",       "copiedDirectories", "skippedFiles",
                                    "skippedDirectories"};
} // namespace

// 日期：2026-11-06；扩展计量必须显式启用；旧端仍只交换原六字段，不推断其支持跳过。
TransferProgress::TransferProgress(next::SecureChannel &channel, quint64 correlation,
                                   const QUuid &task, const QByteArray &manifest, qint64 total,
                                   bool receiver, bool enabled,
                                   std::function<void(const QJsonObject &)> update,
                                   bool dispositions, quint64 entries)
    : channel_(channel), correlation_(correlation), task_(task), manifest_(manifest), total_(total),
      receiver_(receiver), enabled_(enabled), update_(std::move(update)),
      dispositions_(dispositions), entries_(entries),
      accounting_(total, dispositions ? entries : 0) {
    if (!correlation || task.isNull() || manifest.size() != 32 || total < 0 ||
        (dispositions && (!enabled || (!entries && total))))
        throw Error(ExitCode::Config, QStringLiteral("字节进度绑定无效"), "progress");
    throttle_.start();
    sample_.start();
    if (enabled_ && !receiver_)
        channel_.observeProgress([this](const next::Frame &frame) {
            // 日期：2026-11-06；回调在同一控制线程执行，生命周期由当前对象限定。
            accept(frame);
        });
}

// 日期：2026-11-05；异常退栈也清除回调，不在析构阶段发送网络消息。
TransferProgress::~TransferProgress() {
    if (enabled_ && !receiver_)
        channel_.observeProgress({});
}

// 日期：2026-11-06；只允许接收端加入本轮重验的恢复数据，计量失败不发布快照。
void TransferProgress::restored(qint64 bytes) {
    if (!receiver_)
        throw Error(ExitCode::Integrity, QStringLiteral("发送端不能自行增加接收进度"), "progress");
    accounting_.restored(bytes);
    publish();
}

// 日期：2026-11-06；真实写入和同步增量统一验证，不将跳过文件大小伪装成网络流量。
void TransferProgress::written(qint64 bytes, qint64 confirmed) {
    if (!receiver_)
        throw Error(ExitCode::Integrity, QStringLiteral("发送端不能自行增加写入进度"), "progress");
    accounting_.written(bytes, confirmed);
    publish();
}

// 日期：2026-11-06；旧模式只能处理复制；显式模式严格按冻结条目顺序完成固定大小计数。
void TransferProgress::settled(const StrongEntry &entry, bool skipped, bool receivedBody) {
    if (!receiver_ || (skipped && !dispositions_))
        throw Error(ExitCode::Integrity, QStringLiteral("当前进度未启用接收处置计量"), "progress");
    if (dispositions_) {
        accounting_.settled(entry, skipped, receivedBody);
        publish();
    }
}

// 日期：2026-11-06；每秒最多四条固定尺寸帧；最终条目另强制发布，不能积累快照队列。
void TransferProgress::publish(bool force) {
    if (!receiver_ || (!force && throttle_.elapsed() < 250))
        return;
    if (enabled_) {
        auto value = accounting_.snapshot();
        if (!dispositions_)
            for (const auto &key : DispositionFields)
                value.remove(key);
        value["taskId"] = task_.toString(QUuid::WithoutBraces);
        value["manifest"] = QString::fromLatin1(manifest_.toHex());
        value["total"] = QString::number(total_);
        channel_.write(next::Type::Progress, correlation_, value);
    }
    notify();
    throttle_.restart();
}

// 日期：2026-11-06；逻辑处理量包含已确认跳过，实际同步量在扩展事件中另列confirmedBytes。
qint64 TransferProgress::confirmed() const {
    return accounting_.handled();
}

// 日期：2026-11-06；固定快照只反映本轮真实接收或经校验远端进度，不根据最终成功回包补造。
QJsonObject TransferProgress::snapshot() const {
    return accounting_.snapshot();
}

// 日期：2026-11-06；先核对身份及协议字段数，再原子接受单调计数；拒绝缺字段和未协商扩展。
void TransferProgress::accept(const next::Frame &frame) {
    auto value = next::parseControl(frame.payload);
    if (frame.header.correlation != correlation_ || frame.header.type != next::Type::Progress ||
        value.size() != (dispositions_ ? 13 : 6) ||
        value["taskId"] != task_.toString(QUuid::WithoutBraces) ||
        value["manifest"] != QString::fromLatin1(manifest_.toHex()) ||
        value["total"] != QString::number(total_))
        throw Error(ExitCode::Integrity, QStringLiteral("远端进度身份或字段无效"), "progress");
    value.remove("taskId");
    value.remove("manifest");
    value.remove("total");
    if (!dispositions_)
        for (const auto &key : DispositionFields)
            value[key] = "0";
    accounting_.accept(value);
    notify();
}

// 日期：2026-11-06；网络速率排除恢复重读与准备跳过，ETA按实际尚未到达的逻辑字节计算。
void TransferProgress::notify() {
    const qint64 network = accounting_.received() - accounting_.restoredBytes();
    const qint64 elapsed = sample_.elapsed();
    if (elapsed >= 250) {
        const double current = (network - previousNetwork_) * 1000.0 / elapsed;
        speed_ = speed_ == 0 ? current : speed_ * 0.5 + current * 0.5;
        previousNetwork_ = network;
        sample_.restart();
    }
    if (update_) {
        QJsonObject value{
            {"event", "byte-progress"},
            {"taskId", task_.toString(QUuid::WithoutBraces)},
            {"state", "transferring"},
            {"bytes", QString::number(accounting_.handled())},
            {"receivedBytes", QString::number(accounting_.received())},
            {"restoredBytes", QString::number(accounting_.restoredBytes())},
            {"total", QString::number(total_)},
            {"bytesPerSecond", speed_},
            {"etaSeconds", speed_ > 0 ? QJsonValue(std::ceil(accounting_.remaining() / speed_))
                                      : QJsonValue(QJsonValue::Null)}};
        if (dispositions_) {
            const auto counters = accounting_.snapshot();
            for (const auto &key : DispositionFields)
                value[key] = counters[key];
            value["handledBytes"] = QString::number(accounting_.handled());
            value["confirmedBytes"] = QString::number(accounting_.confirmed());
            value["entries"] = QString::number(entries_);
        }
        update_(value);
    }
}
} // namespace dukto
