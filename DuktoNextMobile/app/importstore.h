#pragma once

#include <QIODevice>
#include <QLockFile>
#include <QSet>
#include <QString>
#include <QTemporaryDir>
#include <functional>
#include <memory>

// 日期：2026-11-25；文档提供器通过流进入有界沙箱，不将content URI冒充本地文件路径。
class ImportStore final {
  public:
    struct Limits {
        qint64 bytes = 16LL * 1024 * 1024 * 1024;
        qint64 reserve = 64LL * 1024 * 1024;
        int entries = 512;
        int depth = 32;
    };
    // 日期：2026-11-25；事务目录创建在应用私有空间，失败事务自动清理。
    ImportStore(const QString &root, Limits limits);
    // 日期：2026-11-25；按相对路径创建有限目录，拒绝点路径、绝对路径及重名。
    bool directory(const QString &relative);
    // 日期：2026-11-25；流式复制并核对声明长度、取消状态、磁盘空间及总量，错误即终止事务。
    bool copy(QIODevice &source, const QString &relative, qint64 expected = -1,
              const std::function<bool()> &cancelled = std::function<bool()>());
    // 日期：2026-11-25；仅完整事务可提交，返回由调用者持有至任务终止的沙箱路径。
    QString commit();
    // 日期：2026-11-25；读取首个具体错误，便于权限及空间问题排查。
    QString error() const;
    // 日期：2026-11-25；提供实际已复制字节，不以提供器上报的总量冒充完成进度。
    qint64 bytes() const;

  private:
    // 日期：2026-11-25；只允许普通相对名称，跨平台统一拒绝特殊段及控制字符。
    bool validate(const QString &relative);
    // 日期：2026-11-25；保留首错并使事务失效，失败后不能提交部分文件。
    bool fail(const QString &message);
    std::unique_ptr<QLockFile> budgetLock_;
    std::unique_ptr<QTemporaryDir> temporary_;
    Limits limits_;
    QSet<QString> entries_;
    QString error_;
    qint64 bytes_ = 0;
    bool committed_ = false;
};
