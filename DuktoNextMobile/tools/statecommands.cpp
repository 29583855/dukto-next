#include "statecommands.h"
#include "core/error.h"
#include "core/privatestore.h"
#include "core/statecleanup.h"
#include "core/statedomain.h"
#include "core/statesession.h"
#include <QDir>
#include <QFileInfo>
#include <QJsonArray>

namespace {
using Budget = dukto::StateBudget;

// 日期：2026-11-08；只接受规范非负64位十进制字节数，不接受符号、空白、指数、溢出或前导零。
qint64 amount(const QCommandLineParser &parser, const QString &name) {
    bool ok = false;
    const auto text = parser.value(name);
    const auto value = text.toLongLong(&ok);
    if (!parser.isSet(name) || !ok || value < 0 || QString::number(value) != text)
        throw dukto::Error(dukto::ExitCode::Config,
                           QStringLiteral("预算必须为规范非负64位字节数：--") + name, "arguments");
    return value;
}

// 日期：2026-11-08；五项额度必须明确提供；历史合计遵守既定256MiB上限，不写死正文或全局默认值。
Budget::Limits limits(const QCommandLineParser &parser) {
    Budget::Limits result;
    result.total = amount(parser, "budget-total");
    const QStringList names{"budget-history", "budget-metadata", "budget-body", "budget-unknown"};
    for (int index = 0; index < names.size(); ++index)
        result.categories[index] = amount(parser, names[index]);
    if (result.total < Budget::FileBytes + dukto::StateDomain::MarkerBytes ||
        result.categories[1] < Budget::FileBytes + dukto::StateDomain::MarkerBytes ||
        result.categories[0] > 256 * 1024 * 1024)
        throw dukto::Error(dukto::ExitCode::Config,
                           QStringLiteral("总额/元数据额不足以保存控制区，或历史额超过256MiB"),
                           "arguments");
    return result;
}

} // namespace

// 日期：2026-11-08；查询不创建父目录；初始化/修改/根登记使用独占资格，不隐式迁移旧历史或回收未知项。
int runStateCommand(const QCommandLineParser &parser, const QStringList &arguments,
                    const std::function<void(const QJsonObject &)> &output,
                    const std::function<bool()> &interrupted) {
    const auto group = arguments.value(1);
    const auto operation = arguments.value(2);
    if (group == "gc") {
        if (arguments.size() != 3 || (operation != "preview" && operation != "run") ||
            !parser.isSet("state-directory") || parser.value("state-directory").isEmpty() ||
            !QStringList{"service", "transfers", "remote/service", "remote/transfers"}.contains(
                parser.value("state-root")))
            throw dukto::Error(
                dukto::ExitCode::Config,
                QStringLiteral("用法：state gc preview|run --state-directory <目录> "
                               "--state-root service|transfers|remote/service|remote/transfers"),
                "arguments");
        const QStringList allowed{"state-directory", "state-root", "j", "json", "non-interactive"};
        for (const auto &name : parser.optionNames())
            if (!allowed.contains(name) || parser.values(name).size() > 1 ||
                parser.optionNames().count(name) > 1)
                throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("清理选项不适用或重复"),
                                   "arguments");
        const auto check = [&interrupted]() {
            // 日期：2026-11-08；显式维护的取消不跳过未完成候选或清除已有删除意图。
            if (interrupted())
                throw dukto::Error(dukto::ExitCode::Cancelled, QStringLiteral("状态清理已取消"),
                                   "cleanup");
        };
        auto store = dukto::StateSession::observe(parser.value("state-directory"),
                                                  parser.value("state-root"),
                                                  dukto::PrivateStore::Use::Maintenance, check);
        const auto report = dukto::cleanupState(*store, QDateTime::currentDateTimeUtc(),
                                                operation == "run", {}, check);
        output(report);
        return report["errorCount"].toString() == "0" ? 0 : int(dukto::ExitCode::Integrity);
    }
    const bool configuration = group == "budget" && (operation == "init" || operation == "set");
    const bool binding = group == "root" && operation == "bind";
    const bool accounting = group == "root" && operation == "account";
    if (arguments.size() != 3 ||
        !(configuration || binding || accounting ||
          ((group == "budget" || group == "root") && operation == "show")) ||
        !parser.isSet("state-directory") || parser.value("state-directory").isEmpty())
        throw dukto::Error(
            dukto::ExitCode::Config,
            QStringLiteral("用法：state budget init|show|set 或 state root bind|show|account；"
                           "须显式指定--state-directory"),
            "arguments");
    QStringList allowed{"state-directory", "j", "json", "non-interactive"};
    if (configuration)
        allowed += QStringList{"budget-total", "budget-history", "budget-metadata", "budget-body",
                               "budget-unknown"};
    if (group == "root")
        allowed.append("state-root");
    if (group == "budget" && operation == "set")
        allowed.append("budget-revision");
    for (const auto &name : parser.optionNames())
        if (!allowed.contains(name) || parser.values(name).size() > 1 ||
            parser.optionNames().count(name) > 1)
            throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("状态管理选项不适用或重复"),
                               "arguments");
    Budget::Limits requested;
    if (configuration)
        requested = limits(parser);
    quint64 revision = 0;
    if (group == "budget" && operation == "set") {
        bool ok = false;
        const auto text = parser.value("budget-revision");
        revision = text.toULongLong(&ok);
        if (!parser.isSet("budget-revision") || !ok || !revision ||
            QString::number(revision) != text)
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("修改预算须提供查询所得的规范--budget-revision"),
                               "arguments");
    }
    const auto rootName = parser.value("state-root");
    if (group == "root" &&
        !QStringList{"service", "clients", "transfers", "history"}.contains(rootName))
        throw dukto::Error(dukto::ExitCode::Config,
                           QStringLiteral("--state-root须为service、clients、transfers或history"),
                           "arguments");
    const auto check = [&interrupted]() {
        // 日期：2026-11-08；只在未持预算原生锁时检查取消，取消不重置域或退还已有预留。
        if (interrupted())
            throw dukto::Error(dukto::ExitCode::Cancelled, QStringLiteral("状态管理已取消"),
                               "state-budget");
    };
    check();
    const auto parent = parser.value("state-directory");
    if (operation != "init" && !QFileInfo(parent).isDir())
        throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("状态父目录不存在"),
                           "state-budget");
    if (operation == "init" && !QDir().mkpath(parent))
        throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("无法准备状态父目录"),
                           "state-budget");
    dukto::PrivateStore coordinator(QDir(parent).filePath("budget"), operation == "init",
                                    (configuration || accounting)
                                        ? dukto::PrivateStore::Use::Maintenance
                                        : dukto::PrivateStore::Use::Shared);
    if (operation == "init")
        dukto::StateDomain::initialize(coordinator, requested);
    dukto::StateDomain domain(coordinator, check);
    if (group == "budget") {
        output(Budget::report(operation == "set" ? domain.configure(revision, requested)
                                                 : domain.usage(),
                              operation));
    } else {
        dukto::PrivateStore member(QDir(parent).filePath(rootName), binding,
                                   (binding || accounting) ? dukto::PrivateStore::Use::Maintenance
                                                           : dukto::PrivateStore::Use::Shared);
        const auto root = binding ? domain.bind(member) : domain.root(member);
        const auto inventory = accounting ? domain.accountUnknown(member) : QJsonObject();
        auto value = Budget::report(domain.usage(), operation);
        if (accounting) {
            value.insert("inventory", inventory);
            value.insert(
                "message",
                QStringLiteral("已有直接文件占用已持久计量；未知占用保留，生产写前限制仍待接入"));
        }
        value.insert("event", "state-root");
        value.insert("root", rootName);
        value.insert("rootGeneration", root.generation.toString(QUuid::WithoutBraces));
        value.insert("bound", true);
        output(value);
    }
    return 0;
}
