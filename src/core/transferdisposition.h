#pragma once

#include "durablereceive.h"

namespace dukto {
class DispositionJournal;
// 日期：2026-11-06；先核验完整原处置，copied有界重读原源，skipped不访问源；授权映射仅用于copied。
QJsonObject
verifyCompletedSource(StrongManifest &manifest, DispositionJournal &outcomes,
                      const std::function<void()> &check = {},
                      const std::function<QString(const StrongEntry &)> &sourceForCopied = {});
// 日期：2026-11-06；只在已协商显式处置时添加规范路径、决定及跳过根，不携带原生身份。
void addTransferDisposition(QJsonObject &object, const DurableReceive::Preparation &value,
                            bool final);
// 日期：2026-11-06；逐项绑定冻结清单并核对准备至完成的单向变化；调用者另检查完整帧字段。
DurableReceive::Preparation
readTransferDisposition(const QJsonObject &object, StrongManifest &manifest, quint64 file,
                        bool final, const DurableReceive::Preparation *prepared = nullptr);
} // namespace dukto
