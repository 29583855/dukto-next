#pragma once

#include <QJsonObject>

namespace dukto {
class DataFileCredit final {
  public:
    // 日期：2026-11-06；全进程至多32个传输数据文件；打开前申请，耗尽立即报繁忙而不持资源等待。
    DataFileCredit();
    // 日期：2026-11-06；调用者先关闭原生数据文件，正常和异常退出均归还同一份额度。
    ~DataFileCredit();
    DataFileCredit(const DataFileCredit &) = delete;
    DataFileCredit &operator=(const DataFileCredit &) = delete;
    // 日期：2026-11-06；仅报告数据文件授信，目录、SQLite、私有配置和属性句柄另行管理。
    static QJsonObject usage();
};
} // namespace dukto
