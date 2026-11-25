#pragma once
#include <QCommandLineParser>
#include <QJsonObject>
#include <functional>

// 日期：2026-11-08；三平台共用显式状态域管理入口，全部数字先校验再接触状态目录。
int runStateCommand(const QCommandLineParser &parser, const QStringList &arguments,
                    const std::function<void(const QJsonObject &)> &output,
                    const std::function<bool()> &interrupted);
