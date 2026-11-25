#include "buffercredit.h"
#include "error.h"
#include <mutex>

namespace dukto {
namespace {
std::mutex mutex;
constexpr qint64 Limit = 128 * 1024 * 1024;
constexpr qint64 Reserved = 8 * 1024 * 1024;
qint64 used = 0;
qint64 peak = 0;
qint64 dataUsed = 0;
qint64 dataPeak = 0;
} // namespace

// 日期：2026-11-05；同时检查总额与数据子额度；先进入的控制连接不挤占数据专属的计数。
BufferCredit::BufferCredit(qint64 bytes, bool data) : bytes_(bytes), data_(data) {
    std::lock_guard<std::mutex> lock(mutex);
    if (bytes <= 0 || bytes > Limit || used > Limit - bytes ||
        (data && (bytes > Limit - Reserved || dataUsed > Limit - Reserved - bytes)))
        throw Error(ExitCode::Permission, QStringLiteral("传输缓冲授信繁忙，请降低并发或稍后重试"),
                    "budget");
    used += bytes;
    if (data_)
        dataUsed += bytes;
    peak = qMax(peak, used);
    dataPeak = qMax(dataPeak, dataUsed);
}

// 日期：2026-11-05；总额与数据分类在同一锁内归还，不允许复制或转类后双重归还。
BufferCredit::~BufferCredit() {
    std::lock_guard<std::mutex> lock(mutex);
    used -= bytes_;
    if (data_)
        dataUsed -= bytes_;
    Q_ASSERT(used >= 0 && dataUsed >= 0 && dataUsed <= used);
}

// 日期：2026-11-05；转换不增加总额；数据额度不足时不修改任何计数或本令牌的分类。
void BufferCredit::classifyAsData() {
    std::lock_guard<std::mutex> lock(mutex);
    if (data_)
        return;
    if (bytes_ > Limit - Reserved || dataUsed > Limit - Reserved - bytes_)
        throw Error(ExitCode::Permission, QStringLiteral("数据缓冲授信繁忙，控制保留额不能转用"),
                    "budget");
    dataUsed += bytes_;
    dataPeak = qMax(dataPeak, dataUsed);
    data_ = true;
}

// 日期：2026-11-05；总额、数据与控制授信分列，64 位值统一十进制字符串且不暴露业务数据。
QJsonObject BufferCredit::usage() {
    std::lock_guard<std::mutex> lock(mutex);
    return {
        {"limit", QString::number(Limit)},       {"reserved", QString::number(Reserved)},
        {"used", QString::number(used)},         {"peak", QString::number(peak)},
        {"dataUsed", QString::number(dataUsed)}, {"controlUsed", QString::number(used - dataUsed)},
        {"dataPeak", QString::number(dataPeak)}};
}
} // namespace dukto
