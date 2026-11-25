#pragma once

#include <QStringList>
#include <QUrl>
#include <QVariantMap>
#include <functional>

namespace mobile {
using FileResult = std::function<void(QStringList, QString)>;
// 日期：2026-11-25；系统选择授权文件并异步暂存，返回稳定沙箱路径及具体错误。
void selectDocuments(bool folder, FileResult done);
// 日期：2026-11-25；将用户选中的已收文件交给系统导出，成功与取消分别反馈。
void exportDocument(const QString &path, FileResult done);
// 日期：2026-11-25；关闭当前原生选择器，避免超时后产生迟到回调。
void cancelDocumentPicker();
// 日期：2026-11-25；Android申请或停止活动任务前台服务，其余平台返回不支持。
bool setBackgroundTransfer(bool active);
// 日期：2026-11-25；读取Android服务是否仍持有后台资格。
bool backgroundTransferAlive();
// 日期：2026-11-25；取走系统通知取消、超时或服务终止的请求。
bool takeBackgroundStop();
// 日期：2026-11-25；iOS申请有限后台收尾时间，不提供长期后台监听。
void beginBackgroundCleanup();
// 日期：2026-11-25；收尾完成或回到前台后归还iOS后台时间。
void endBackgroundCleanup();
// 日期：2026-11-25；返回待处理系统分享的计数、有界文本及错误，不自动发送。
QVariantMap sharedDocuments();
// 日期：2026-11-25；明确发送时导入授权文件，复用同一配额与流式事务。
void importSharedDocuments(FileResult done);
// 日期：2026-11-25；显式清除文本或整份分享，不删除提供器原文件。
void discardSharedDocuments(bool textOnly);
// 日期：2026-11-25；iOS接收系统打开文档事件，保存安全作用域至导入完成。
bool acceptSharedUrl(const QUrl &url);
} // namespace mobile
