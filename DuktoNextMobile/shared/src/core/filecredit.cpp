#include "filecredit.h"
#include "error.h"
#include <mutex>

namespace dukto {
namespace {
std::mutex mutex;
constexpr int Limit = 32;
int used = 0;
int peak = 0;
} // namespace

// 日期：2026-11-06；所有扫描和收发路径共享同一进程计数；拒绝时不增加计数或打开文件。
DataFileCredit::DataFileCredit() {
    std::lock_guard<std::mutex> lock(mutex);
    if (used >= Limit)
        throw Error(ExitCode::Permission, QStringLiteral("传输数据文件额度繁忙，请稍后重试"),
                    "file-budget");
    ++used;
    peak = qMax(peak, used);
}

// 日期：2026-11-06；令牌不能复制或移动，析构只归还一次，不影响其他活动文件。
DataFileCredit::~DataFileCredit() {
    std::lock_guard<std::mutex> lock(mutex);
    --used;
    Q_ASSERT(used >= 0 && used <= Limit);
}

// 日期：2026-11-06；授信可能覆盖文件关闭后的短暂清理期，因此是实际数据文件数的保守上界。
QJsonObject DataFileCredit::usage() {
    std::lock_guard<std::mutex> lock(mutex);
    return {{"limit", Limit}, {"used", used}, {"peak", peak}};
}
} // namespace dukto
