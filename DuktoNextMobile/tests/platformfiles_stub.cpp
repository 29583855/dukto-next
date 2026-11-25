#include "platformfiles.h"

// 日期：2026-11-25；Linux主机测试没有手机提供器，不能将其结果记成SAF或iOS通过。
void mobile::selectDocuments(bool, FileResult done) {
    done({}, QStringLiteral("主机测试不提供手机文档选择器"));
}
// 日期：2026-11-25；测试宿主明确报告不支持原生导出。
void mobile::exportDocument(const QString &, FileResult done) {
    done({}, QStringLiteral("主机测试不提供手机文档导出"));
}
// 日期：2026-11-25；测试替身不持有原生窗口。
void mobile::cancelDocumentPicker() {
}

// 日期：2026-11-25；主机没有手机后台服务，不提供虚假资格。
bool mobile::setBackgroundTransfer(bool) {
    return false;
}
// 日期：2026-11-25；主机后台服务始终未启动。
bool mobile::backgroundTransferAlive() {
    return false;
}
// 日期：2026-11-25；主机无通知停止请求。
bool mobile::takeBackgroundStop() {
    return false;
}
// 日期：2026-11-25；主机收尾接口为空，不计作iOS通过。
void mobile::beginBackgroundCleanup() {
}
// 日期：2026-11-25；主机没有系统后台任务。
void mobile::endBackgroundCleanup() {
}

// 日期：2026-11-25；主机测试无系统分享入口。
QVariantMap mobile::sharedDocuments() {
    return {};
}
// 日期：2026-11-25；测试替身明确拒绝系统分享导入。
void mobile::importSharedDocuments(FileResult done) {
    done({}, QStringLiteral("主机没有系统分享"));
}
// 日期：2026-11-25；主机没有需要释放的分享授权。
void mobile::discardSharedDocuments(bool) {
}
// 日期：2026-11-25；主机不把任意本地URL冒充iOS系统授权。
bool mobile::acceptSharedUrl(const QUrl &) {
    return false;
}
