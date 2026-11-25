#pragma once

#include <QHostAddress>
#include <QJsonObject>
#include <QSettings>

namespace dukto {
struct DiagnosticOptions {
    QString configurationFile;
    QString stateDirectory;
    QString outputDirectory;
    bool requireConfiguration = false;
    bool requireStateDirectory = false;
    bool requireOutputDirectory = false;
    bool checkPort = false;
    QHostAddress bindAddress = QHostAddress::AnyIPv4;
    quint16 port = 4644;
    bool listenerActive = false;
};
// 日期：2026-11-07；固定白名单检查配置/目录/运行库/监听，只返回状态，不收集配置值和文件正文。
QJsonObject collectDiagnostics(QSettings &settings, const DiagnosticOptions &options);
// 日期：2026-11-07；至多64KiB JSON同目录原子发布，目标已存在或经过链接时拒绝且不覆盖。
void exportDiagnostics(const QJsonObject &report, const QString &destination);
} // namespace dukto
