#include "historybudget.h"
#include "error.h"
#include "privatestore.h"
#include "statedomain.h"
#include "statesession.h"
#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>
#include <QStringList>
#include <limits>

namespace dukto {
namespace {
constexpr qint64 Grain = 65536;

// 日期：2026-11-09；所有上界保持64位，回调拒绝不能变成整数回绕后的少量授信。
qint64 endOf(const SqliteFileEvent &event) {
    if (event.offset < 0 || event.bytes < 0 ||
        event.offset > std::numeric_limits<qint64>::max() - event.bytes)
        throw Error(ExitCode::Disk, QStringLiteral("历史写入范围溢出"), "history-budget");
    return event.offset + event.bytes;
}
} // namespace

// 日期：2026-11-09；成员根和中央会话持续持有共享资格，配置/独占回收不能穿过活动策略。
HistoryBudget::HistoryBudget(std::shared_ptr<PrivateStore> store, const QString &parent)
    : store_(std::move(store)) {
    auto session = StateSession::open(parent);
    rootKey_ = session->binding(*store_).key;
    budget_ = session->budget(*store_);
    for (const auto &base : {QString("history.sqlite"), QString("receipts.sqlite")}) {
        admit(base, QFileInfo(QDir(store_->directory()).filePath(base)).size());
        admit(base + ".origin.json", 65536);
        for (const auto &suffix : {"-journal", "-wal", "-shm"}) {
            const auto name = base + suffix;
            const QFileInfo existing(QDir(store_->directory()).filePath(name));
            if (existing.exists())
                admit(name, existing.size());
        }
    }
}

// 日期：2026-11-09；所有打开句柄须先由SQLite关闭，析构不按进程消失伪造释放证据。
HistoryBudget::~HistoryBudget() = default;

// 日期：2026-11-09；稳定角色只在已核验的私有根内使用，同一角色跨连接共用一份高水位。
QByteArray HistoryBudget::key(const QString &name) const {
    return QCryptographicHash::hash("dukto-history-envelope-v1" + rootKey_ + name.toUtf8(),
                                    QCryptographicHash::Sha256);
}

// 日期：2026-11-09；默认历史256MiB由持久域统一约束，分库不能各自拿到完整256MiB。
qint64 HistoryBudget::charge(qint64 bytes) {
    if (bytes < 0 || bytes > std::numeric_limits<qint64>::max() - Grain + 1)
        throw Error(ExitCode::Disk, QStringLiteral("历史额度范围无效"), "history-budget");
    return qMax(Grain, (bytes + Grain - 1) / Grain * Grain);
}

// 日期：2026-11-09；固定角色名称不含目录组件；说明原子替换按新旧两份各64KiB保守计量。
void HistoryBudget::admit(const QString &name, qint64 maximum) {
    const QString base = name.startsWith("history.sqlite") ? "history.sqlite" : "receipts.sqlite";
    const auto suffix = name.mid(base.size());
    const auto index = QStringList{"", "-journal", "-wal", "-shm", ".origin.json"}.indexOf(suffix);
    if (!name.startsWith(base) || index < 0)
        throw Error(ExitCode::Config, QStringLiteral("历史额度角色无效"), "history-budget");
    if (suffix == ".origin.json" && maximum > 65536)
        throw Error(ExitCode::Config, QStringLiteral("历史迁移说明超过固定上限"), "history-budget");
    store_->identity();
    const auto amount = name.endsWith(".origin.json") ? 2 * charge(maximum) : charge(maximum);
    auto &cached = admitted_[size_t(index + (base == "receipts.sqlite" ? 5 : 0))];
    if (cached >= amount)
        return;
    budget_->admitHighWater(key(name), StateBudget::Category::History, amount);
    cached = amount;
}

// 日期：2026-11-09；主库/旁路仅接受当前根的精确直接路径；SQLite临时库另走固定池。
QString HistoryBudget::role(const QByteArray &path) const {
    const auto file = QString::fromUtf8(path);
    const auto name = QFileInfo(file).fileName();
    if (QDir::cleanPath(file) != QDir(store_->directory()).filePath(name))
        throw Error(ExitCode::Permission, QStringLiteral("历史SQLite路径不属于当前根"),
                    "history-budget");
    for (const auto &base : {QString("history.sqlite"), QString("receipts.sqlite")})
        if (name == base || name == base + "-journal" || name == base + "-wal" ||
            name == base + "-shm")
            return name;
    throw Error(ExitCode::Permission, QStringLiteral("历史SQLite旁路名称无效"), "history-budget");
}

// 日期：2026-11-09；没有登记的句柄不获得隐式无限额度，重复open同一编号亦不能覆盖旧临时预留。
HistoryBudget::Entry &HistoryBudget::entry(quint64 file) {
    for (auto &item : entries_)
        if (item.file == file && file)
            return item;
    throw Error(ExitCode::Integrity, QStringLiteral("历史SQLite句柄未登记"), "history-budget");
}

// 日期：2026-11-09；32份全域临时预留保持固定账本规模，遗留占用明确保留而非按PID清零。
StateBudget::Record HistoryBudget::temporary() {
    for (int index = 0; index < 32; ++index) {
        const auto object = key("temporary-" + QString::number(index));
        try {
            StateBudget::Record record;
            try {
                record = budget_->lookup(object);
            } catch (const Error &error) {
                if (error.stage != "budget-missing")
                    throw;
                record = budget_->enroll(object, StateBudget::Category::History, 0);
            }
            if (record.category != StateBudget::Category::History)
                throw Error(ExitCode::Integrity, QStringLiteral("历史临时预算类别不一致"),
                            "history-budget");
            if (!record.pending && record.committed == 0)
                return budget_->reserve(record, Grain);
        } catch (const Error &error) {
            if (error.stage != "budget-stale" && error.stage != "budget-pending")
                throw;
        }
    }
    throw Error(ExitCode::Disk, QStringLiteral("历史临时额度槽已占用，请关闭程序并核对遗留预留"),
                "history-budget");
}

// 日期：2026-11-09；命名对象保存永久保守包络，匿名对象扩展同一未决操作；不持预算锁执行SQLite。
void HistoryBudget::grow(Entry &item, qint64 bytes, bool sharedMemory) {
    if (item.anonymous) {
        if (sharedMemory)
            throw Error(ExitCode::Permission, QStringLiteral("匿名历史库不允许WAL共享区"),
                        "history-budget");
        const auto maximum = charge(bytes);
        if (maximum > item.temporary.committed + item.temporary.reserved)
            item.temporary = budget_->extend(item.temporary, maximum);
    } else {
        admit(item.name + (sharedMemory ? "-shm" : ""), bytes);
    }
}

// 日期：2026-11-09；C回调边界保留SQLite错误码；额度不足不会调用对应原生写入。
int HistoryBudget::before(const SqliteFileEvent &event) noexcept {
    try {
        using Action = SqliteFileEvent::Action;
        if (event.action == Action::Delete) {
            role(event.name);
            return SQLITE_OK;
        }
        if (event.action == Action::Close || event.action == Action::UnmapSharedMemory)
            return SQLITE_OK;
        if (event.action == Action::Open) {
            if (failedObservation_)
                return SQLITE_FULL;
            Entry *empty = nullptr;
            for (auto &item : entries_) {
                if (item.file == event.file)
                    return SQLITE_CANTOPEN;
                if (!item.file && !empty)
                    empty = &item;
            }
            if (!empty || !event.file)
                return SQLITE_FULL;
            Entry next;
            next.file = event.file;
            next.anonymous = event.name.isEmpty();
            next.deleteOnClose = (event.flags & SQLITE_OPEN_DELETEONCLOSE) != 0;
            if (next.anonymous) {
                if (!next.deleteOnClose)
                    return SQLITE_CANTOPEN;
                next.temporary = temporary();
            } else {
                next.name = role(event.name);
                const auto existing = QFileInfo(QString::fromUtf8(event.name)).size();
                admit(next.name, existing);
            }
            *empty = std::move(next);
            return SQLITE_OK;
        }
        auto &item = entry(event.file);
        if (failedObservation_) {
            const auto &file = event.observation.file;
            const bool shrinking = event.action == Action::Truncate && file.kind == 1 &&
                                   event.bytes <= file.logicalBytes;
            const bool rollbackWrite = event.action == Action::Write && file.kind == 1 &&
                                       endOf(event) <= file.logicalBytes;
            if (!shrinking && !rollbackWrite)
                return SQLITE_FULL;
        }
        if (event.action == Action::MapSharedMemory) {
            if (event.extend)
                grow(item, event.bytes, true);
        } else if (event.action == Action::Write || event.action == Action::Truncate ||
                   event.action == Action::SizeHint) {
            grow(item, endOf(event));
        }
        return SQLITE_OK;
    } catch (const std::bad_alloc &) {
        return SQLITE_NOMEM;
    } catch (...) {
        return SQLITE_FULL;
    }
}

// 日期：2026-11-09；失败写入也观察实际占用；关闭仅对成功delete-on-close匿名对象归还额度。
void HistoryBudget::after(const SqliteFileEvent &event, int result) noexcept {
    if (event.action == SqliteFileEvent::Action::Delete)
        return;
    try {
        auto &item = entry(event.file);
        if (event.action == SqliteFileEvent::Action::Close) {
            if (item.anonymous && item.deleteOnClose && result == SQLITE_OK)
                budget_->settle(item.temporary, 0);
            item = {};
            return;
        }
        const auto &observed = event.observation;
        if (result == SQLITE_OK &&
            (observed.fileResult != SQLITE_OK || (!item.anonymous && observed.file.kind != 1)))
            failedObservation_ = true;
        if (observed.fileResult == SQLITE_OK && observed.file.kind == 1)
            grow(item, qMax(observed.file.logicalBytes, observed.file.allocatedBytes));
        if (observed.sharedMemoryResult == SQLITE_OK && observed.sharedMemory.kind == 1)
            grow(item,
                 qMax(observed.sharedMemory.logicalBytes, observed.sharedMemory.allocatedBytes),
                 true);
        if (event.action == SqliteFileEvent::Action::Open && result != SQLITE_OK)
            item = {};
    } catch (...) {
        failedObservation_ = true;
    }
}

// 日期：2026-11-09；观察失败不能解释为零占用，调用方保留历史原件并停止该连接初始化。
void HistoryBudget::check() const {
    if (failedObservation_)
        throw Error(ExitCode::Disk, QStringLiteral("历史分配量无法纳入额度，原件与预留已保留"),
                    "history-budget");
}
} // namespace dukto
