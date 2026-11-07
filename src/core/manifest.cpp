#include "manifest.h"
#include "error.h"
#include "files.h"
#include "sqliteruntime.h"

#include <QDateTime>
#include <QDirIterator>
#include <QFileInfo>
#include <QSqlError>
#include <QUuid>
#include <limits>

namespace dukto {
// 日期：2026-11-05；每个线程独立 SQLite 连接，缓存上限 2 MiB、数据库上限 256 MiB。
Manifest::Manifest() : connection_(QUuid::createUuid().toString(QUuid::WithoutBraces)) {
    if (!directory_.isValid())
        throw Error(ExitCode::Disk, QStringLiteral("无法创建清单缓存目录"), "scan");
    database_ = addSqliteDatabase(connection_);
    try {
        database_.setDatabaseName(directory_.filePath("manifest.sqlite"));
        if (!database_.open())
            throw Error(ExitCode::Disk, database_.lastError().text(), "scan");
        cacheCredit_.configure(database_);
        QSqlQuery query(database_);
        for (const auto &sql :
             {"PRAGMA page_size=4096", "PRAGMA max_page_count=65536", "PRAGMA temp_store=FILE",
              "CREATE TABLE entries(source TEXT, relative TEXT, size INTEGER, modified INTEGER)",
              "CREATE TABLE roots(name TEXT PRIMARY KEY)"})
            if (!query.exec(sql))
                throw Error(ExitCode::Disk, query.lastError().text(), "scan");
    } catch (...) {
        database_.close();
        database_ = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection_);
        throw;
    }
}

// 日期：2026-11-04；连接不得被活跃游标或其他线程引用。
Manifest::~Manifest() {
    cursor_.reset();
    database_.close();
    database_ = QSqlDatabase();
    QSqlDatabase::removeDatabase(connection_);
}

// 日期：2026-11-04；每条条目只在栈上保留，超过磁盘预算时 SQLite 返回明确失败。
void Manifest::append(const QString &path, const QString &relative) {
    validateRelativePath(relative);
    const QFileInfo info(path);
    if (isLinkedPath(path))
        throw Error(ExitCode::Permission, QStringLiteral("不支持链接或重解析点：") + path, "scan");
    if ((!info.isFile() && !info.isDir()) || !info.isReadable())
        throw Error(ExitCode::Disk, QStringLiteral("不支持或不可读取的文件：") + path, "scan");
    const qint64 size = info.isDir() ? -1 : info.size();
    if (size > std::numeric_limits<qint64>::max() - totalBytes)
        throw Error(ExitCode::Disk, QStringLiteral("批次总大小超出 64 位限制"), "scan");
    QSqlQuery query(database_);
    query.prepare("INSERT INTO entries VALUES(?, ?, ?, ?)");
    query.addBindValue(info.absoluteFilePath());
    query.addBindValue(relative);
    query.addBindValue(size);
    query.addBindValue(info.lastModified().toMSecsSinceEpoch());
    if (!query.exec())
        throw Error(ExitCode::Disk, query.lastError().text(), "scan");
    ++count;
    if (size >= 0)
        totalBytes += size;
}

// 日期：2026-11-04；目录遍历不跟随链接，每 512 项提交一次以控制日志占用。
void Manifest::scan(const QStringList &paths, const std::atomic_bool *cancel,
                    const std::function<void()> &checkpoint) {
    if (count || paths.isEmpty())
        throw Error(ExitCode::Config, QStringLiteral("文件列表为空或清单已使用"), "scan");
    if (!database_.transaction())
        throw Error(ExitCode::Disk, database_.lastError().text(), "scan");
    for (const auto &path : paths) {
        if (cancel && cancel->load())
            throw Error(ExitCode::Cancelled, QStringLiteral("已取消扫描"), "scan");
        if (checkpoint)
            checkpoint();
        const QFileInfo base(path);
#ifdef Q_OS_WIN
        // 日期：2026-11-04；显式路径的父目录也不能经过 junction，固定扫描期间的父目录链。
        NativeDirectoryLock parentLock(base.absolutePath(), false);
#endif
        QString rootName;
        // 日期：2026-11-04；顶层别名在磁盘中去重，大小写或 Unicode 规范化不能合并目录。
        for (int index = 0; index < 100000; ++index) {
            const auto candidate =
                QFileInfo(renamedPath(base.absoluteFilePath(), index)).fileName();
            validateRelativePath(candidate);
            QSqlQuery query(database_);
            query.prepare("INSERT OR IGNORE INTO roots VALUES (?)");
            query.addBindValue(candidate.normalized(QString::NormalizationForm_C).toCaseFolded());
            if (!query.exec())
                throw Error(ExitCode::Disk, query.lastError().text(), "scan");
            if (query.numRowsAffected() == 1) {
                rootName = candidate;
                break;
            }
        }
        if (rootName.isEmpty())
            throw Error(ExitCode::Config, QStringLiteral("同名顶层条目超过限制"), "scan");
        append(base.absoluteFilePath(), rootName);
        // 日期：2026-11-04；顶层全是文件时也执行提交上限，不能只在遍历子目录时提交。
        if (count % 512 == 0 && (!database_.commit() || !database_.transaction()))
            throw Error(ExitCode::Disk, database_.lastError().text(), "scan");
        if (!base.isDir())
            continue;
        QDirIterator iterator(base.absoluteFilePath(),
                              QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden | QDir::System,
                              QDirIterator::Subdirectories);
        while (iterator.hasNext()) {
            if (cancel && cancel->load())
                throw Error(ExitCode::Cancelled, QStringLiteral("已取消扫描"), "scan");
            if (checkpoint)
                checkpoint();
            const auto current = iterator.next();
            const auto relative =
                rootName + '/' + QDir(base.absoluteFilePath()).relativeFilePath(current);
            append(current, relative);
            if (count % 512 == 0 && (!database_.commit() || !database_.transaction()))
                throw Error(ExitCode::Disk, database_.lastError().text(), "scan");
        }
    }
    if (!database_.commit())
        throw Error(ExitCode::Disk, database_.lastError().text(), "scan");
    rewind();
}

// 日期：2026-11-04；使用 forward-only 查询，禁止把文件清单整体加载进内存。
void Manifest::rewind() {
    cursor_.reset(new QSqlQuery(database_));
    cursor_->setForwardOnly(true);
    if (!cursor_->exec("SELECT source, relative, size, modified FROM entries ORDER BY rowid"))
        throw Error(ExitCode::Disk, cursor_->lastError().text(), "scan");
}

// 日期：2026-11-04；一项读取完成后立刻替换调用方条目。
bool Manifest::next(Entry &entry) {
    if (!cursor_)
        return false;
    if (!cursor_->next()) {
        if (cursor_->lastError().isValid())
            throw Error(ExitCode::Disk, cursor_->lastError().text(), "scan");
        return false;
    }
    entry = {cursor_->value(0).toString(), cursor_->value(1).toString(),
             cursor_->value(2).toLongLong(), cursor_->value(3).toLongLong()};
    return true;
}
} // namespace dukto
