#pragma once

#include "strongmanifest.h"

namespace dukto {
// 每条记录是调用者已核实的历史处置；本日志不代替文件落盘、授权或原生目标身份验证。
class DispositionJournal final {
  public:
    // 日期：2026-11-05；绑定任务、强清单和策略；逐条同步保存，不把跳过计入复制字节。
    DispositionJournal(PrivateStore &store, const QString &name, const QUuid &task,
                       StrongManifest &manifest, const QString &conflict,
                       const std::function<void()> &check = {});
    // 日期：2026-11-05；先关闭数据库再移除当前线程连接，保留原结果供重启核对。
    ~DispositionJournal();
    DispositionJournal(const DispositionJournal &) = delete;
    DispositionJournal &operator=(const DispositionJournal &) = delete;
    // 日期：2026-11-05；只允许按冻结清单顺序确认；重复处置必须逐字段相同，不可更改历史路径或决定。
    void append(quint64 file, const QString &path, const QString &disposition,
                quint64 skippedRoot = 0);
    // 日期：2026-11-05；有界读取同一条历史处置，未记录项明确拒绝，不从当前文件存在性推断结果。
    QJsonObject item(quint64 file) const;
    // 日期：2026-11-05；每页最多100条，重验全部记录并计算版本化摘要；requireComplete拒绝缺项。
    QJsonObject summary(bool requireComplete = true, const std::function<void()> &check = {}) const;

  private:
    // 日期：2026-11-05；校验单条规范字段，不递归追溯父项，避免深目录耗尽调用栈。
    QJsonObject canonicalItem(quint64 file, const QString &path, const QString &disposition,
                              quint64 skippedRoot) const;
    // 日期：2026-11-05；编码严格绑定清单条目和相对目标；子树跳过必须指向已持久化的目录根。
    QJsonObject checkedItem(quint64 file, const QString &path, const QString &disposition,
                            quint64 skippedRoot) const;
    // 日期：2026-11-05；磁盘记录必须与规范编码一致，额外字段和宽松数字转换均拒绝。
    QJsonObject decode(quint64 file, const QByteArray &bytes) const;
    // 日期：2026-11-05；固定SQL失败统一返回磁盘错误，不暴露私有本机路径。
    void sql(const QString &statement) const;
    // 日期：2026-11-05；构造失败和正常析构共用连接回收，避免重试累积Qt数据库连接。
    void close();
    StrongManifest &manifest_;
    QString conflict_;
    QByteArray binding_;
    QJsonObject manifestInfo_;
    quint64 expectedEntries_ = 0;
    qint64 expectedBytes_ = 0;
    quint64 next_ = 1;
    QString connection_;
    SqliteCacheCredit cacheCredit_{1024};
    QSqlDatabase database_;
    std::unique_ptr<QLockFile> ownership_;
};
} // namespace dukto
