#pragma once

#include "strongmanifest.h"
#include <QSqlQuery>

namespace dukto {
// 跳过证据校验共用于活动接收和只读完成快照；不访问目标树或修改接收日志。
class ReceiveSkipProof final {
  public:
    // 日期：2026-11-06；复用调用者的固定数据库快照，旧v3日志可明确禁用最终决定表。
    ReceiveSkipProof(QSqlDatabase database, StrongManifest &manifest, bool finalSkipsEnabled)
        : manifest_(manifest), finalSkipsEnabled_(finalSkipsEnabled), database_(database) {
    }
    // 日期：2026-11-06；按磁盘父索引核验准备及最终决定，不递归驻留目录树。
    QJsonObject decision(quint64 file) const;
    // 日期：2026-11-06；最终跳过必须绑定原接收准备和临时项意图，不能凭目标存在推断。
    QJsonObject finalDecision(quint64 file) const;
    // 日期：2026-11-06；只允许合法最终决定覆盖原receive，历史skip不能再次被改写。
    QJsonObject applyFinal(const StrongEntry &entry, const QJsonObject &decision) const;

  private:
    // 日期：2026-11-06；只执行预绑定的只读查询，坏库不能当作空记录或普通跳过。
    void execute(QSqlQuery &query) const;
    StrongManifest &manifest_;
    bool finalSkipsEnabled_;
    QSqlDatabase database_;
};
} // namespace dukto
