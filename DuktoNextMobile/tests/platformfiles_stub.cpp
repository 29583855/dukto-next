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
