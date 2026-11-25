#pragma once

#include <QJsonObject>

namespace dukto {
class BufferCredit final {
  public:
    // 日期：2026-11-05；进程共用 128 MiB 应用缓冲额度，数据类合计不能占用 8 MiB 控制保留额。
    explicit BufferCredit(qint64 bytes, bool data = false);
    // 日期：2026-11-04；异常退栈与正常退出均精确归还额度，令牌本身不分配对应大小的数据。
    ~BufferCredit();
    BufferCredit(const BufferCredit &) = delete;
    BufferCredit &operator=(const BufferCredit &) = delete;
    // 日期：2026-11-05；认证后把已有 TLS 授信原子转为数据类；失败保持原分类且不重复申请内存。
    void classifyAsData();
    // 日期：2026-11-04；只输出本进程可计量应用缓冲授信，不把 RSS、内核 socket 或 TLS 库堆称为额度。
    static QJsonObject usage();

  private:
    qint64 bytes_;
    bool data_;
};
} // namespace dukto
