#include "core/catalog.h"
#include "core/discovery.h"
#include "core/endpoint.h"
#include "core/error.h"
#include "core/files.h"
#include "core/identity.h"
#include "core/legacy.h"
#include "core/sourcefile.h"
#include "input.h"
#include "servicecommands.h"

#include <QCommandLineParser>
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSettings>
#include <QSqlDatabase>
#include <QSslSocket>
#include <QStandardPaths>
#include <QTcpServer>
#include <QTextStream>
#include <QTimer>
#include <csignal>

namespace {
volatile std::sig_atomic_t interrupted = 0;

// 日期：2026-11-04；信号处理器只写标记，不调用非信号安全的 Qt 或磁盘接口。
void interruptHandler(int) {
    interrupted = 1;
}

// 日期：2026-11-04；帮助/版本同样使用 UTF-8，避免受系统 ANSI 代码页影响。
void printText(const QString &text) {
    QTextStream stream(stdout);
    stream.setCodec("UTF-8");
    stream << text;
    stream.flush();
}

// 日期：2026-11-05；JSON 模式逐行输出事件，日志不混入标准输出。
void output(const QJsonObject &event, bool json) {
    QTextStream stream(stdout);
    stream.setCodec("UTF-8");
    if (json)
        stream << QJsonDocument(event).toJson(QJsonDocument::Compact) << '\n';
    else if (event.value("event") == "devices") {
        const auto peers = event.value("peers").toArray();
        if (peers.isEmpty())
            stream << QStringLiteral("未发现设备；可使用 --to 指定地址\n");
        for (const auto &value : peers) {
            const auto peer = value.toObject();
            stream << peer.value("name").toString() << " at " << peer.value("host").toString()
                   << " (" << peer.value("platform").toString() << ") "
                   << peer.value("address").toString() << ':' << peer.value("port").toInt() << '\n';
        }
    } else if (event.value("event") == "receipt") {
        stream << event.value("taskId").toString() << ' ' << event.value("state").toString() << ' '
               << event.value("bytes").toString() << '/' << event.value("total").toString()
               << " B\n";
        for (const auto &value : event.value("files").toArray()) {
            const auto file = value.toObject();
            stream << file.value("sequence").toString() << ' ' << file.value("source").toString()
                   << " -> " << file.value("path").toString() << " ("
                   << file.value("bytes").toString() << " B) " << file.value("sha256").toString()
                   << '\n';
        }
    } else if (event.value("event") == "listing") {
        stream << event.value("share").toString() << ':' << event.value("path").toString() << '\n';
        for (const auto &value : event.value("entries").toArray()) {
            const auto entry = value.toObject();
            const auto name =
                QJsonDocument(QJsonArray{entry.value("name")}).toJson(QJsonDocument::Compact);
            stream << entry.value("type").toString() << ' ' << entry.value("bytes").toString()
                   << " B " << QString::fromUtf8(name.mid(1, name.size() - 2)) << '\n';
        }
        if (!event.value("cursor").toString().isEmpty())
            stream << "cursor=" << event.value("cursor").toString() << '\n';
    } else if (event.value("event") == "clients") {
        for (const auto &value : event.value("entries").toArray()) {
            const auto client = value.toObject();
            stream << client.value("client").toString()
                   << (client.value("revoked").toBool() ? QStringLiteral(" 已撤销")
                                                        : QStringLiteral(" 有效"))
                   << QStringLiteral(" 修订 ") << client.value("revision").toString() << '\n';
            for (const auto &value : client.value("grants").toArray()) {
                const auto grant = value.toObject();
                QStringList rights;
                if (grant["browse"].toBool())
                    rights.append(QStringLiteral("浏览"));
                if (grant["download"].toBool())
                    rights.append(QStringLiteral("下载"));
                if (grant["upload"].toBool())
                    rights.append(QStringLiteral("上传"));
                stream << "  " << grant["share"].toString() << ": "
                       << rights.join(QStringLiteral("、")) << '\n';
            }
        }
        if (event.value("more").toBool())
            stream << "cursor=" << event.value("after").toString() << '\n';
        else if (event.value("entries").toArray().isEmpty())
            stream << QStringLiteral("没有更多客户端\n");
    } else if (event.value("event") == "byte-progress") {
        stream << QStringLiteral("已接收 ") << event.value("receivedBytes").toString() << '/'
               << event.value("total").toString() << QStringLiteral(" B；已校验落盘 ")
               << event.value("bytes").toString() << QStringLiteral(" B；恢复 ")
               << event.value("restoredBytes").toString() << " B; "
               << QString::number(event.value("bytesPerSecond").toDouble() / 1048576.0, 'f', 2)
               << " MiB/s; ETA="
               << (event.value("etaSeconds").isNull()
                       ? QString("?")
                       : QString::number(event.value("etaSeconds").toDouble(), 'f', 0))
               << QStringLiteral(" s（仍需最终校验和提交）\n");
    } else if (event.contains("values")) {
        const auto values = event.value("values").toObject();
        for (auto iterator = values.begin(); iterator != values.end(); ++iterator)
            stream << iterator.key() << " = " << iterator.value().toVariant().toString() << '\n';
    } else
        stream << event.value("event").toString() << " [" << event.value("stage").toString() << "] "
               << event.value("message").toString() << ' ' << event.value("path").toString() << ' '
               << event.value("bytes").toString() << '\n';
    stream.flush();
}

// 日期：2026-11-04；独立 CLI 自查运行依赖，不启动图形会话或自动更改配置。
int doctor(bool json) {
    const bool sqlite = QSqlDatabase::isDriverAvailable("QSQLITE");
    const bool tls = QSslSocket::supportsSsl();
    output({{"eventVersion", 1},
            {"event", "doctor"},
            {"qt", qVersion()},
            {"cxxStandard", "C++14"},
            {"sqlite", sqlite},
            {"tls", tls},
            {"tlsBuild", QSslSocket::sslLibraryBuildVersionString()},
            {"tlsRuntime", QSslSocket::sslLibraryVersionString()},
            {"config", QStandardPaths::writableLocation(QStandardPaths::AppConfigLocation)},
            {"message",
             sqlite && tls ? QStringLiteral("核心依赖可用") : QStringLiteral("核心依赖不完整")}},
           json);
    return sqlite && tls ? 0 : 2;
}
} // namespace

// 日期：2026-11-05；三平台控制台入口严格核对传输策略，解析或传输失败返回明确非零退出码。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QCoreApplication::setApplicationName("dukto-cli");
    QCoreApplication::setOrganizationName("DuktoNext");
    QCoreApplication::setApplicationVersion(DUKTO_VERSION);
    std::signal(SIGINT, interruptHandler);
    std::signal(SIGTERM, interruptHandler);
#ifdef Q_OS_WIN
    std::signal(SIGBREAK, interruptHandler);
#endif
    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("Dukto Next 独立命令行传输工具（C++14/Qt5）"));
    parser.addHelpOption();
    parser.addVersionOption();
    parser.addPositionalArgument(
        "command", "discover / send / send-text / receive / receipts / "
                   "serve / pair / auth / rotate / list / upload / download / tasks / task "
                   "/ pause / cancel / resume / doctor / config / help");
    parser.addPositionalArgument("arguments", "config show / config set <key> <value>",
                                 "[arguments...]");
    parser.addOptions(
        {{{"j", "json"}, QStringLiteral("输出 UTF-8 JSONL")},
         {"to", QStringLiteral("发送目标 IP 或主机名"), "host"},
         {"port", QStringLiteral("TCP 端口"), "port", "4644"},
         {"bind", QStringLiteral("接收监听地址"), "address", "0.0.0.0"},
         {"path", QStringLiteral("输入文件/目录，可重复"), "path"},
         {"output", QStringLiteral("接收目录"), "directory"},
         {"file", QStringLiteral("发送 UTF-8 文本文件，- 表示标准输入"), "file"},
         {"timeout", QStringLiteral("无进展超时秒数"), "seconds", "30"},
         {"retries", QStringLiteral("新版上传/下载/继续的网络重试次数：0..3，默认手动恢复"),
          "count", "0"},
         {"deadline-seconds",
          QStringLiteral("新版上传/下载/继续的总时限：1..604800 秒，含扫描与排队"), "seconds",
          "86400"},
         {"on-conflict",
          QStringLiteral("新版上传/下载冲突策略：rename（默认保留双方）或 fail；恢复沿用原策略"),
          "policy", "rename"},
         {"threads", QStringLiteral("新版上传/下载/继续的数据通道数：1/2/4/8/16"), "count", "1"},
         {"duration", QStringLiteral("设备发现持续秒数（1–3600）"), "seconds", "3"},
         {"config-file", QStringLiteral("使用独立 INI 配置文件"), "path"},
         {"state-directory", QStringLiteral("任务明细保存目录"), "directory"},
         {"server-name", QStringLiteral("服务证书 SAN 的 IP/主机名，可重复（serve init）"), "name"},
         {"profile", QStringLiteral("本地服务器资料别名"), "alias", "default"},
         {"request-id", QStringLiteral("稳定传输请求 UUID；中断后使用相同值重试"), "uuid"},
         {"remote-path", QStringLiteral("上传目标目录或下载源的共享内相对路径"), "path"},
         {"fingerprint", QStringLiteral("已核对的服务器证书 SHA256 指纹（公开值）"), "hex"},
         {"credential-file", QStringLiteral("受保护的一次性配对文件"), "path"},
         {"client", QStringLiteral("本地服务管理的客户端 UUID"), "id"},
         {"share", QStringLiteral("授权共享名称，可重复"), "name"},
         {"allow-browse", QStringLiteral("明确允许浏览共享")},
         {"allow-download", QStringLiteral("明确允许下载共享内容")},
         {"allow-upload", QStringLiteral("明确允许上传到共享")},
         {"session-seconds",
          QStringLiteral("认证会话有效期 1..86400 秒，默认 24 小时（serve session set）"),
          "seconds"},
         {"cursor", QStringLiteral("目录浏览或本机客户端列表的下一页游标"), "cursor"},
         {"all", QStringLiteral("连续输出目录、任务或客户端全部页，不累积全部结果")},
         {"task", QStringLiteral("任务 UUID（receipts show 或 task/pause/cancel/resume）"), "id"},
         {"after", QStringLiteral("明细分页的起始序号"), "sequence", "0"},
         {"once", QStringLiteral("接收一个批次后退出")},
         {"non-interactive", QStringLiteral("禁止等待交互式输入")}});
    if (!parser.parse(app.arguments())) {
        output(dukto::Error(dukto::ExitCode::Config, parser.errorText(), "arguments").json(),
               parser.isSet("json"));
        return 2;
    }
    if (parser.isSet("version")) {
        printText(QString("dukto-cli %1\n").arg(DUKTO_VERSION));
        return 0;
    }
    if (parser.isSet("help")) {
        printText(parser.helpText());
        return 0;
    }
    const bool json = parser.isSet("json");
    try {
        const auto args = parser.positionalArguments();
        const auto command = args.value(0, "help");
        if (command == "help") {
            printText(parser.helpText());
            return 0;
        }
        if (parser.isSet("on-conflict")) {
            if ((command != "upload" && command != "download") ||
                parser.values("on-conflict").size() != 1)
                throw dukto::Error(
                    dukto::ExitCode::Config,
                    QStringLiteral("--on-conflict 仅用于新版 upload/download，恢复沿用原策略"),
                    "arguments");
            dukto::checkedConflictPolicy(parser.value("on-conflict"));
        }
        if (parser.isSet("threads") && parser.value("threads") != "1" && command != "upload" &&
            command != "download" && command != "resume")
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("多通道仅适用于新版 upload/download/resume"),
                               "arguments");
        if ((parser.isSet("retries") || parser.isSet("deadline-seconds")) && command != "upload" &&
            command != "download" && command != "resume")
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("重试与总时限仅适用于新版 upload/download/resume"),
                               "arguments");
        if (parser.values("retries").size() > 1 || parser.values("deadline-seconds").size() > 1)
            throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("重试与总时限选项不能重复"),
                               "arguments");
        if (command == "doctor")
            return doctor(json);
        std::unique_ptr<QSettings> configuration;
        if (parser.isSet("config-file"))
            configuration.reset(new QSettings(parser.value("config-file"), QSettings::IniFormat));
        else
            configuration.reset(new QSettings);
        auto &settings = *configuration;
        const auto stateDirectory =
            parser.isSet("state-directory")
                ? parser.value("state-directory")
                : QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
        if (command == "serve" || command == "pair" || command == "auth" || command == "rotate" ||
            command == "list" || command == "upload" || command == "download" ||
            command == "tasks" || command == "task" || command == "pause" || command == "cancel" ||
            command == "resume")
            return runServiceCommand(
                parser, args, stateDirectory,
                [json](const QJsonObject &event) { output(event, json); },
                []() { return interrupted != 0; });
        if (command == "receipts") {
            bool validSequence = false;
            const auto after = parser.value("after").toLongLong(&validSequence);
            if (args.value(1) != "show" || parser.value("task").isEmpty() || !validSequence ||
                after < 0)
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("用法：receipts show --task ID [--after 序号]"),
                                   "arguments");
            dukto::Catalog catalog(QDir(stateDirectory).filePath("receipts.sqlite"));
            auto result = catalog.task(parser.value("task"));
            result.insert("eventVersion", 1);
            result.insert("event", "receipt");
            result.insert("files", catalog.page(parser.value("task"), after));
            output(result, json);
            return 0;
        }
        if (settings.status() != QSettings::NoError)
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("配置文件不可读取或格式无效"), "config");
        if (command == "config") {
            if (args.value(1) == "show") {
                QJsonObject data;
                for (const auto &key : settings.allKeys())
                    data.insert(key, QJsonValue::fromVariant(settings.value(key)));
                output({{"eventVersion", 1}, {"event", "config"}, {"values", data}}, json);
                return 0;
            }
            if (args.value(1) == "set" && args.size() == 4 &&
                QStringList{"output", "server", "timeout", "port", "bind", "username"}.contains(
                    args[2])) {
                if ((args[2] == "timeout" && (args[3].toInt() <= 0 || args[3].toInt() > 86400)) ||
                    (args[2] == "port" && (args[3].toInt() <= 0 || args[3].toInt() > 65535)) ||
                    (args[2] == "bind" && QHostAddress(args[3]).isNull()) ||
                    (args[2] == "output" && !QFileInfo(args[3]).isDir()))
                    throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("配置值无效"),
                                       "config");
                if (args[2] == "server")
                    dukto::parseEndpoint(args[3], 4644);
                settings.setValue(args[2], args[3]);
                settings.sync();
                if (settings.status() != QSettings::NoError)
                    throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("配置保存失败"),
                                       "config");
                output({{"eventVersion", 1},
                        {"event", "config"},
                        {"message", QStringLiteral("配置已保存")}},
                       json);
                return 0;
            }
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("用法：config show 或 config set <key> <value>"),
                               "config");
        }
        bool portValid = false;
        // 日期：2026-11-04；命令行显式参数优先于配置，配置实际接入默认值。
        const auto value = [&parser, &settings](const QString &key) {
            return parser.isSet(key) ? parser.value(key)
                                     : settings.value(key, parser.value(key)).toString();
        };
        const auto port = value("port").toUInt(&portValid);
        const auto seconds = value("timeout").toInt();
        if (!portValid || port == 0 || port > 65535 || seconds <= 0 || seconds > 86400)
            throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("端口或超时参数超出范围"),
                               "arguments");
        dukto::LegacyRequest request;
        request.port = static_cast<quint16>(port);
        request.timeoutMs = seconds * 1000;
        QTimer signalTimer;
        signalTimer.setInterval(50);
        if (command == "discover") {
            const int duration = parser.value("duration").toInt();
            if (duration < 1 || duration > 3600)
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("发现时长须在 1–3600 秒内"), "arguments");
            dukto::Discovery discovery;
            if (!discovery.start(
                    request.port,
                    settings
                        .value("username", qEnvironmentVariable(
                                               "USERNAME", qEnvironmentVariable("USER", "User")))
                        .toString()))
                throw dukto::Error(dukto::ExitCode::Network, discovery.errorString(), "discover");
            // 日期：2026-11-04；最终输出有界快照，等待期间保持取消可响应。
            QTimer::singleShot(duration * 1000, &app, [&app, &discovery, json]() {
                output({{"eventVersion", 1}, {"event", "devices"}, {"peers", discovery.peers()}},
                       json);
                app.quit();
            });
            // 日期：2026-11-04；服务被信号停止时也输出结构化取消结果，不能只改变退出码。
            QObject::connect(&signalTimer, &QTimer::timeout, &app, [&app, json]() {
                if (interrupted) {
                    output(dukto::Error(dukto::ExitCode::Cancelled,
                                        QStringLiteral("已请求取消设备发现"), "discover")
                               .json(),
                           json);
                    app.exit(7);
                }
            });
            signalTimer.start();
            return app.exec();
        }
        if (command == "receive") {
            request.output = value("output");
            if (request.output.isEmpty())
                request.output = QStandardPaths::writableLocation(QStandardPaths::DownloadLocation);
            if (!QFileInfo(request.output).isDir())
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("请指定存在的 --output 接收目录"), "arguments");
            dukto::LegacyListener listener(request.output, request.timeoutMs, nullptr,
                                           QDir(stateDirectory).filePath("receipts.sqlite"));
            const QHostAddress address(value("bind"));
            if (address.isNull() || !listener.listen(address, request.port))
                throw dukto::Error(dukto::ExitCode::Network, listener.errorString(), "listen");
            // 日期：2026-11-04；主线程消费受限频率进度事件。
            QObject::connect(&listener, &dukto::LegacyListener::event, &app,
                             [json](const QJsonObject &event) { output(event, json); });
            // 日期：2026-11-04；仅 --once 模式在一个批次后退出，服务模式继续监听。
            QObject::connect(&listener, &dukto::LegacyListener::result, &app,
                             [&app, &parser, json](int code, const QJsonObject &event) {
                                 output(event, json);
                                 if (parser.isSet("once"))
                                     app.exit(code);
                             });
            // 日期：2026-11-04；输出取消请求后退出事件循环，监听器析构会等待活动写入清理完成。
            QObject::connect(&signalTimer, &QTimer::timeout, &app, [&app, json]() {
                if (interrupted) {
                    output(dukto::Error(dukto::ExitCode::Cancelled,
                                        QStringLiteral("已请求停止接收"), "listen")
                               .json(),
                           json);
                    app.exit(7);
                }
            });
            signalTimer.start();
            output({{"eventVersion", 1},
                    {"event", "listening"},
                    {"address", listener.serverAddress().toString()},
                    {"port", listener.serverPort()}},
                   json);
            return app.exec();
        }
        if (command != "send" && command != "send-text")
            throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("未知命令：") + command,
                               "arguments");
        const auto endpoint = dukto::parseEndpoint(
            parser.isSet("to") ? parser.value("to") : settings.value("server").toString(),
            request.port);
        request.host = endpoint.host;
        request.port = endpoint.port;
        request.paths = parser.values("path");
        request.textMode = command == "send-text";
        if (request.host.isEmpty() || (!request.textMode && request.paths.isEmpty()))
            throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("缺少 --to 或 --path"),
                               "arguments");
        if (request.textMode) {
            const auto path = parser.value("file");
            if (path.isEmpty())
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("请指定 --file，标准输入使用 --file -"),
                                   "arguments");
            if (path == "-") {
                // 日期：2026-11-04；输入管道不关闭时仍可超时或取消，避免阻塞整个 CLI。
                request.text = readStandardInput(
                    request.timeoutMs, []() { return interrupted != 0; },
                    !parser.isSet("non-interactive"));
            } else {
                dukto::SourceFile source(path);
                auto &file = source.device();
                request.text = file.read(dukto::MaxTextBytes + 1);
                if (file.error() != QFileDevice::NoError)
                    throw dukto::Error(dukto::ExitCode::Disk, file.errorString(), "read");
                source.verify();
            }
            if (request.text.size() > dukto::MaxTextBytes ||
                QString::fromUtf8(request.text).toUtf8() != request.text)
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("文本必须是有效 UTF-8，且不超过 8 MiB"), "read");
        }
        dukto::LegacyJob job(request);
        // 日期：2026-11-04；只在主线程打印，保持 JSON 行完整。
        QObject::connect(&job, &dukto::LegacyJob::event, &app,
                         [json](const QJsonObject &event) { output(event, json); });
        // 日期：2026-11-04；发送结果统一转换为进程退出码。
        QObject::connect(&job, &dukto::LegacyJob::result, &app,
                         [&app, json](int code, const QJsonObject &event) {
                             output(event, json);
                             app.exit(code);
                         });
        // 日期：2026-11-04；工作线程在阻塞等待期间仍能及时取消。
        QObject::connect(&signalTimer, &QTimer::timeout, &app, [&job]() {
            if (interrupted)
                job.cancel();
        });
        signalTimer.start();
        job.start();
        return app.exec();
    } catch (const dukto::Error &error) {
        output(error.json(), json);
        return static_cast<int>(error.code);
    } catch (const std::exception &error) {
        output(dukto::Error(dukto::ExitCode::Runtime, QString::fromUtf8(error.what())).json(),
               json);
        return 1;
    }
}
