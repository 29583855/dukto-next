#pragma once

#include "sqlitecache.h"
#include <QJsonArray>
#include <QLockFile>
#include <QSqlDatabase>
#include <memory>

namespace dukto {
class HistoryState;
class Catalog final {
  public:
    // 日期：2026-11-04；任务明细存于单个有界 SQLite 数据库，各线程独立连接。
    explicit Catalog(const QString &path);
    // 日期：2026-11-04；析构回滚未提交小批次，释放当前线程数据库连接。
    ~Catalog();
    // 日期：2026-11-04；建立接收任务，清理过期/超量完成记录，不删除用户文件。
    QString begin(qint64 total, qint64 entries, const QString &peer);
    // 日期：2026-11-04；逐条记录已提交文件/目录和原始映射，每 256 项或 200ms 提交。
    void append(const QString &task, qint64 sequence, const QString &source, const QString &path,
                qint64 bytes, const QByteArray &sha256);
    // 日期：2026-11-04；先提交明细再持久化最终状态，不冒充整个批次原子提交。
    void finish(const QString &task, const QString &state, qint64 received,
                const QString &error = QString());
    // 日期：2026-11-04；按页读取至多 100 项，调用方不会加载完整批次清单。
    QJsonArray page(const QString &task, qint64 afterSequence = 0);
    // 日期：2026-11-04；返回任务状态、计数与已保存的接收端身份信息。
    QJsonObject task(const QString &id);
    // 日期：2026-11-04；按实际路径输出持久索引位置。
    QString path() const;

  private:
    // 日期：2026-11-04；只有存在待提交事务时执行提交。
    void flush();
    // 日期：2026-11-04；按每页 100 项识别失去进程所有权的旧接收，结果标为中断未知。
    void recoverInterrupted();
    // 日期：2026-11-04；每个任务持有跨进程锁，长传输不按文件年龄误判失效。
    std::unique_ptr<QLockFile> taskLock(const QString &id) const;
    SqliteCacheCredit cacheCredit_{2048};
    std::shared_ptr<HistoryState> state_;
    QSqlDatabase database_;
    QString connection_;
    QString activeTask_;
    std::unique_ptr<QLockFile> ownership_;
    bool transaction_ = false;
    int pending_ = 0;
    qint64 lastCommit_ = 0;
};
} // namespace dukto
