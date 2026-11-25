#pragma once

#include "sqlitevfs.h"
#include "statebudget.h"
#include <array>
#include <atomic>
#include <memory>

namespace dukto {
class PrivateStore;
class HistoryBudget final : public SqliteFilePolicy {
  public:
    // 日期：2026-11-09；两个历史库共用已有域的History额度；名称高水位在真实写入前持久授信。
    HistoryBudget(std::shared_ptr<PrivateStore> store, const QString &parent);
    // 日期：2026-11-09；关闭失败或进程退出不退款，未决临时文件须后续独占维护核对。
    ~HistoryBudget() override;
    // 日期：2026-11-09；迁移正文与原子说明先按整个新对象授信，原件和并存临时对象均保守保留。
    void admit(const QString &name, qint64 maximum);
    // 日期：2026-11-09；打开后观察超出授信时禁止继续初始化，但不删除现有对象。
    void check() const;
    // 日期：2026-11-09；每个VFS独立持有句柄编号和预留，但同一历史状态共享不可清除的观察错误。
    std::shared_ptr<HistoryBudget> connection() const;
    // 日期：2026-11-09；固定64个连接内句柄，匿名临时文件从全域固定池获得持久预留。
    int before(const SqliteFileEvent &event) noexcept override;
    // 日期：2026-11-09；原生操作后补充高水位；只有已成功删除的匿名临时文件才归还其预留。
    void after(const SqliteFileEvent &event, int result) noexcept override;

  private:
    // 日期：2026-11-09；状态对象与派生连接共享错误锁存；新策略不能让既有观察错误变为健康。
    HistoryBudget(std::shared_ptr<PrivateStore> store, const QString &parent,
                  std::shared_ptr<std::atomic_bool> failedObservation);
    struct Entry {
        quint64 file = 0;
        QString name;
        StateBudget::Record temporary;
        bool anonymous = false;
        bool deleteOnClose = false;
    };
    // 日期：2026-11-09；只接受固定两库及各自journal/WAL/shm，不以任意路径扩大历史访问范围。
    QString role(const QByteArray &path) const;
    // 日期：2026-11-09；根登记代数与固定角色生成键，名称高水位不因inode复用或删除重建而减少。
    QByteArray key(const QString &name) const;
    // 日期：2026-11-09；64KiB向上取整的逻辑额度额外覆盖已观察分配量，溢出与负数拒绝。
    static qint64 charge(qint64 bytes);
    // 日期：2026-11-09；当前事件只能匹配本连接已成功登记的固定句柄槽。
    Entry &entry(quint64 file);
    // 日期：2026-11-09；临时池先持久登记再独占预留，冲突或遗留未决槽不复用。
    StateBudget::Record temporary();
    // 日期：2026-11-09；映射需求按SQLite原生共享节点范围计算，旁路额度与主库分别合计。
    void grow(Entry &entry, qint64 bytes, bool sharedMemory = false);
    std::shared_ptr<PrivateStore> store_;
    QString parent_;
    std::shared_ptr<StateBudget> budget_;
    QByteArray rootKey_;
    std::array<Entry, 64> entries_{};
    std::array<qint64, 10> admitted_{};
    std::shared_ptr<std::atomic_bool> failedObservation_;
};
} // namespace dukto
