#pragma once

#include "shares.h"
#include <QElapsedTimer>
#include <QJsonObject>
#include <atomic>
#include <functional>

namespace dukto {
class BrowseStore final {
  public:
    // 日期：2026-11-04；每页有界读取已落盘的目录快照，不把十万文件列表保存在内存。
    explicit BrowseStore(PrivateStore &store, const std::atomic_bool *cancel = nullptr,
                         std::function<void()> reauthorize = {});
    // 日期：2026-11-04；首请求创建有界快照，后续游标绑定主体/共享/路径/期限并验证 HMAC。
    QJsonObject list(const Principal &principal, const QString &share, const QString &relative,
                     const QString &cursor = QString());

  private:
    // 日期：2026-11-04；全局最多四个快照、单主体两个，所有快照及状态总量不超过 256 MiB。
    QString create(const Principal &principal, const QString &share, const QString &relative);
    // 日期：2026-11-04；只回收已过期或无对应元数据的浏览快照，保持有效游标可安全重试。
    void collect() const;
    // 日期：2026-11-04；扫描过程中逐条观察取消，停止时未发布的临时快照自动清理。
    void check() const;
    PrivateStore &store_;
    const std::atomic_bool *cancel_;
    std::function<void()> reauthorize_;
    mutable QElapsedTimer authorizationClock_;
};
} // namespace dukto
