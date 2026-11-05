#pragma once

#include "files.h"
#include "privatestore.h"
#include "sqlitecache.h"
#include <QJsonObject>
#include <QLockFile>
#include <QSqlDatabase>
#include <QUuid>
#include <memory>

namespace dukto {
struct TransferTask {
    QUuid id;
    QUuid owner;
    QUuid request;
    QString direction;
    QString share;
    QString relative;
    QString root;
    QString state;
    QString desired;
    quint64 revision = 1;
    QByteArray manifest;
    qint64 total = 0;
    qint64 entries = 0;
    qint64 processed = 0;
    int error = 0;
    QString message;
    ConflictPolicy conflict = ConflictPolicy::Rename;
    // 日期：2026-11-04；公开结果不含本地根、凭据或源绝对路径，64 位值使用字符串。
    QJsonObject publicInfo() const;
};

class TaskLease final {
  public:
    // 日期：2026-11-04；释放跨进程任务执行所有权，磁盘任务和检查点仍保留。
    ~TaskLease();
    TaskLease(const TaskLease &) = delete;
    TaskLease &operator=(const TaskLease &) = delete;

  private:
    friend class TaskStore;
    // 日期：2026-11-04；只有已核对主体的 TaskStore 可以建立任务执行锁。
    TaskLease(QUuid task, QUuid owner, const QString &path);
    QUuid task_;
    QUuid owner_;
    QString path_;
    QLockFile lock_;
};

class TaskStore final {
  public:
    // 日期：2026-11-04；在受保护根中打开有界持久任务库，各线程使用独立 SQLite 连接。
    explicit TaskStore(PrivateStore &store, bool control = true);
    // 日期：2026-11-04；先关闭本线程连接再移除 Qt 注册项，不隐式删除未完成任务。
    ~TaskStore();
    TaskStore(const TaskStore &) = delete;
    TaskStore &operator=(const TaskStore &) = delete;
    // 日期：2026-11-05；请求摘要绑定冲突策略；默认保留旧规范值，相同请求更改策略明确拒绝。
    TransferTask create(const QUuid &owner, const QUuid &request, const QString &direction,
                        const QString &share, const QString &relative, const QString &root,
                        const QByteArray &uploadManifest = {},
                        ConflictPolicy conflict = ConflictPolicy::Rename);
    // 日期：2026-11-04；任务查询强制所属主体，不能通过猜测其他任务 UUID 取得状态或路径。
    TransferTask task(const QUuid &owner, const QUuid &id) const;
    // 日期：2026-11-04；按主体和稳定插入序号分页，双重限制 100 条及控制报文字节，不加载全部任务。
    QJsonObject page(const QUuid &owner, quint64 after = 0) const;
    // 日期：2026-11-04；只有一个线程/进程持有执行所有权，重复连接不能同时写同一任务。
    std::unique_ptr<TaskLease> acquire(const QUuid &owner, const QUuid &id) const;
    // 日期：2026-11-04；控制连接非阻塞探测执行租约，活动任务返回空值而非抢占其写入者。
    std::unique_ptr<TaskLease> tryAcquire(const QUuid &owner, const QUuid &id) const;
    // 日期：2026-11-04；强清单完全冻结后绑定总计；重复确认返回同一绑定，不重新创建任务。
    TransferTask bindManifest(const TaskLease &lease, const QJsonObject &summary);
    // 日期：2026-11-04；状态/进度更新按修订号比较交换，完成只允许从提交阶段并且字节完整。
    TransferTask advance(const TaskLease &lease, quint64 revision, const QString &state,
                         qint64 processed, int error = 0, const QString &message = QString());
    // 日期：2026-11-04；外部控制只持久请求暂停/取消；工作者到安全点后才能确认实际状态。
    TransferTask requestStop(const QUuid &owner, const QUuid &id, bool pause);

  private:
    // 日期：2026-11-04；执行方必须持有本任务/主体的跨进程所有权，不以连接序号代替任务锁。
    void verifyLease(const TaskLease &lease) const;
    // 日期：2026-11-04；数据库事务内更新一条已核对记录；受影响行必须恰好一条。
    void save(const TransferTask &task) const;
    PrivateStore &store_;
    QString connection_;
    SqliteCacheCredit cacheCredit_;
    QSqlDatabase database_;
};
} // namespace dukto
