#include "catalog.h"
#include "error.h"
#include "historystate.h"
#include "sqliteruntime.h"
#include <QDateTime>
#include <QDir>
#include <QFileInfo>
#include <QJsonObject>
#include <QSqlError>
#include <QSqlQuery>
#include <QUuid>

namespace dukto {
// 日期：2026-11-05；缓存 2 MiB、数据库 256 MiB、锁等待 2 秒，元数据不可无界增长。
Catalog::Catalog(const QString &path)
    : connection_(QUuid::createUuid().toString(QUuid::WithoutBraces)) {
    if (!QDir().mkpath(QFileInfo(path).absolutePath()))
        throw Error(ExitCode::Disk, QStringLiteral("无法创建接收明细目录"), "catalog");
    // 日期：2026-11-09；固定接收明细迁入私有历史根，整个连接寿命保留共享资格和旧库读锁。
    state_ = HistoryState::catalog(path);
    database_ = addSqliteDatabase(connection_, state_ ? state_->policy() : nullptr);
    try {
        database_.setDatabaseName(state_ ? state_->path() : QFileInfo(path).absoluteFilePath());
        database_.setConnectOptions("QSQLITE_BUSY_TIMEOUT=2000");
        if (!database_.open())
            throw Error(ExitCode::Disk, database_.lastError().text(), "catalog");
        if (state_)
            state_->validate(database_);
        cacheCredit_.configure(database_);
        QSqlQuery query(database_);
        for (const auto sql :
             {"PRAGMA max_page_count=65536", "PRAGMA foreign_keys=ON", "PRAGMA temp_store=FILE",
              "CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, time INTEGER, state TEXT, "
              "total "
              "INTEGER, entries INTEGER, peer TEXT, received INTEGER, error TEXT)",
              "CREATE TABLE IF NOT EXISTS files(task TEXT REFERENCES tasks(id) ON DELETE CASCADE, "
              "seq "
              "INTEGER, source TEXT, path TEXT, bytes INTEGER, sha256 TEXT, PRIMARY "
              "KEY(task,seq))",
              "CREATE INDEX IF NOT EXISTS tasks_time ON tasks(time)"})
            if (!query.exec(sql))
                throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
        query.finish();
        recoverInterrupted();
    } catch (...) {
        database_.close();
        database_ = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection_);
        throw;
    }
}

// 日期：2026-11-04；查询均为栈对象，销毁连接时没有活跃游标。
Catalog::~Catalog() {
    if (transaction_)
        database_.rollback();
    database_.close();
    database_ = QSqlDatabase();
    QSqlDatabase::removeDatabase(connection_);
}

// 日期：2026-11-04；清理仅涉及已结束任务，活动或结果未知任务不得静默遗忘。
QString Catalog::begin(qint64 total, qint64 entries, const QString &peer) {
    if (ownership_)
        throw Error(ExitCode::Config, QStringLiteral("接收明细已有活动任务"), "catalog");
    QLockFile admission(database_.databaseName() + ".admission.lock");
    admission.setStaleLockTime(0);
    if (!admission.tryLock(2000))
        throw Error(ExitCode::Disk, QStringLiteral("接收明细任务准入繁忙或不可写"), "catalog");
    QSqlQuery query(database_);
    if (!query.exec("DELETE FROM tasks WHERE state IN ('completed','failed') AND (time < "
                    "strftime('%s','now')-2592000 OR id NOT IN (SELECT id FROM tasks ORDER BY time "
                    "DESC LIMIT 9999))"))
        throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
    const auto id = QUuid::createUuid().toString(QUuid::WithoutBraces);
    auto owner = taskLock(id);
    if (!owner->tryLock(0))
        throw Error(ExitCode::Disk, QStringLiteral("无法建立接收任务所有权锁"), "catalog");
    if (!query.exec("SELECT COUNT(*) FROM tasks") || !query.next())
        throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
    if (query.value(0).toLongLong() >= 10000)
        throw Error(ExitCode::Disk, QStringLiteral("接收明细任务配额已满，请先核对中断任务"),
                    "catalog");
    query.finish();
    query.prepare("INSERT INTO tasks VALUES (?, ?, 'receiving', ?, ?, ?, 0, '')");
    query.addBindValue(id);
    query.addBindValue(QDateTime::currentSecsSinceEpoch());
    query.addBindValue(total);
    query.addBindValue(entries);
    query.addBindValue(peer);
    if (!query.exec())
        throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
    activeTask_ = id;
    ownership_ = std::move(owner);
    return id;
}

// 日期：2026-11-04；明细采用小事务，元数据写入失败会中止任务并保留此前已提交文件。
void Catalog::append(const QString &task, qint64 sequence, const QString &source,
                     const QString &path, qint64 bytes, const QByteArray &sha256) {
    if (!ownership_ || task != activeTask_)
        throw Error(ExitCode::Config, QStringLiteral("不能修改非当前接收任务的明细"), "catalog");
    if (!transaction_) {
        if (!database_.transaction())
            throw Error(ExitCode::Disk, database_.lastError().text(), "catalog");
        transaction_ = true;
        lastCommit_ = QDateTime::currentMSecsSinceEpoch();
    }
    QSqlQuery query(database_);
    query.prepare("INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)");
    query.addBindValue(task);
    query.addBindValue(sequence);
    query.addBindValue(source);
    query.addBindValue(path);
    query.addBindValue(bytes);
    query.addBindValue(QString::fromLatin1(sha256.toHex()));
    if (!query.exec())
        throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
    if (++pending_ >= 256 || QDateTime::currentMSecsSinceEpoch() - lastCommit_ >= 200)
        flush();
}

// 日期：2026-11-04；最终状态与总收到字节保存后，调用方才可报告完成。
void Catalog::finish(const QString &task, const QString &state, qint64 received,
                     const QString &error) {
    if (!ownership_ || task != activeTask_ || (state != "completed" && state != "failed"))
        throw Error(ExitCode::Config, QStringLiteral("接收任务所有权或最终状态无效"), "catalog");
    flush();
    QSqlQuery query(database_);
    query.prepare("UPDATE tasks SET state=?, received=?, error=? WHERE id=?");
    query.addBindValue(state);
    query.addBindValue(received);
    query.addBindValue(error.isNull() ? QString("") : error);
    query.addBindValue(task);
    if (!query.exec() || query.numRowsAffected() != 1)
        throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
    ownership_.reset();
    activeTask_.clear();
}

// 日期：2026-11-04；锁文件位于独立私有目录，UUID 校验避免数据库内容构造任意路径。
std::unique_ptr<QLockFile> Catalog::taskLock(const QString &id) const {
    if (QUuid(id).isNull() || QUuid(id).toString(QUuid::WithoutBraces) != id)
        throw Error(ExitCode::Disk, QStringLiteral("接收明细任务 ID 无效"), "catalog");
    const auto directory = database_.databaseName() + ".locks";
    if (!QDir().mkpath(directory))
        throw Error(ExitCode::Disk, QStringLiteral("无法创建接收任务锁目录"), "catalog");
    std::unique_ptr<QLockFile> lock(new QLockFile(QDir(directory).filePath(id + ".lock")));
    lock->setStaleLockTime(0);
    return lock;
}

// 日期：2026-11-04；只收回没有存活进程持锁的接收，不删除文件，也不假定已提交文件完整入库。
void Catalog::recoverInterrupted() {
    QString after;
    for (;;) {
        QSqlQuery query(database_);
        query.prepare(
            "SELECT id FROM tasks WHERE state='receiving' AND id>? ORDER BY id LIMIT 100");
        query.addBindValue(after.isNull() ? QString("") : after);
        if (!query.exec())
            throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
        QStringList ids;
        while (query.next())
            ids.append(query.value(0).toString());
        if (query.lastError().isValid())
            throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
        query.finish();
        if (ids.isEmpty())
            return;
        for (const auto &id : ids) {
            auto owner = taskLock(id);
            if (!owner->tryLock(0)) {
                if (owner->error() != QLockFile::LockFailedError)
                    throw Error(ExitCode::Disk, QStringLiteral("无法核对接收任务锁"), "catalog");
                continue;
            }
            query.prepare("UPDATE tasks SET state='interrupted', error=? WHERE id=? AND "
                          "state='receiving'");
            query.addBindValue(
                QStringLiteral("上次接收进程已退出，最终结果未知；请核对接收目录。"
                               "部分文件可能已提交但尚未记入明细，R6 不支持断点续传。"));
            query.addBindValue(id);
            if (!query.exec())
                throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
        }
        after = ids.last();
    }
}

// 日期：2026-11-04；每次查询只返回有限记录，序号使用十进制字符串避免 64 位精度损失。
QJsonArray Catalog::page(const QString &task, qint64 afterSequence) {
    QSqlQuery query(database_);
    query.setForwardOnly(true);
    query.prepare("SELECT seq,source,path,bytes,sha256 FROM files WHERE task=? AND seq>? ORDER BY "
                  "seq LIMIT 100");
    query.addBindValue(task);
    query.addBindValue(afterSequence);
    if (!query.exec())
        throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
    QJsonArray result;
    while (query.next())
        result.append(QJsonObject{{"sequence", query.value(0).toString()},
                                  {"source", query.value(1).toString()},
                                  {"path", query.value(2).toString()},
                                  {"bytes", query.value(3).toString()},
                                  {"sha256", query.value(4).toString()}});
    if (query.lastError().isValid())
        throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
    return result;
}

// 日期：2026-11-04；找不到任务时给出明确错误，不能将空结果解释为成功。
QJsonObject Catalog::task(const QString &id) {
    QSqlQuery query(database_);
    query.prepare("SELECT time,state,total,entries,peer,received,error FROM tasks WHERE id=?");
    query.addBindValue(id);
    if (!query.exec())
        throw Error(ExitCode::Disk, query.lastError().text(), "catalog");
    if (!query.next())
        throw Error(ExitCode::Config, QStringLiteral("接收任务不存在或明细已过期"), "catalog");
    return {{"taskId", id},
            {"time", query.value(0).toString()},
            {"state", query.value(1).toString()},
            {"total", query.value(2).toString()},
            {"entries", query.value(3).toString()},
            {"peer", query.value(4).toString()},
            {"bytes", query.value(5).toString()},
            {"message", query.value(6).toString()}};
}

// 日期：2026-11-04；路径只用于本机结果索引，不通过 R6 网络发出。
QString Catalog::path() const {
    return database_.databaseName();
}

// 日期：2026-11-04；提交失败保留事务标志供析构回滚。
void Catalog::flush() {
    if (transaction_ && !database_.commit())
        throw Error(ExitCode::Disk, database_.lastError().text(), "catalog");
    transaction_ = false;
    pending_ = 0;
}
} // namespace dukto
