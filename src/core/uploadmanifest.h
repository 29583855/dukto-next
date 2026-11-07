#pragma once

#include "files.h"
#include "strongmanifest.h"
#include <QDateTime>

namespace dukto {
struct ClientProfile;

class UploadManifest final {
  public:
    // 日期：2026-11-06；独占请求源清单，首次扫描后持久冻结；重启只读重验，不访问源目录。
    UploadManifest(PrivateStore &store, const QUuid &request, const ClientProfile &profile,
                   const QString &share, const QString &relative, ConflictPolicy conflict,
                   const QStringList &paths, const std::atomic_bool *cancel = nullptr,
                   const std::function<void()> &check = {});
    // 日期：2026-11-06；引用仅属于当前工作线程；包装对象覆盖上传及网络重试的完整生命周期。
    StrongManifest &get() const;

  private:
    std::unique_ptr<QLockFile> ownership_;
    std::unique_ptr<StrongManifest> manifest_;
};

// 日期：2026-11-07；独占维护下按原请求回收七天前未发布的源扫描库，冻结及幂等记录始终保留。
QJsonObject cleanupUploadScan(PrivateStore &store, const QUuid &request, const QDateTime &now,
                              bool apply, const std::function<void()> &check = {});
} // namespace dukto
