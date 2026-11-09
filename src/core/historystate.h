#pragma once

#include "privatestore.h"
#include <memory>

class QSqlDatabase;

namespace dukto {
class HistoryState final {
  public:
    // 日期：2026-11-09；固定两种历史库迁入受保护共享根，原库保留并持续持有SQLite读事务。
    static std::shared_ptr<HistoryState> open(const QString &parent, const QString &name,
                                              std::function<void()> check = {});
    // 日期：2026-11-09；接收明细旧路径与已迁移路径统一定位同一状态父目录，不按任意文件名迁移。
    static std::shared_ptr<HistoryState> catalog(const QString &path);
    // 日期：2026-11-09；先关闭旧库的读事务和原生连接，再归还历史根与预算域共享资格。
    ~HistoryState();
    // 日期：2026-11-09；每次返回路径前重验受保护根及数据库权限，不返回旧库作为写入目标。
    QString path() const;
    // 日期：2026-11-09；开库后以SQLite实际持有的句柄交叉核验受保护路径，禁止路径换代接管连接。
    void validate(const QSqlDatabase &database) const;

  private:
    // 日期：2026-11-09；只由工厂初始化，迁移失败不会泄漏旧SQLite连接或源读锁。
    HistoryState();
    struct Legacy;
    std::shared_ptr<PrivateStore> store_;
    std::unique_ptr<Legacy> legacy_;
    QString name_;
};
} // namespace dukto
