#pragma once

#include "privatestore.h"
#include "sqlitecache.h"
#include <QElapsedTimer>
#include <QJsonArray>
#include <QLockFile>
#include <QSqlDatabase>
#include <atomic>
#include <functional>
#include <memory>

namespace dukto {
constexpr qint64 StrongBlockBytes = 4 * 1024 * 1024;
struct StrongEntry {
    quint64 id = 0;
    QString relative;
    QString source;
    bool directory = false;
    qint64 bytes = 0;
    QByteArray sha256;
    // 日期：2026-11-04；网络字段不包含本机源路径，大小和 ID 始终用规范十进制字符串。
    QJsonObject publicInfo() const;
};

class StrongManifest final {
  public:
    // 日期：2026-11-04；新建和只读模式显式区分；已有不完整清单不能被当作可用强身份。
    StrongManifest(PrivateStore &store, const QString &name, bool create,
                   const std::function<void()> &check = {}, int cacheKiB = 2048);
    // 日期：2026-11-04；先归还本线程 SQLite 连接；未完成构建保留不完整标记供显式回收。
    ~StrongManifest();
    StrongManifest(const StrongManifest &) = delete;
    StrongManifest &operator=(const StrongManifest &) = delete;
    // 日期：2026-11-04；在磁盘中排序扫描结果，256 KiB 流式计算全文件及每个 4 MiB 块摘要。
    void scan(const QStringList &paths, const std::atomic_bool *cancel = nullptr,
              const std::function<void()> &check = {});
    // 日期：2026-11-04；导入一条清单记录，严格递增 ID、相对路径、父目录和跨平台重名边界。
    void append(const StrongEntry &entry);
    // 日期：2026-11-04；按文件内连续块序号导入强摘要，尾块长度由文件大小唯一确定。
    void appendBlock(quint64 file, quint64 block, qint64 bytes, const QByteArray &sha256);
    // 日期：2026-11-04；重新核对全部磁盘记录并冻结确定编码的强摘要，失败不能发布完成状态。
    QByteArray seal(const QByteArray &expected = {}, const std::function<void()> &check = {});
    // 日期：2026-11-04；只读精确文件 ID，不依据客户端传来的绝对源路径访问磁盘。
    StrongEntry entry(quint64 id) const;
    // 日期：2026-11-04；每页同时受 100 项和 64 KiB 控制帧预算限制，按 ID 幂等读取。
    QJsonArray entries(quint64 after = 0) const;
    // 日期：2026-11-04；块摘要逐页读取；单个大文件也不会生成随块数增长的内存数组。
    QJsonArray blocks(quint64 file, quint64 first = 0) const;
    // 日期：2026-11-04；返回冻结后的条目/块/字节计数和内容身份，未完成状态明确拒绝。
    QJsonObject summary() const;
    // 日期：2026-11-04；重新验证磁盘清单的强编码和范围，不只信任持久摘要字段。
    void verify(const std::function<void()> &check = {}) const;
    // 日期：2026-11-04；仅向同进程数据工作者提供冻结库位置，各线程重建自己的只读连接并重验。
    QPair<QString, QString> backing() const;

  private:
    // 日期：2026-11-04；固定 SQL 仅用于本地架构，错误规范化，不泄露数据库中的源绝对路径。
    void execute(const QString &sql) const;
    // 日期：2026-11-04；写事务每 256 条或 200ms 提交，缓存和回滚日志均有固定上限。
    void changed();
    // 日期：2026-11-04；显式提交当前小事务，所有发布和读前必须调用。
    void flush();
    // 日期：2026-11-04；按固定序号、UTF-8 路径及大端整数重算规范内容摘要。
    QByteArray digest(const std::function<void()> &check) const;
    PrivateStore &store_;
    QString name_;
    QString connection_;
    SqliteCacheCredit cacheCredit_;
    QSqlDatabase database_;
    bool writable_;
    bool transaction_ = false;
    bool sealed_ = false;
    int pending_ = 0;
    QElapsedTimer clock_;
    quint64 count_ = 0;
    quint64 blockCount_ = 0;
    qint64 total_ = 0;
    QString lastRelative_;
    QByteArray identity_;
    std::unique_ptr<QLockFile> ownership_;
};

class TemporaryManifest final {
  public:
    // 日期：2026-11-04；上传源扫描可重建，独占随机库仅用于本次操作，不与持久下载/接收清单混用。
    explicit TemporaryManifest(PrivateStore &store);
    // 日期：2026-11-04；先关闭 SQLite 再回收本次临时库，正常失败/重试不累积源扫描副本。
    ~TemporaryManifest();
    TemporaryManifest(const TemporaryManifest &) = delete;
    TemporaryManifest &operator=(const TemporaryManifest &) = delete;
    // 日期：2026-11-04；访问当前线程拥有的强清单，不传给其他线程或跨越包装对象生命周期。
    StrongManifest &get() const;

  private:
    // 日期：2026-11-04；只处理自己随机名称和对应 SQLite 日志；失败保留文件并输出明确诊断。
    void discard() noexcept;
    PrivateStore &store_;
    QString name_;
    std::unique_ptr<StrongManifest> manifest_;
};
} // namespace dukto
