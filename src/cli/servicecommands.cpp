#include "servicecommands.h"
#include "core/endpoint.h"
#include "core/error.h"
#include "core/expiredtaskcleanup.h"
#include "core/paralleltransfer.h"
#include "core/protocol.h"
#include "core/service.h"
#include "core/sessionpolicy.h"
#include "core/shares.h"
#include "core/strongmanifest.h"
#include "core/transferoperation.h"
#include "core/uploadmanifest.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QRegularExpression>
#include <QTimer>
#include <atomic>
#include <limits>

namespace {
// 日期：2026-11-04；所有授权须显式指定，不因输入共享名就默认开放读写。
QList<dukto::Grant> grants(const QCommandLineParser &parser) {
    QList<dukto::Grant> result;
    for (const auto &name : parser.values("share"))
        result.append({name, parser.isSet("allow-browse"), parser.isSet("allow-download"),
                       parser.isSet("allow-upload")});
    dukto::encodeGrants(result);
    return result;
}

// 日期：2026-11-04；一般状态父目录可以创建，真正的秘密根由 PrivateStore 原生安全创建。
void prepareParent(const QString &directory) {
    if (!QDir().mkpath(directory))
        throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("无法准备状态父目录"), "identity");
}

// 日期：2026-11-04；公开指纹允许来自命令行，秘密凭据仅允许来自已保护文件。
QByteArray fingerprint(const QString &text) {
    static const QRegularExpression format("\\A[0-9a-fA-F]{64}\\z");
    if (!format.match(text).hasMatch())
        throw dukto::Error(dukto::ExitCode::Config,
                           QStringLiteral("请提供核对后的完整 64 位十六进制证书指纹"), "pair");
    return QByteArray::fromHex(text.toLatin1());
}

// 日期：2026-11-04；超时以明确整数解析，服务 TLS/帧总期限同样遵守 1–3600 秒配置。
int timeout(const QCommandLineParser &parser) {
    bool valid = false;
    const auto seconds = parser.value("timeout").toInt(&valid);
    if (!valid || seconds < 1 || seconds > 3600)
        throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("超时须在 1 到 3600 秒之间"),
                           "arguments");
    return seconds * 1000;
}
// 日期：2026-11-05；期限只接受规范十进制，避免负数、溢出和无效文本回退到默认值。
int certificateDays(const QCommandLineParser &parser) {
    const auto text = parser.value("certificate-days");
    bool ok = false;
    const int days = text.toInt(&ok);
    if (!ok || QString::number(days) != text || days < 1 || days > 825)
        throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("证书有效期须为1..825天"),
                           "arguments");
    return days;
}
} // namespace

// 日期：2026-11-07；GUI/CLI复用核心；过期维护先独占状态根，恢复控制仍绑定原请求。
int runServiceCommand(const QCommandLineParser &parser, const QStringList &arguments,
                      const QString &stateDirectory,
                      const std::function<void(const QJsonObject &)> &output,
                      const std::function<bool()> &interrupted) {
    auto command = arguments.value(0);
    const bool resuming = command == "resume";
    if (command == "trust" || command == "profile-info") {
        for (const auto &option :
             QStringList{"to", "port", "server-name", "credential-file", "share", "remote-path",
                         "request-id", "path", "output", "client"})
            if (parser.isSet(option))
                throw dukto::Error(
                    dukto::ExitCode::Config,
                    QStringLiteral("资料证书命令沿用原目标，不接受目标/任务/配对覆盖参数"),
                    "arguments");
        if (command == "profile-info" && parser.isSet("fingerprint"))
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("profile-info为只读操作，不接受证书变更参数"),
                               "arguments");
    }
    if (command == "serve") {
        const auto action = arguments.value(1);
        const auto servicePath = QDir(stateDirectory).filePath("service");
        if (action == "cleanup") {
            const auto operation = arguments.value(2);
            const QUuid owner(parser.value("client"));
            const QUuid id(parser.value("task"));
            bool valid = false;
            const auto after = parser.value("after").toULongLong(&valid);
            const QStringList allowed{"client", "task", "state-directory", "after",
                                      "j",      "json", "non-interactive"};
            for (const auto &option : parser.optionNames()) {
                if (!allowed.contains(option) || parser.values(option).size() > 1 ||
                    parser.optionNames().count(option) > 1)
                    throw dukto::Error(dukto::ExitCode::Config,
                                       QStringLiteral("清理选项无效或重复"), "arguments");
            }
            if (arguments.size() != 3 || (operation != "preview" && operation != "run") ||
                owner.isNull() || id.isNull() || !valid ||
                parser.value("client") != owner.toString(QUuid::WithoutBraces) ||
                parser.value("task") != id.toString(QUuid::WithoutBraces) ||
                parser.value("after") != QString::number(after) ||
                (operation == "run" && parser.isSet("after")))
                throw dukto::Error(
                    dukto::ExitCode::Config,
                    QStringLiteral("用法：serve cleanup preview|run --client UUID --task UUID"),
                    "arguments");
            dukto::PrivateStore store(servicePath, false, dukto::PrivateStore::Use::Maintenance);
            output(dukto::cleanupExpiredUpload(
                store, owner, id, QDateTime::currentDateTimeUtc(), operation == "run", after,
                [&]() {
                    // 日期：2026-11-07；本地信号在每个有界清理安全点观察，中断保留已提交的恢复凭据。
                    if (interrupted())
                        throw dukto::Error(dukto::ExitCode::Cancelled,
                                           QStringLiteral("清理已中断，可再次执行续做"), "cleanup");
                }));
            return 0;
        }
        if (action == "init" || action == "info" || action == "renew") {
            if (arguments.size() != 2)
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("身份命令不接受额外位置参数"), "arguments");
            if (action == "init")
                prepareParent(stateDirectory);
            dukto::PrivateStore store(servicePath, action == "init");
            QJsonObject info;
            if (action == "init")
                info = dukto::initializeIdentity(store, parser.values("server-name"),
                                                 certificateDays(parser))
                           .publicInfo();
            else if (action == "renew")
                info = dukto::renewIdentity(store, fingerprint(parser.value("fingerprint")),
                                            parser.values("server-name"), certificateDays(parser));
            else
                info = dukto::inspectIdentity(store);
            info["sessionSeconds"] = QString::number(dukto::loadSessionSeconds(store));
            info["eventVersion"] = 1;
            info["event"] = "server-identity";
            info["stage"] = action;
            if (action != "renew")
                info["message"] =
                    QStringLiteral("服务器 ID：%1；证书状态：%2；有效期至：%3；SHA-256 指纹：%4")
                        .arg(info["serverId"].toString(), info["certificateStatus"].toString(),
                             info["expiresUtc"].toString(), info["fingerprint"].toString());
            else
                info["message"] = info["message"].toString() + QStringLiteral("；新指纹：") +
                                  info["fingerprint"].toString();
            output(info);
            return 0;
        }
        if (action == "start") {
            if (arguments.size() != 2)
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("服务启动不接受额外位置参数"), "arguments");
            const auto port = parser.isSet("port") ? parser.value("port") : QString("4646");
            const auto endpoint = dukto::parseEndpoint("localhost:" + port, 4646);
            const QHostAddress bind(parser.value("bind"));
            if (bind.isNull())
                throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("监听地址无效"),
                                   "arguments");
            dukto::ServiceListener listener(servicePath, timeout(parser));
            QObject::connect(&listener, &dukto::ServiceListener::event, &listener, output);
            if (!listener.listen(bind, endpoint.port))
                throw dukto::Error(dukto::ExitCode::Network, QStringLiteral("服务端口无法监听"),
                                   "service");
            auto info = listener.publicInfo();
            info["eventVersion"] = 1;
            info["event"] = "service-listening";
            info["port"] = listener.serverPort();
            info["address"] = bind.toString();
            info["message"] = QStringLiteral("新版 TLS 服务已启动");
            output(info);
            QTimer signal;
            signal.setInterval(25);
            QObject::connect(&signal, &QTimer::timeout, &listener, [&]() {
                // 日期：2026-11-04；信号只在 Qt 线程里触发完整服务停止，等待所有活动 TLS 任务清理。
                if (interrupted()) {
                    listener.stop();
                    QCoreApplication::quit();
                }
            });
            signal.start();
            QCoreApplication::exec();
            return interrupted() ? 7 : 0;
        }
        dukto::PrivateStore store(servicePath);
        dukto::loadIdentity(store);
        if (action == "session") {
            const auto operation = arguments.value(2);
            if (arguments.size() != 3 || (operation != "show" && operation != "set") ||
                (operation == "show" && parser.isSet("session-seconds")) ||
                (operation == "set" && parser.values("session-seconds").size() != 1))
                throw dukto::Error(
                    dukto::ExitCode::Config,
                    QStringLiteral(
                        "用法：serve session show 或 serve session set --session-seconds 1..86400"),
                    "arguments");
            if (operation == "set")
                dukto::setSessionSeconds(store, parser.value("session-seconds"));
            output(dukto::sessionPolicyInfo(store));
            return 0;
        }
        dukto::Shares shares(store);
        if (action == "share") {
            const auto operation = arguments.value(2);
            if (arguments.size() != 3)
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("用法：serve share add/remove/list"),
                                   "arguments");
            if (operation == "add") {
                const auto permissions = grants(parser);
                const auto paths = parser.values("path");
                if (permissions.size() != 1 || paths.size() != 1)
                    throw dukto::Error(dukto::ExitCode::Config,
                                       QStringLiteral("每次配置一个 --share 与 --path"),
                                       "arguments");
                shares.set({permissions.first(), paths.first()});
            } else if (operation == "remove") {
                if (parser.values("share").size() != 1)
                    throw dukto::Error(dukto::ExitCode::Config,
                                       QStringLiteral("请指定一个 --share"), "arguments");
                shares.remove(parser.value("share"));
            } else if (operation != "list") {
                throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("共享管理操作无效"),
                                   "arguments");
            }
            QJsonArray values;
            for (const auto &share : shares.all())
                values.append(
                    QJsonObject{{"root", share.root},
                                {"permissions", dukto::encodeGrants({share.permissions})[0]}});
            output({{"eventVersion", 1},
                    {"event", "shares"},
                    {"shares", values},
                    {"message", QStringLiteral("共享配置已读取/更新")}});
            return 0;
        }
        dukto::AuthStore auth(store);
        if (action == "clients") {
            if (arguments.size() != 2)
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("用法：serve clients [--cursor UUID] [--all]"),
                                   "arguments");
            auto after = parser.value("cursor");
            for (int page = 0; page < 1024; ++page) {
                const auto result = auth.clients(after);
                output(result);
                if (!parser.isSet("all") || !result["more"].toBool())
                    return 0;
                const auto following = result["after"].toString();
                if (following <= after)
                    throw dukto::Error(dukto::ExitCode::Integrity,
                                       QStringLiteral("客户端列表游标未前进"), "auth");
                after = following;
            }
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("客户端分页次数已达上限，请重新查询"), "auth");
        }
        if (action == "pairing") {
            if (arguments.size() != 2)
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("配对颁发不接受额外位置参数"), "arguments");
            const auto permissions = grants(parser);
            shares.validate(permissions);
            const auto offer = auth.issue(permissions);
            const auto name =
                "pairing-export-" + QUuid::createUuid().toString(QUuid::WithoutBraces) + ".json";
            store.write(name, dukto::next::encodeControl(
                                  {{"version", 1},
                                   {"credential", QString::fromLatin1(offer.credential.toHex())},
                                   {"expires", offer.expires.toString(Qt::ISODate)}}));
            output({{"eventVersion", 1},
                    {"event", "pairing-issued"},
                    {"expiresUtc", offer.expires.toString(Qt::ISODate)},
                    {"credentialFile", QDir(servicePath).filePath(name)},
                    {"message",
                     QStringLiteral("一次性配对凭据已保存到受保护文件，请安全交付给客户端")}});
            return 0;
        }
        if (action == "revoke" || action == "grant") {
            const QUuid client(parser.value("client"));
            if (arguments.size() != 2 || client.isNull())
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("请指定有效 --client UUID"), "arguments");
            if (action == "revoke")
                auth.revoke(client);
            else {
                const auto permissions = grants(parser);
                shares.validate(permissions);
                auth.setGrants(client, permissions);
            }
            output({{"eventVersion", 1},
                    {"event", "authorization-updated"},
                    {"client", client.toString(QUuid::WithoutBraces)},
                    {"message", QStringLiteral("授权状态已持久更新")}});
            return 0;
        }
        throw dukto::Error(
            dukto::ExitCode::Config,
            QStringLiteral(
                "用法：serve init/info/renew/start/session/share/pairing/clients/grant/revoke"),
            "arguments");
    }
    if (command != "pair" && command != "auth" && command != "rotate" && command != "list" &&
        command != "trust" && command != "profile-info" && command != "upload" &&
        command != "download" && command != "tasks" && command != "task" && command != "pause" &&
        command != "cancel" && command != "task-items" && !resuming)
        throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("远程命令无效"), "arguments");
    if (arguments.size() != 1)
        throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("远程命令不接受额外位置参数"),
                           "arguments");
    prepareParent(stateDirectory);
    dukto::PrivateStore clients(QDir(stateDirectory).filePath("clients"), true);
    const auto alias = parser.value("profile");
    if (command == "profile-info") {
        output(dukto::profileInfo(clients, alias));
        return 0;
    }
    dukto::ClientProfile profile;
    QByteArray pairing;
    if (command == "pair") {
        const auto endpoint = dukto::parseEndpoint(
            parser.value("to"), parser.isSet("port") ? parser.value("port").toInt() : 4646);
        profile = dukto::prepareProfile(clients, alias, endpoint.host, endpoint.port,
                                        parser.isSet("server-name") ? parser.value("server-name")
                                                                    : endpoint.host,
                                        fingerprint(parser.value("fingerprint")));
        const QFileInfo file(parser.value("credential-file"));
        if (parser.value("credential-file").isEmpty())
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("请用 --credential-file 指定受保护配对文件"), "pair");
        dukto::PrivateStore input(file.absolutePath());
        const auto record = dukto::next::parseControl(input.read(file.fileName()));
        const auto text = record["credential"].toString();
        pairing = fingerprint(text);
    } else {
        profile = dukto::loadProfile(clients, alias);
        if (!profile.paired)
            throw dukto::Error(dukto::ExitCode::Permission,
                               QStringLiteral("客户端资料尚未确认配对"), "auth");
        if (command != "rotate" && command != "trust" && !profile.pendingCredential.isEmpty())
            throw dukto::Error(dukto::ExitCode::Permission,
                               QStringLiteral("凭据轮换尚待确认，请用相同资料执行 rotate 后继续"),
                               "profile");
    }
    std::atomic_bool cancelled{false};
    QTimer signal;
    signal.setInterval(25);
    QObject::connect(&signal, &QTimer::timeout, &signal, [&]() {
        // 日期：2026-11-04；原子取消在 TLS 所属线程事件循环里观察，保持三平台信号语义。
        if (interrupted())
            cancelled.store(true);
    });
    signal.start();
    std::unique_ptr<dukto::TransferOperation> operation;
    if (command == "upload" || command == "download" || resuming)
        operation.reset(new dukto::TransferOperation(
            dukto::checkedTransferPolicy(parser.value("retries"), parser.value("deadline-seconds")),
            &cancelled, output));
    const auto stop = operation ? operation->cancellation() : &cancelled;
    if (command == "trust") {
        output(dukto::migrateProfileFingerprint(
            clients, alias, fingerprint(parser.value("old-fingerprint")),
            fingerprint(parser.value("fingerprint")), timeout(parser), &cancelled));
        return 0;
    }
    if (command == "rotate") {
        output(dukto::rotateProfile(clients, alias, timeout(parser), &cancelled));
        return 0;
    }
    std::unique_ptr<dukto::PrivateStore> transferState;
    std::unique_ptr<dukto::UploadManifest> upload;
    QUuid request;
    QUuid resumeId;
    auto share = parser.value("share");
    auto relative = parser.value("remote-path");
    auto conflict = dukto::checkedConflictPolicy(parser.value("on-conflict"));
    if (resuming) {
        resumeId = QUuid(parser.value("task"));
        if (resumeId.isNull() || parser.value("task") != resumeId.toString(QUuid::WithoutBraces) ||
            parser.isSet("request-id") || parser.isSet("share") || parser.isSet("remote-path"))
            throw dukto::Error(
                dukto::ExitCode::Config,
                QStringLiteral("resume 使用 --task 及原 --path 或 --output，任务参数从服务读取"),
                "arguments");
        const auto task = operation->run([&]() {
            // 日期：2026-11-05；任务查找与后续传输共享总时限及有限重试次数。
            dukto::RemoteClient query(profile, timeout(parser), stop);
            query.authenticate();
            const auto value = query.manage(resumeId);
            query.close();
            return value;
        });
        command = task["direction"].toString();
        if (command != "upload" && command != "download")
            throw dukto::Error(dukto::ExitCode::Integrity, QStringLiteral("任务方向无效"), "task");
        share = task["share"].toString();
        relative = task["path"].toString();
        request = QUuid(task["requestId"].toString());
        conflict = task.contains("conflict")
                       ? dukto::checkedConflictPolicy(task["conflict"].toString())
                       : dukto::ConflictPolicy::Rename;
    }
    if (command == "upload" || command == "download") {
        dukto::checkedChannels(parser.value("threads"));
        if ((!resuming && parser.values("share").size() != 1) ||
            parser.values("remote-path").size() > 1 ||
            (command == "upload" && parser.values("path").isEmpty()) ||
            (command == "download" &&
             (!parser.values("path").isEmpty() || parser.value("output").isEmpty())))
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("请指定一个 --share；upload 使用 --path，download "
                                              "使用 --remote-path 和 --output"),
                               "arguments");
        if (!resuming)
            request = parser.isSet("request-id") ? QUuid(parser.value("request-id"))
                                                 : QUuid::createUuid();
        if (request.isNull() ||
            (parser.isSet("request-id") &&
             parser.value("request-id") != request.toString(QUuid::WithoutBraces)))
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("--request-id 必须是规范 UUID"), "arguments");
        operation->bindRequest(request);
        output({{"eventVersion", 1},
                {"event", "transfer-started"},
                {"requestId", request.toString(QUuid::WithoutBraces)},
                {"message", QStringLiteral("中断后可使用相同 --request-id 重试")}});
        transferState.reset(
            new dukto::PrivateStore(QDir(stateDirectory).filePath("transfers"), true));
        if (command == "upload") {
            operation->run([&]() {
                // 日期：2026-11-06；原请求跨进程复用冻结源清单，重开不扫描已删除的跳过源。
                upload.reset(new dukto::UploadManifest(
                    *transferState, request, profile, share, relative, conflict,
                    parser.values("path"), stop, [&]() {
                        // 日期：2026-11-06；本地磁盘核验同样处理信号，并受原总期限约束。
                        QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
                    }));
                return QJsonObject{};
            });
        }
    }
    if (command == "upload" || command == "download") {
        const auto progress = [&](QJsonObject event) {
            // 日期：2026-11-05；核心事件逐条转发并绑定当前任务，重试不丢失公开身份。
            operation->report(event);
        };
        auto result = operation->run([&]() {
            // 日期：2026-11-05；每次只新建认证连接，原请求/冻结清单/本地日志始终复用。
            dukto::RemoteClient remote(profile, timeout(parser), stop);
            remote.authenticate();
            operation->resume(remote, resumeId);
            auto value =
                command == "upload"
                    ? remote.upload(request, share, relative, *transferState, upload->get(),
                                    progress, dukto::checkedChannels(parser.value("threads")),
                                    conflict)
                    : remote.download(request, share, relative, *transferState,
                                      QFileInfo(parser.value("output")).absoluteFilePath(),
                                      progress, dukto::checkedChannels(parser.value("threads")),
                                      conflict);
            dukto::TransferOperation::closeCompleted(remote);
            return value;
        });
        result["eventVersion"] = 1;
        result["event"] = "transfer-completed";
        // 日期：2026-11-06；逻辑完成不代表全部复制，显式显示跳过字节，原JSON计量完整保留。
        result["message"] =
            result.value("accountingVersion") == QJsonValue(1)
                ? QStringLiteral("任务已确认：复制 %1 B，跳过 %2 B")
                      .arg(result["copiedBytes"].toString(), result["skippedBytes"].toString())
                : QStringLiteral("任务全部文件已确认完成");
        output(result);
        return 0;
    }
    dukto::RemoteClient remote(profile, timeout(parser), &cancelled);
    const auto account = command == "pair" ? remote.pair(pairing) : remote.authenticate();
    if (command == "pair") {
        profile.server = remote.serverId();
        profile.paired = true;
        dukto::saveProfile(clients, profile);
    }
    if (command == "task-items") {
        const QUuid id(parser.value("task"));
        if (parser.values("task").size() != 1 || id.isNull() ||
            parser.value("task") != id.toString(QUuid::WithoutBraces) ||
            parser.values("after").size() > 1)
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("请指定规范 --task UUID 和单个 --after"),
                               "arguments");
        auto after =
            dukto::next::decimal(parser.value("after"), std::numeric_limits<qint64>::max());
        dukto::PrivateStore local(QDir(stateDirectory).filePath("transfers"), true);
        remote.close();
        for (int count = 0; count < 100000; ++count) {
            // 日期：2026-11-05；每页独立认证及关闭，10万文件翻页不耗尽单会话请求上限。
            dukto::RemoteClient query(profile, timeout(parser), &cancelled);
            query.authenticate();
            auto page = query.items(id, local, after);
            query.close();
            const auto more = page["more"].toBool();
            after = page["after"].toString().toULongLong();
            page["eventVersion"] = 1;
            page["event"] = "task-items";
            page["message"] =
                page["available"].toBool()
                    ? QStringLiteral("本页%1项，接收端持久记录；不代表当前文件重新校验")
                          .arg(page["entries"].toArray().size())
                    : QStringLiteral("本机接收记录或冻结清单尚不可用：%1")
                          .arg(page["reason"].toString());
            output(page);
            if (!parser.isSet("all") || !more) {
                return 0;
            }
        }
        throw dukto::Error(dukto::ExitCode::Config,
                           QStringLiteral("明细翻页次数已达上限，请按游标继续"), "items");
    }
    if (command == "tasks") {
        auto after =
            dukto::next::decimal(parser.value("after"), std::numeric_limits<qint64>::max());
        bool more;
        do {
            auto page = remote.tasks(after);
            after = page["after"].toString().toULongLong();
            more = page["more"].toBool();
            page["eventVersion"] = 1;
            page["event"] = "tasks";
            page["message"] = QStringLiteral("本页任务 %1 项；下一页序号：%2")
                                  .arg(page["tasks"].toArray().size())
                                  .arg(after);
            output(page);
        } while (parser.isSet("all") && more);
        remote.close();
        return 0;
    }
    if (command == "task" || command == "pause" || command == "cancel") {
        const QUuid id(parser.value("task"));
        if (id.isNull() || parser.value("task") != id.toString(QUuid::WithoutBraces))
            throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("请指定规范 --task UUID"),
                               "arguments");
        auto task = remote.manage(id, command == "pause"    ? dukto::next::Type::Pause
                                      : command == "cancel" ? dukto::next::Type::Cancel
                                                            : dukto::next::Type::TaskQuery);
        remote.close();
        task["eventVersion"] = 1;
        task["event"] = "task-state";
        // 日期：2026-11-05；先复制值再插入新键，避免 QJsonValueRef 因对象重排而引用到其他字段。
        task["errorMessage"] = task.value("message");
        task["message"] = QStringLiteral("任务状态：%1；请求：%2；活动执行者：%3")
                              .arg(task["state"].toString(), task["desired"].toString(),
                                   task["executionActive"].toBool() ? "yes" : "no");
        output(task);
        return 0;
    }
    if (command == "list") {
        if (parser.values("share").size() != 1 || parser.values("path").size() > 1)
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("请指定一个 --share 和可选的相对 --path"),
                               "arguments");
        auto cursor = parser.value("cursor");
        do {
            auto page = remote.list(parser.value("share"), parser.value("path"), cursor);
            cursor = page["cursor"].toString();
            page["eventVersion"] = 1;
            page["event"] = "listing";
            output(page);
        } while (parser.isSet("all") && !cursor.isEmpty());
        remote.close();
        return 0;
    }
    remote.close();
    auto result = account.publicInfo();
    if (remote.sessionSeconds())
        result["sessionSeconds"] = QString::number(remote.sessionSeconds());
    result["eventVersion"] = 1;
    result["event"] = command == "pair" ? "paired" : "authenticated";
    result["serverId"] = remote.serverId().toString(QUuid::WithoutBraces);
    result["message"] =
        command == "pair" ? QStringLiteral("服务器配对完成") : QStringLiteral("服务器认证成功");
    output(result);
    return 0;
}
