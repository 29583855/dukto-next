#pragma once

#include "sqlitecache.h"
#include <QSqlDatabase>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <atomic>
#include <functional>
#include <memory>

namespace dukto {
struct Entry {
    QString source;
    QString relative;
    qint64 size = 0;
    qint64 modified = 0;
};

class Manifest final {
  public:
    // 日期：2026-11-04；在临时磁盘数据库中建立传输清单，限制 SQLite 缓存与页数。
    Manifest();
    // 日期：2026-11-04；先销毁查询与连接，再删除临时数据库文件。
    ~Manifest();
    // 日期：2026-11-04；流式枚举普通文件与目录，拒绝链接及特殊文件。
    void scan(const QStringList &paths, const std::atomic_bool *cancel = nullptr,
              const std::function<void()> &checkpoint = {});
    // 日期：2026-11-04；从磁盘清单顺序读取下一项，内存不随目录条目数增长。
    bool next(Entry &entry);
    // 日期：2026-11-04；重置有界游标以重新遍历已扫描清单。
    void rewind();
    qint64 count = 0;
    qint64 totalBytes = 0;

  private:
    // 日期：2026-11-04；验证单条条目并保存源文件身份及线上相对路径。
    void append(const QString &path, const QString &relative);
    QTemporaryDir directory_;
    QString connection_;
    SqliteCacheCredit cacheCredit_{2048};
    QSqlDatabase database_;
    std::unique_ptr<QSqlQuery> cursor_;
};
} // namespace dukto
