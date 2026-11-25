#pragma once

#include <QCommandLineParser>
#include <QJsonObject>
#include <QStringList>
#include <functional>

// 日期：2026-11-04；服务器管理和客户端配对/认证命令共用生产核心，输出只接受规范非敏感事件。
int runServiceCommand(const QCommandLineParser &parser, const QStringList &arguments,
                      const QString &stateDirectory,
                      const std::function<void(const QJsonObject &)> &output,
                      const std::function<bool()> &interrupted);
