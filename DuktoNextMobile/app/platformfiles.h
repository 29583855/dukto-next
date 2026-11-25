#pragma once

#include <QStringList>
#include <functional>

namespace mobile {
using FileResult = std::function<void(QStringList, QString)>;
// 日期：2026-11-25；系统选择授权文件并异步暂存，返回稳定沙箱路径及具体错误。
void selectDocuments(bool folder, FileResult done);
// 日期：2026-11-25；将用户选中的已收文件交给系统导出，成功与取消分别反馈。
void exportDocument(const QString &path, FileResult done);
// 日期：2026-11-25；关闭当前原生选择器，避免超时后产生迟到回调。
void cancelDocumentPicker();
} // namespace mobile
