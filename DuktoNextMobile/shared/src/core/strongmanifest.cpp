#include "strongmanifest.h"
#include "error.h"
#include "files.h"
#include "manifest.h"
#include "protocol.h"
#include "sourcefile.h"
#include "sqliteruntime.h"

#include <QCryptographicHash>
#include <QDir>
#include <QJsonDocument>
#include <QSqlError>
#include <QSqlQuery>
#include <QtEndian>
#include <limits>

namespace dukto {
// 日期：2026-11-04；未冻结清单不能交给数据线程；位置仅用于本地，绝不写入票据或网络字段。
QPair<QString, QString> StrongManifest::backing() const {
    summary();
    return {store_.directory(), name_};
}

// 日期：2026-11-04；扫描库只有当前调用者持有，发送内容仍受强清单摘要和原生源句柄约束。
TemporaryManifest::TemporaryManifest(PrivateStore &store)
    : store_(store),
      name_("upload-" + QUuid::createUuid().toString(QUuid::WithoutBraces) + ".sqlite") {
    if (store_.exists(name_))
        throw Error(ExitCode::Permission, QStringLiteral("临时扫描名称已被占用"), "manifest");
    try {
        manifest_.reset(new StrongManifest(store_, name_, true));
    } catch (...) {
        discard();
        throw;
    }
}

// 日期：2026-11-04；销毁顺序保证 Windows SQLite 句柄先释放，不能在仍扫描时删除数据库。
TemporaryManifest::~TemporaryManifest() {
    manifest_.reset();
    discard();
}

// 日期：2026-11-04；引用不转移所有权，接收端日志始终使用独立的持久 StrongManifest。
StrongManifest &TemporaryManifest::get() const {
    return *manifest_;
}

// 日期：2026-11-04；析构不得抛异常覆盖传输结果；权限/磁盘错误保留证据并明确报告。
void TemporaryManifest::discard() noexcept {
    try {
        for (const auto &name : {name_, name_ + "-journal"})
            if (store_.exists(name))
                store_.remove(name);
    } catch (...) {
        qWarning("临时源清单回收失败，已保留状态文件供管理");
    }
}

namespace {
// 日期：2026-11-04；SQL 错误不包含数据库路径或源文件名，调用方统一报告清单磁盘失败。
void checked(QSqlQuery &query) {
    if (!query.exec())
        throw Error(ExitCode::Disk, QStringLiteral("强清单数据库操作失败"), "manifest");
}

// 日期：2026-11-04；不直接 hash 内存整数，规范字段按指定宽度写大端，跨系统/架构得到同一身份。
void number(QCryptographicHash &hash, quint64 value, int width = 8) {
    char bytes[8];
    qToBigEndian(value, reinterpret_cast<uchar *>(bytes));
    hash.addData(bytes + 8 - width, width);
}

// 日期：2026-11-04；数据库行只按已知列解码，目录和文件摘要使用不同的严格长度要求。
StrongEntry row(const QSqlQuery &query) {
    return {query.value(0).toULongLong(), query.value(1).toString(),
            query.value(2).toString(),    query.value(3).toBool(),
            query.value(4).toLongLong(),  query.value(5).toByteArray()};
}

// 日期：2026-11-04；扫描和摘要处理每个片段均检查取消，并允许服务层周期重查授权。
void checkWork(const std::atomic_bool *cancel, const std::function<void()> &check) {
    if (cancel && cancel->load())
        throw Error(ExitCode::Cancelled, QStringLiteral("强清单操作已取消"), "manifest");
    if (check)
        check();
}
} // namespace

// 日期：2026-11-04；目录 SHA 字段为空字符串；文件包括空文件均必须携带精确 32 字节摘要。
QJsonObject StrongEntry::publicInfo() const {
    return {{"id", QString::number(id)},
            {"path", relative},
            {"type", directory ? "directory" : "file"},
            {"bytes", QString::number(bytes)},
            {"sha256", QString::fromLatin1(sha256.toHex())}};
}

// 日期：2026-11-05；数据库在原生安全创建的文件上打开；不完整清单只允许原构建者写入。
StrongManifest::StrongManifest(PrivateStore &store, const QString &name, bool create,
                               const std::function<void()> &check, int cacheKiB)
    : store_(store), name_(name), connection_(QUuid::createUuid().toString()),
      cacheCredit_(cacheKiB), writable_(create) {
    const bool existed = store.exists(name);
    if (create) {
        ownership_.reset(new QLockFile(QDir(store.directory()).filePath(name + ".lock")));
        ownership_->setStaleLockTime(0);
        if (existed || !ownership_->tryLock(0) || store.exists(name))
            throw Error(ExitCode::Permission, QStringLiteral("强清单已存在或正在建立"), "manifest");
        store.write(name, {});
    }
    if (store.validateFile(name) > MaxMetadataBytes)
        throw Error(ExitCode::Disk, QStringLiteral("强清单超出磁盘预算"), "manifest");
    database_ = addSqliteDatabase(connection_);
    try {
        if (!create)
            database_.setConnectOptions("QSQLITE_OPEN_READONLY");
        database_.setDatabaseName(QDir(store.directory()).filePath(name));
        if (!database_.open())
            throw Error(ExitCode::Disk, QStringLiteral("无法打开强清单数据库"), "manifest");
        cacheCredit_.configure(database_);
        execute("PRAGMA temp_store=FILE");
        execute("PRAGMA busy_timeout=1000");
        if (create) {
            execute("PRAGMA page_size=4096");
            execute("PRAGMA max_page_count=65536");
            execute("PRAGMA journal_mode=DELETE");
            execute("PRAGMA synchronous=FULL");
            execute("PRAGMA journal_size_limit=8388608");
            execute("CREATE TABLE entries(id INTEGER PRIMARY KEY, relative TEXT NOT NULL, "
                    "source TEXT NOT NULL, directory INTEGER NOT NULL, bytes INTEGER NOT NULL, "
                    "sha BLOB NOT NULL, pathkey TEXT UNIQUE NOT NULL)");
            execute("CREATE TABLE blocks(file INTEGER NOT NULL, block INTEGER NOT NULL, bytes "
                    "INTEGER NOT NULL, sha BLOB NOT NULL, PRIMARY KEY(file,block)) WITHOUT ROWID");
            execute("CREATE TABLE metadata(value BLOB NOT NULL)");
            clock_.start();
        } else {
            QSqlQuery query(database_);
            if (!query.exec("SELECT value FROM metadata") || !query.next())
                throw Error(ExitCode::Integrity, QStringLiteral("强清单尚未完成或已损坏"),
                            "manifest");
            const auto meta = next::parseControl(query.value(0).toByteArray());
            if (meta["version"] != 1 || meta["blockBytes"] != QString::number(StrongBlockBytes) ||
                query.next())
                throw Error(ExitCode::Integrity, QStringLiteral("强清单版本或记录无效"),
                            "manifest");
            count_ = next::decimal(meta["entries"], 10000000);
            blockCount_ = next::decimal(meta["blocks"], std::numeric_limits<qint64>::max());
            total_ = static_cast<qint64>(
                next::decimal(meta["bytes"], std::numeric_limits<qint64>::max()));
            identity_ = QByteArray::fromHex(meta["sha256"].toString().toLatin1());
            if (!count_ || identity_.size() != 32 ||
                meta["sha256"] != QString::fromLatin1(identity_.toHex()))
                throw Error(ExitCode::Integrity, QStringLiteral("强清单内容身份无效"), "manifest");
            sealed_ = true;
            verify(check);
        }
    } catch (...) {
        database_.close();
        database_ = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection_);
        throw;
    }
}

// 日期：2026-11-04；异常退出回滚当前小事务，绝不自动冻结或将半份清单标记完成。
StrongManifest::~StrongManifest() {
    if (transaction_)
        database_.rollback();
    database_.close();
    database_ = QSqlDatabase();
    QSqlDatabase::removeDatabase(connection_);
}

// 日期：2026-11-04；固定 SQL 执行不插入远端输入，用户字段全部使用 bindValue。
void StrongManifest::execute(const QString &sql) const {
    QSqlQuery query(database_);
    if (!query.exec(sql))
        throw Error(ExitCode::Disk, QStringLiteral("强清单数据库结构操作失败"), "manifest");
}

// 日期：2026-11-04；开始下一次写入前提交已达界的小事务，避免大批次线性增长回滚日志。
void StrongManifest::changed() {
    if (!writable_ || sealed_)
        throw Error(ExitCode::Config, QStringLiteral("强清单已冻结或只读"), "manifest");
    if (pending_ >= 256 || clock_.elapsed() >= 200)
        flush();
    if (!transaction_) {
        if (!database_.transaction())
            throw Error(ExitCode::Disk, QStringLiteral("强清单事务启动失败"), "manifest");
        transaction_ = true;
    }
    ++pending_;
}

// 日期：2026-11-04；提交失败保留事务标记，析构会回滚且调用方收到明确磁盘错误。
void StrongManifest::flush() {
    if (transaction_ && !database_.commit())
        throw Error(ExitCode::Disk, QStringLiteral("强清单事务提交失败"), "manifest");
    transaction_ = false;
    pending_ = 0;
    clock_.restart();
}

// 日期：2026-11-04；清单按 UTF-8 字节顺序排序，父目录必须先存在且不能是普通文件。
void StrongManifest::append(const StrongEntry &entry) {
    validateRelativePath(entry.relative);
    if (!entry.id || entry.id != count_ + 1 || count_ >= 10000000 || entry.bytes < 0 ||
        (entry.directory && (entry.bytes || !entry.sha256.isEmpty())) ||
        (!entry.directory && entry.sha256.size() != 32) ||
        (!lastRelative_.isEmpty() && lastRelative_.toUtf8() >= entry.relative.toUtf8()) ||
        entry.bytes > std::numeric_limits<qint64>::max() - total_)
        throw Error(ExitCode::Integrity, QStringLiteral("强清单条目身份、顺序或长度无效"),
                    "manifest");
    const auto separator = entry.relative.lastIndexOf('/');
    if (separator >= 0) {
        QSqlQuery parent(database_);
        parent.prepare("SELECT directory FROM entries WHERE pathkey=? AND relative=?");
        const auto relative = entry.relative.left(separator);
        parent.addBindValue(relative.normalized(QString::NormalizationForm_C).toCaseFolded());
        parent.addBindValue(relative);
        checked(parent);
        if (!parent.next() || !parent.value(0).toBool())
            throw Error(ExitCode::Integrity, QStringLiteral("强清单父目录缺失或名称冲突"),
                        "manifest");
    }
    changed();
    QSqlQuery query(database_);
    query.prepare("INSERT INTO entries VALUES(?,?,?,?,?,?,?)");
    query.addBindValue(static_cast<qlonglong>(entry.id));
    query.addBindValue(entry.relative);
    query.addBindValue(entry.source.isNull() ? QString("") : entry.source);
    query.addBindValue(entry.directory);
    query.addBindValue(entry.bytes);
    query.addBindValue(entry.sha256.isNull() ? QByteArray("") : entry.sha256);
    query.addBindValue(entry.relative.normalized(QString::NormalizationForm_C).toCaseFolded());
    checked(query);
    ++count_;
    total_ += entry.bytes;
    lastRelative_ = entry.relative;
}

// 日期：2026-11-04；只接受该文件的下一个块，重复、缺口、越界或错误尾块长度均拒绝。
void StrongManifest::appendBlock(quint64 file, quint64 block, qint64 bytes,
                                 const QByteArray &sha256) {
    const auto item = entry(file);
    if (item.directory || item.bytes == 0 ||
        block > static_cast<quint64>((item.bytes - 1) / StrongBlockBytes) ||
        bytes !=
            qMin(StrongBlockBytes, item.bytes - static_cast<qint64>(block) * StrongBlockBytes) ||
        sha256.size() != 32)
        throw Error(ExitCode::Integrity, QStringLiteral("强清单分块范围或摘要无效"), "manifest");
    QSqlQuery previous(database_);
    previous.prepare("SELECT COALESCE(MAX(block)+1,0) FROM blocks WHERE file=?");
    previous.addBindValue(static_cast<qlonglong>(file));
    checked(previous);
    if (!previous.next() || previous.value(0).toULongLong() != block)
        throw Error(ExitCode::Integrity, QStringLiteral("强清单分块重复或不连续"), "manifest");
    previous.finish();
    changed();
    QSqlQuery query(database_);
    query.prepare("INSERT INTO blocks VALUES(?,?,?,?)");
    query.addBindValue(static_cast<qlonglong>(file));
    query.addBindValue(static_cast<qlonglong>(block));
    query.addBindValue(bytes);
    query.addBindValue(sha256);
    checked(query);
    ++blockCount_;
}

// 日期：2026-11-04；条目查询返回一行；超过 SQLite 有符号 ID 范围的输入在转换前拒绝。
StrongEntry StrongManifest::entry(quint64 id) const {
    if (!id || id > count_)
        throw Error(ExitCode::Integrity, QStringLiteral("强清单文件 ID 不存在"), "manifest");
    QSqlQuery query(database_);
    query.prepare("SELECT id,relative,source,directory,bytes,sha FROM entries WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(id));
    checked(query);
    if (!query.next())
        throw Error(ExitCode::Integrity, QStringLiteral("强清单文件记录缺失"), "manifest");
    return row(query);
}

// 日期：2026-11-04；目录条目先落磁盘，随后按同一编码顺序打开固定源句柄并生成块强摘要。
void StrongManifest::scan(const QStringList &paths, const std::atomic_bool *cancel,
                          const std::function<void()> &check) {
    if (!writable_ || sealed_ || count_)
        throw Error(ExitCode::Config, QStringLiteral("强清单不能重复扫描"), "manifest");
    Manifest source;
    source.scan(paths, cancel, [&]() {
        // 日期：2026-11-04；目录枚举阶段同样观察服务授权/连接，不能只在后续内容摘要阶段检查。
        checkWork(cancel, check);
    });
    execute("CREATE TABLE staging(relative TEXT PRIMARY KEY, source TEXT, bytes INTEGER) WITHOUT "
            "ROWID");
    Entry item;
    while (source.next(item)) {
        checkWork(cancel, check);
        changed();
        QSqlQuery insert(database_);
        insert.prepare("INSERT INTO staging VALUES(?,?,?)");
        insert.addBindValue(item.relative);
        insert.addBindValue(item.source);
        insert.addBindValue(item.size);
        checked(insert);
    }
    flush();
    QSqlQuery sorted(database_);
    sorted.setForwardOnly(true);
    if (!sorted.exec("SELECT relative,source,bytes FROM staging ORDER BY relative COLLATE BINARY"))
        throw Error(ExitCode::Disk, QStringLiteral("强清单磁盘排序失败"), "manifest");
    while (sorted.next()) {
        checkWork(cancel, check);
        const qint64 size = sorted.value(2).toLongLong();
        StrongEntry current{
            count_ + 1, sorted.value(0).toString(), sorted.value(1).toString(),
            size < 0,   qMax(qint64(0), size),      size < 0 ? QByteArray() : QByteArray(32, '\0')};
        append(current);
        if (current.directory)
            continue;
        SourceFile input(current.source);
        if (input.device().size() != size)
            throw Error(ExitCode::Integrity, QStringLiteral("源文件大小在扫描后已变化"),
                        "manifest");
        QCryptographicHash whole(QCryptographicHash::Sha256);
        qint64 remaining = size;
        quint64 index = 0;
        while (remaining) {
            const auto blockBytes = qMin(remaining, StrongBlockBytes);
            qint64 consumed = 0;
            QCryptographicHash block(QCryptographicHash::Sha256);
            while (consumed < blockBytes) {
                checkWork(cancel, check);
                const auto fragment = input.device().read(qMin(BufferSize, blockBytes - consumed));
                if (fragment.isEmpty())
                    throw Error(ExitCode::Disk, QStringLiteral("源文件摘要读取不完整"), "manifest");
                whole.addData(fragment);
                block.addData(fragment);
                consumed += fragment.size();
            }
            appendBlock(current.id, index++, blockBytes, block.result());
            remaining -= blockBytes;
        }
        input.verify();
        changed();
        QSqlQuery update(database_);
        update.prepare("UPDATE entries SET sha=? WHERE id=?");
        update.addBindValue(whole.result());
        update.addBindValue(static_cast<qlonglong>(current.id));
        checked(update);
    }
    if (sorted.lastError().isValid())
        throw Error(ExitCode::Disk, QStringLiteral("强清单排序读取失败"), "manifest");
    sorted.finish();
    flush();
    execute("DROP TABLE staging");
    seal({}, [&]() { checkWork(cancel, check); });
}

// 日期：2026-11-04；稳定编码涵盖名称/类型/大小/全摘要和每块摘要；本机路径不影响跨平台身份。
QByteArray StrongManifest::digest(const std::function<void()> &check) const {
    QCryptographicHash hash(QCryptographicHash::Sha256);
    hash.addData(QByteArrayLiteral("DuktoNext.Manifest.1") + '\0');
    number(hash, StrongBlockBytes, 4);
    quint64 count = 0;
    quint64 blocks = 0;
    qint64 total = 0;
    QString previous;
    QSqlQuery files(database_);
    files.setForwardOnly(true);
    if (!files.exec("SELECT id,relative,source,directory,bytes,sha FROM entries ORDER BY id"))
        throw Error(ExitCode::Disk, QStringLiteral("强清单验证读取失败"), "manifest");
    while (files.next()) {
        if (check)
            check();
        const auto file = row(files);
        validateRelativePath(file.relative);
        if (file.id != ++count || file.bytes < 0 ||
            file.bytes > std::numeric_limits<qint64>::max() - total ||
            (!previous.isEmpty() && previous.toUtf8() >= file.relative.toUtf8()) ||
            (file.directory && (file.bytes || !file.sha256.isEmpty())) ||
            (!file.directory && file.sha256.size() != 32))
            throw Error(ExitCode::Integrity, QStringLiteral("强清单条目验证失败"), "manifest");
        previous = file.relative;
        total += file.bytes;
        hash.addData("E", 1);
        number(hash, file.id);
        const auto name = file.relative.toUtf8();
        number(hash, static_cast<quint64>(name.size()), 4);
        hash.addData(name);
        hash.addData(file.directory ? "D" : "F", 1);
        number(hash, static_cast<quint64>(file.bytes));
        hash.addData(file.directory ? QByteArray(32, '\0') : file.sha256);
        QSqlQuery chunks(database_);
        chunks.setForwardOnly(true);
        chunks.prepare("SELECT block,bytes,sha FROM blocks WHERE file=? ORDER BY block");
        chunks.addBindValue(static_cast<qlonglong>(file.id));
        checked(chunks);
        quint64 index = 0;
        qint64 consumed = 0;
        while (chunks.next()) {
            if (check)
                check();
            const auto bytes = chunks.value(1).toLongLong();
            const auto sha = chunks.value(2).toByteArray();
            if (file.directory || consumed >= file.bytes ||
                chunks.value(0).toULongLong() != index ||
                bytes != qMin(StrongBlockBytes, file.bytes - consumed) || sha.size() != 32)
                throw Error(ExitCode::Integrity, QStringLiteral("强清单分块验证失败"), "manifest");
            hash.addData("B", 1);
            number(hash, file.id);
            number(hash, index++);
            number(hash, static_cast<quint64>(bytes), 4);
            hash.addData(sha);
            consumed += bytes;
            ++blocks;
        }
        if (chunks.lastError().isValid() || consumed != file.bytes)
            throw Error(ExitCode::Integrity, QStringLiteral("强清单分块缺失或读取失败"),
                        "manifest");
    }
    QSqlQuery allBlocks(database_);
    if (!allBlocks.exec("SELECT COUNT(*) FROM blocks") || !allBlocks.next() ||
        allBlocks.value(0).toULongLong() != blocks || files.lastError().isValid() || !count ||
        count != count_ || blocks != blockCount_ || total != total_)
        throw Error(ExitCode::Integrity, QStringLiteral("强清单总计或孤立分块无效"), "manifest");
    hash.addData("Z", 1);
    number(hash, count);
    number(hash, blocks);
    number(hash, static_cast<quint64>(total));
    return hash.result();
}

// 日期：2026-11-04；expected 用于接收端核对发送方身份，错误时不写冻结元数据。
QByteArray StrongManifest::seal(const QByteArray &expected, const std::function<void()> &check) {
    if (!writable_ || sealed_)
        throw Error(ExitCode::Config, QStringLiteral("强清单不能重复冻结"), "manifest");
    flush();
    const auto sha = digest(check);
    if (!expected.isEmpty() && expected != sha)
        throw Error(ExitCode::Integrity, QStringLiteral("强清单内容身份不匹配"), "manifest");
    changed();
    QSqlQuery query(database_);
    query.prepare("INSERT INTO metadata VALUES(?)");
    query.addBindValue(next::encodeControl({{"version", 1},
                                            {"entries", QString::number(count_)},
                                            {"blocks", QString::number(blockCount_)},
                                            {"bytes", QString::number(total_)},
                                            {"blockBytes", QString::number(StrongBlockBytes)},
                                            {"sha256", QString::fromLatin1(sha.toHex())}}));
    checked(query);
    query.finish();
    flush();
    identity_ = sha;
    sealed_ = true;
    return identity_;
}

// 日期：2026-11-04；本机源路径只在 entry 返回给本进程，网络分页固定使用 publicInfo。
QJsonArray StrongManifest::entries(quint64 after) const {
    summary();
    if (after > count_)
        throw Error(ExitCode::Config, QStringLiteral("强清单分页起点无效"), "manifest");
    QSqlQuery query(database_);
    query.setForwardOnly(true);
    query.prepare("SELECT id,relative,source,directory,bytes,sha FROM entries WHERE id>? ORDER BY "
                  "id LIMIT 100");
    query.addBindValue(static_cast<qlonglong>(after));
    checked(query);
    QJsonArray result;
    while (query.next()) {
        result.append(row(query).publicInfo());
        if (QJsonDocument(result).toJson(QJsonDocument::Compact).size() >
            next::ControlLimit - 1024) {
            result.removeLast();
            break;
        }
    }
    if (query.lastError().isValid())
        throw Error(ExitCode::Disk, QStringLiteral("强清单分页读取失败"), "manifest");
    return result;
}

// 日期：2026-11-04；块列表最多 100 项，序号字符串避免 JavaScript double 丢失精度。
QJsonArray StrongManifest::blocks(quint64 file, quint64 first) const {
    summary();
    const auto item = entry(file);
    const auto count =
        item.bytes ? static_cast<quint64>((item.bytes - 1) / StrongBlockBytes + 1) : 0;
    if (first > count)
        throw Error(ExitCode::Config, QStringLiteral("强清单块分页起点无效"), "manifest");
    QSqlQuery query(database_);
    query.setForwardOnly(true);
    query.prepare(
        "SELECT block,bytes,sha FROM blocks WHERE file=? AND block>=? ORDER BY block LIMIT 100");
    query.addBindValue(static_cast<qlonglong>(file));
    query.addBindValue(static_cast<qlonglong>(first));
    checked(query);
    QJsonArray result;
    while (query.next())
        result.append(
            QJsonObject{{"block", QString::number(query.value(0).toULongLong())},
                        {"bytes", QString::number(query.value(1).toLongLong())},
                        {"sha256", QString::fromLatin1(query.value(2).toByteArray().toHex())}});
    if (query.lastError().isValid())
        throw Error(ExitCode::Disk, QStringLiteral("强清单块分页读取失败"), "manifest");
    return result;
}

// 日期：2026-11-04；任何半成品读取都明确失败，不以零计数或空摘要回退成功。
QJsonObject StrongManifest::summary() const {
    if (!sealed_)
        throw Error(ExitCode::Integrity, QStringLiteral("强清单尚未冻结"), "manifest");
    return {{"version", 1},
            {"entries", QString::number(count_)},
            {"blocks", QString::number(blockCount_)},
            {"bytes", QString::number(total_)},
            {"blockBytes", QString::number(StrongBlockBytes)},
            {"sha256", QString::fromLatin1(identity_.toHex())}};
}

// 日期：2026-11-04；重算时读取大小不随文件数或分块数增长，篡改或缺失任何记录均拒绝。
void StrongManifest::verify(const std::function<void()> &check) const {
    summary();
    if (digest(check) != identity_)
        throw Error(ExitCode::Integrity, QStringLiteral("强清单持久内容已变化"), "manifest");
}
} // namespace dukto
