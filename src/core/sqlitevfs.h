#pragma once
#include <QByteArray>
#include <memory>
#include <sqlite3.h>

namespace dukto {
struct SqliteFileEvent {
    enum class Action {
        Open,
        Write,
        Truncate,
        SizeHint,
        MapSharedMemory,
        UnmapSharedMemory,
        Delete,
        Close
    };
    Action action = Action::Open;
    quint64 file = 0;
    QByteArray name;
    int flags = 0;
    qint64 offset = 0;
    qint64 bytes = 0;
    bool extend = false;
};

class SqliteFilePolicy {
  public:
    // 日期：2026-11-07；策略寿命覆盖数据库及其所有旁路句柄，异常不得越过SQLite的C回调。
    virtual ~SqliteFilePolicy() = default;
    // 日期：2026-11-07；真实写入/扩展之前调用；拒绝返回SQLite错误码，不得依赖提交后检查。
    virtual int before(const SqliteFileEvent &event) noexcept = 0;
    // 日期：2026-11-07；原生调用后报告实际结果；失败可能已部分写入，不能直接按请求量退款。
    virtual void after(const SqliteFileEvent &event, int result) noexcept = 0;
};

class SqliteVfs final {
  public:
    // 日期：2026-11-07；每连接独立命名VFS，SQLite派生的日志/临时库使用同一策略，不替换系统默认VFS。
    explicit SqliteVfs(std::shared_ptr<SqliteFilePolicy> policy = {});
    // 日期：2026-11-07；调用方先关闭全部SQLite句柄，再注销本连接VFS；策略不被全局注册表永久保留。
    ~SqliteVfs();
    SqliteVfs(const SqliteVfs &) = delete;
    SqliteVfs &operator=(const SqliteVfs &) = delete;
    // 日期：2026-11-07；只返回内部随机VFS名称，业务文件路径和URI由驱动正常转义。
    QByteArray name() const;

  private:
    struct Implementation;
    std::unique_ptr<Implementation> implementation_;
};
} // namespace dukto
