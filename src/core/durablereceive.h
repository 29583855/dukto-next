#pragma once

#include "files.h"
#include "sqlitecache.h"
#include "strongmanifest.h"
#include <QCryptographicHash>
#include <QSqlDatabase>
#include <QUuid>
#include <map>

namespace dukto {
class ReceiveFile;
class Error;

// 持久接收日志由任务执行者持有；本类不自行授予网络主体访问目标目录的权限。
class DurableReceive final {
  public:
    // 日期：2026-11-05；日志绑定任务、冻结清单、固定根和冲突策略；默认旧日志字节保持兼容。
    DurableReceive(PrivateStore &store, const QString &name, const QUuid &task,
                   StrongManifest &manifest, const QString &root,
                   ConflictPolicy conflict = ConflictPolicy::Rename);
    // 日期：2026-11-04；关闭接收句柄与 SQLite 连接，保留临时数据和已同步检查点用于恢复。
    ~DurableReceive();
    DurableReceive(const DurableReceive &) = delete;
    DurableReceive &operator=(const DurableReceive &) = delete;
    // 日期：2026-11-05；持久预约并核对目录映射；默认保留双方，显式覆盖仅复用安全普通目录。
    QString prepare(quint64 file, const std::function<void()> &check = {});
    // 日期：2026-11-04；选择清单中的普通文件及目标相对名称；逐块重读检查点后返回首个缺失块。
    quint64 open(quint64 file, const QString &destination, const std::function<void()> &check = {});
    // 日期：2026-11-04；恢复任意已确认块，各块独立重读；最多交错接收 16 块，不驻留整块数据。
    quint64 openSparse(quint64 file, const QString &destination,
                       const std::function<void()> &check = {});
    // 日期：2026-11-04；同一日志最多打开 16
    // 个文件；各文件句柄和部分块状态独立且不新建每文件数据库。
    void openConcurrent(quint64 file, const QString &destination,
                        const std::function<void()> &check = {});
    // 日期：2026-11-04；仅在日志所属线程切换已经打开的文件，不跨线程共享 QFile/SQLite。
    void activate(quint64 file);
    // 日期：2026-11-04；完成提交后归还当前文件句柄，持久任务仍保留在同一日志中。
    void closeCurrent();
    // 日期：2026-11-04；只查询本次打开重读过或写入同步过的块；不把未完成片段算作确认。
    bool hasBlock(quint64 block) const;
    // 日期：2026-11-04；块内连续接收至多 256 KiB 片段；稀疏模式允许不同块交错，摘要同步后才确认。
    void write(quint64 block, quint32 offset, const QByteArray &bytes,
               const std::function<void()> &check = {});
    // 日期：2026-11-05；全摘要与同步后按策略原子发布；提交意图绑定新文件身份，重试确认同一结果。
    QString finish(const std::function<void()> &check = {});
    // 日期：2026-11-04；当前已验证字节总量；顺序模式为前缀，稀疏模式可包含非连续已确认块。
    qint64 confirmed() const;
    // 日期：2026-11-04；返回当前文件持久状态，供任务执行者区分接收与提交结果未知。
    QString state() const;

  private:
    // 日期：2026-11-04；两种传输模式共用任务绑定、原生身份与提交恢复，不能绕过强清单。
    quint64 openFile(quint64 file, const QString &destination, const std::function<void()> &check,
                     bool sparse);
    // 日期：2026-11-05；每项只保留最近一次确定的接收错误；写证据失败不能掩盖原异常。
    void recordFailure(quint64 file, const QString &phase, const Error &error) noexcept;
    // 日期：2026-11-05；与完成状态在同一事务解决旧错误，随后新的失败仍可重新记录。
    void resolveFailure(quint64 file);
    struct Partial {
        quint32 offset = 0;
        QCryptographicHash hash{QCryptographicHash::Sha256};
    };
    struct Cursor;
    // 日期：2026-11-04；POSIX 固定句柄不能阻止改名，每次数据访问仍检查原目标根身份。
    void verifyRoot() const;
    // 日期：2026-11-04；参数绑定后的 SQL 操作必须实际执行成功，错误不泄露本地路径。
    void execute(QSqlQuery &query) const;
    // 日期：2026-11-04；仅使用固定 SQL 变更架构和事务配置，不插入远端字段。
    void sql(const QString &statement) const;
    // 日期：2026-11-04；每次持久发布文件状态都使用同步事务，失败保留原可查询证据。
    void save(const QString &state, const QString &target, qint64 confirmed);
    // 日期：2026-11-04；从固定强清单读取唯一的期望块长度和 SHA-256，不接受网络摘要覆盖。
    QJsonObject expectedBlock(quint64 block) const;
    // 日期：2026-11-04；流式重读文件范围，包含取消/授权检查点并拒绝短读。
    QByteArray digest(qint64 offset, qint64 bytes, const std::function<void()> &check);
    // 日期：2026-11-04；提交中重开已记录的同一原生文件，不能把同名外部文件误认作本任务结果。
    void recoverCommit(const std::function<void()> &check);
    PrivateStore &store_;
    StrongManifest &manifest_;
    QString root_;
    ConflictPolicy conflict_;
#ifdef Q_OS_WIN
    std::unique_ptr<NativeDirectoryLock> rootLock_;
#else
    std::unique_ptr<PosixDirectory> rootLock_;
#endif
    QString connection_;
    SqliteCacheCredit cacheCredit_{1024};
    QSqlDatabase database_;
    std::unique_ptr<QLockFile> ownership_;
    std::unique_ptr<Cursor> current_;
    std::map<quint64, std::unique_ptr<Cursor>> parked_;
};
} // namespace dukto
