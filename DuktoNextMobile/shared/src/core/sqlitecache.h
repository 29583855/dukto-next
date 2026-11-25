#pragma once

#include "buffercredit.h"
#include <QSqlDatabase>

namespace dukto {
class SqliteCacheCredit final {
  public:
    // 日期：2026-11-05；打开 SQLite 前取得主库与临时库页缓存目标的共用授信；任务控制保留小额度。
    explicit SqliteCacheCredit(int mainKiB, bool control = false);
    SqliteCacheCredit(const SqliteCacheCredit &) = delete;
    SqliteCacheCredit &operator=(const SqliteCacheCredit &) = delete;
    // 日期：2026-11-05；禁止文件映射，临时数据落盘并回读实际配置；页缓存目标不等于 SQLite
    // 总堆上限。
    void configure(const QSqlDatabase &database) const;

  private:
    BufferCredit credit_;
    int mainKiB_;
};
} // namespace dukto
