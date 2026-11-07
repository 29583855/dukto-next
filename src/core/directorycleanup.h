#pragma once

#include <QByteArray>
#include <QSqlDatabase>
#include <QSqlQuery>
#include <QString>
#include <functional>

namespace dukto {
class StrongManifest;

struct DirectoryCleanupEntry {
    quint64 id = 0;
    QByteArray spec;
    QString source;
    QString temporary;
    QString target;
    QByteArray native;
    QString state;
};

// 日期：2026-11-07；文件和目录共用清单序号游标，每次只读取一个有界条目。
QString receiveCleanupEntryQuery();

// 日期：2026-11-07；核对目录强清单、映射、随机临时名、SQLite类型及原生身份记录。
DirectoryCleanupEntry readCleanupDirectory(const QSqlQuery &query, StrongManifest &manifest);

// 日期：2026-11-07；只移除身份匹配的空临时目录；FULL意图支持删除后崩溃重入。
QString cleanupReceiveDirectory(QSqlDatabase database, const DirectoryCleanupEntry &entry,
                                const QString &root, const QByteArray &rootIdentity, bool apply,
                                bool resetForResume, bool skipPolicy,
                                const std::function<void()> &check = {});
} // namespace dukto
