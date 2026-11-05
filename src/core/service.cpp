#include "service.h"
#include "browse.h"
#include "endpoint.h"
#include "error.h"
#include "paralleltransfer.h"
#include "sessionpolicy.h"
#include "shares.h"
#include "taskstore.h"
#include "transferservice.h"

#include <QJsonArray>
#include <QLockFile>
#include <QRegularExpression>
#include <QTcpSocket>
#include <limits>

namespace dukto {
namespace {
// 日期：2026-11-04；凭据按固定 32 字节编码，Qt fromHex 容忍非法字符的行为不能用于认证解析。
QByteArray secret(const QJsonValue &value) {
    static const QRegularExpression hex("\\A[0-9a-f]{64}\\z");
    if (!value.isString() || !hex.match(value.toString()).hasMatch())
        throw Error(ExitCode::Permission, QStringLiteral("凭据编码无效"), "auth");
    return QByteArray::fromHex(value.toString().toLatin1());
}

// 日期：2026-11-04；别名作为本地状态键，禁止路径、Windows 保留名及无限长输入。
QString profileName(const QString &alias) {
    validateShareName(alias);
    return "profile-" + alias + ".json";
}

// 日期：2026-11-05；按当前业务处理器精确声明能力，接收端不能从版本号推断其他操作可用。
QJsonArray capabilities() {
    return {"pair-v1",
            "auth-v1",
            "credential-rotation-v1",
            "session-lifetime-v1",
            "task-admission-v1",
            "control-close-v1",
            "browse-v1",
            "stream-transfer-v1",
            "task-control-v1",
            "parallel-transfer-v1",
            "byte-progress-v1",
            "conflict-fail-v1",
            "task-items-v1",
            "task-item-failures-v1"};
}

// 日期：2026-11-04；服务端只接受精确 1.0 能力协商，认证消息不能跳过协议入口。
void hello(const next::Frame &frame) {
    const auto object = next::parseControl(frame.payload);
    if (frame.header.type != next::Type::Hello || object["version"] != "1.0" ||
        !object["capabilities"].isArray())
        throw Error(ExitCode::Config, QStringLiteral("请先协商支持的新版协议及能力"), "hello");
}
} // namespace

// 日期：2026-11-04；资料包含秘密，只能通过 PrivateStore 原生权限检查后读取。
ClientProfile loadProfile(const PrivateStore &store, const QString &alias) {
    const auto object = next::parseControl(store.read(profileName(alias)));
    if (object["version"] != 1 || object["alias"] != alias || !object["host"].isString() ||
        !object["peerName"].isString() || !object["paired"].isBool())
        throw Error(ExitCode::Config, QStringLiteral("客户端资料格式无效"), "profile");
    const auto port = next::decimal(object["port"], 65535);
    const auto endpoint = parseEndpoint(object["host"].toString(), static_cast<int>(port));
    ClientProfile profile{alias,
                          endpoint.host,
                          endpoint.port,
                          object["peerName"].toString(),
                          secret(object["fingerprint"]),
                          QUuid(object["server"].toString()),
                          QUuid(object["client"].toString()),
                          secret(object["credential"]),
                          object["paired"].toBool()};
    if (object.contains("pendingCredential"))
        profile.pendingCredential = secret(object["pendingCredential"]);
    if (!port || profile.peerName.isEmpty() || profile.client.isNull() ||
        (profile.paired && profile.server.isNull()) ||
        (!profile.pendingCredential.isEmpty() &&
         (!profile.paired || secureEqual(profile.credential, profile.pendingCredential))))
        throw Error(ExitCode::Config, QStringLiteral("客户端资料身份无效"), "profile");
    return profile;
}

namespace {
// 日期：2026-11-05；调用者持有资料锁时才写入秘密，序列化文本不作为事件或日志返回。
void writeProfile(PrivateStore &store, const ClientProfile &profile) {
    if (profile.credential.size() != 32 || profile.fingerprint.size() != 32 ||
        profile.client.isNull() || !profile.port || profile.peerName.isEmpty() ||
        (profile.paired && profile.server.isNull()) ||
        (!profile.pendingCredential.isEmpty() &&
         (profile.pendingCredential.size() != 32 || !profile.paired ||
          secureEqual(profile.credential, profile.pendingCredential))))
        throw Error(ExitCode::Config, QStringLiteral("待保存的客户端资料无效"), "profile");
    QJsonObject record{{"version", 1},
                       {"alias", profile.alias},
                       {"host", profile.host},
                       {"port", QString::number(profile.port)},
                       {"peerName", profile.peerName},
                       {"fingerprint", QString::fromLatin1(profile.fingerprint.toHex())},
                       {"server", profile.server.toString(QUuid::WithoutBraces)},
                       {"client", profile.client.toString(QUuid::WithoutBraces)},
                       {"credential", QString::fromLatin1(profile.credential.toHex())},
                       {"paired", profile.paired}};
    if (!profile.pendingCredential.isEmpty())
        record["pendingCredential"] = QString::fromLatin1(profile.pendingCredential.toHex());
    store.write(profileName(profile.alias), next::encodeControl(record));
}
} // namespace

// 日期：2026-11-05；配对确认也持有同一资料锁，旧配对响应不能覆盖已轮换或待确认的新秘密。
void saveProfile(PrivateStore &store, const ClientProfile &profile) {
    QLockFile lock(store.directory() + "/" + profileName(profile.alias) + ".lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("客户端资料正在修改，请重试"), "profile");
    if (store.exists(profileName(profile.alias))) {
        const auto current = loadProfile(store, profile.alias);
        if (!current.pendingCredential.isEmpty() || !profile.pendingCredential.isEmpty() ||
            !secureEqual(current.credential, profile.credential) ||
            current.client != profile.client || current.host != profile.host ||
            current.port != profile.port || current.peerName != profile.peerName ||
            current.fingerprint != profile.fingerprint ||
            (current.paired && (!profile.paired || current.server != profile.server)))
            throw Error(ExitCode::Permission,
                        QStringLiteral("资料已改变或轮换尚待确认，请重新加载并完成轮换"),
                        "profile");
    }
    writeProfile(store, profile);
}

// 日期：2026-11-05；恢复仅在新秘密明确认证拒绝后使用原秘密，网络或证书错误保留待确认状态。
QJsonObject rotateProfile(PrivateStore &store, const QString &alias, int timeoutMs,
                          const std::atomic_bool *cancel) {
    QLockFile lock(store.directory() + "/" + profileName(alias) + ".lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("客户端资料正在轮换，请稍后重试"),
                    "profile");
    auto profile = loadProfile(store, alias);
    if (!profile.paired)
        throw Error(ExitCode::Permission, QStringLiteral("请先完成配对再轮换凭据"), "auth");
    const bool recovering = !profile.pendingCredential.isEmpty();
    Principal confirmed;
    bool changed = false;
    if (recovering) {
        auto candidate = profile;
        candidate.credential = profile.pendingCredential;
        candidate.pendingCredential.clear();
        try {
            RemoteClient remote(candidate, timeoutMs, cancel);
            confirmed = remote.authenticate();
            changed = true;
            remote.close();
        } catch (const Error &error) {
            if (changed || error.code != ExitCode::Permission || error.stage != "auth")
                throw;
        }
    }
    if (!changed) {
        RemoteClient remote(profile, timeoutMs, cancel);
        remote.authenticate();
        if (profile.pendingCredential.isEmpty()) {
            profile.pendingCredential = randomCredential();
            // 日期：2026-11-05；该原子写失败时绝不能发出远程变更，防止本地丢失唯一有效秘密。
            writeProfile(store, profile);
        }
        confirmed = remote.rotateCredential(profile.pendingCredential);
        remote.close();
    }
    profile.credential = profile.pendingCredential;
    profile.pendingCredential.clear();
    writeProfile(store, profile);
    auto result = confirmed.publicInfo();
    result["eventVersion"] = 1;
    result["event"] = "credential-rotated";
    result["recovered"] = recovering;
    result["message"] = QStringLiteral("访问凭据已轮换；旧凭据已失效，任务身份和授权保留");
    return result;
}

// 日期：2026-11-04；恢复配对沿用已持久化秘密，不能每次重试生成新凭据导致服务器绑定冲突。
ClientProfile prepareProfile(PrivateStore &store, const QString &alias, const QString &host,
                             quint16 port, const QString &peerName, const QByteArray &fingerprint) {
    profileName(alias);
    QLockFile lock(store.directory() + "/" + profileName(alias) + ".lock");
    lock.setStaleLockTime(0);
    if (!lock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("客户端资料正在建立，请重试"), "profile");
    const auto endpoint = parseEndpoint(host, port);
    if (store.exists(profileName(alias))) {
        const auto profile = loadProfile(store, alias);
        if (profile.host != endpoint.host || profile.port != endpoint.port ||
            profile.peerName != peerName || profile.fingerprint != fingerprint)
            throw Error(ExitCode::Permission,
                        QStringLiteral("现有资料目标或指纹不同，拒绝覆盖信任"), "profile");
        return profile;
    }
    ClientProfile profile{alias,   endpoint.host,       endpoint.port,      peerName, fingerprint,
                          QUuid(), QUuid::createUuid(), randomCredential(), false};
    writeProfile(store, profile);
    return profile;
}

// 日期：2026-11-04；固定指纹与主机名在 TLS 层检查，HelloAck 的 ID 还必须匹配既有服务记录。
RemoteClient::RemoteClient(const ClientProfile &profile, int timeoutMs,
                           const std::atomic_bool *cancel)
    : profile_(profile), channel_(timeoutMs, cancel), cancel_(cancel), timeoutMs_(timeoutMs) {
    channel_.connectTo(profile.host, profile.port, profile.peerName,
                       QSslConfiguration::defaultConfiguration(), profile.fingerprint);
    const auto response = request(next::Type::Hello, next::Type::HelloAck,
                                  {{"version", "1.0"}, {"capabilities", capabilities()}});
    server_ = QUuid(response["serverId"].toString());
    if (response["version"] != "1.0" || !response["capabilities"].isArray() || server_.isNull() ||
        (!profile.server.isNull() && profile.server != server_))
        throw Error(ExitCode::Permission, QStringLiteral("服务器身份或协议协商不匹配"), "hello");
    capabilities_ = response["capabilities"].toArray();
    if (capabilities_.contains("session-lifetime-v1"))
        sessionSeconds_ = checkedSessionSeconds(response["sessionSeconds"]);
}

// 日期：2026-11-05；每条数据连接重新认证后转入数据授信，票据不进入事件输出。
void RemoteClient::runDataLane(const QJsonObject &ticket, int lane,
                               const std::shared_ptr<ParallelState> &state,
                               const QPair<QString, QString> &source) {
    if (!capabilities_.contains("parallel-transfer-v1"))
        throw Error(ExitCode::Config, QStringLiteral("服务器不支持多数据通道"), "parallel");
    channel_.classifyAsData();
    const auto response = request(next::Type::Attach, next::Type::Attached,
                                  {{"sessionId", ticket["sessionId"]},
                                   {"token", ticket["token"]},
                                   {"lane", QString::number(lane)}});
    if (response !=
        QJsonObject{{"sessionId", ticket["sessionId"]}, {"lane", QString::number(lane)}})
        throw Error(ExitCode::Integrity, QStringLiteral("数据通道加入确认不同"), "parallel");
    ParallelTransfer::clientLane(channel_, ticket, lane, state, source, correlation_);
}

// 日期：2026-11-04；错误响应不包含任意远端正文，协议固定的说明按纯文本交由界面展示。
QJsonObject RemoteClient::request(next::Type type, next::Type response, const QJsonObject &object) {
    if (correlation_ == std::numeric_limits<quint64>::max())
        throw Error(ExitCode::Config, QStringLiteral("连接请求序号已耗尽"), "protocol");
    channel_.write(type, ++correlation_, object);
    const auto frame = channel_.read();
    if (frame.header.correlation != correlation_)
        throw Error(ExitCode::Config, QStringLiteral("服务器响应请求序号不匹配"), "protocol");
    const auto result = next::parseControl(frame.payload);
    if (frame.header.type == next::Type::Failure) {
        const auto code = result["code"].toInt(-1);
        if (code < 1 || code > 7 || !result["message"].isString() || !result["stage"].isString())
            throw Error(ExitCode::Config, QStringLiteral("服务器错误响应无效"), "protocol");
        throw Error(static_cast<ExitCode>(code), result["message"].toString(),
                    result["stage"].toString());
    }
    if (frame.header.type != response)
        throw Error(ExitCode::Config, QStringLiteral("服务器响应类型不匹配"), "protocol");
    return result;
}

// 日期：2026-11-04；授权响应只接受本客户端 UUID，权限不作宽松转换。
Principal RemoteClient::account(const QJsonObject &object) const {
    if (object["client"] != profile_.client.toString(QUuid::WithoutBraces) ||
        !object["grants"].isArray())
        throw Error(ExitCode::Permission, QStringLiteral("服务器返回了其他客户端身份或无效授权"),
                    "auth");
    const auto revision = next::decimal(object["revision"], std::numeric_limits<quint64>::max());
    if (!revision)
        throw Error(ExitCode::Permission, QStringLiteral("授权修订号无效"), "auth");
    return {profile_.client, revision, decodeGrants(object["grants"].toArray())};
}

// 日期：2026-11-04；秘密只作为 TLS 帧正文，不能传入日志、任务持久化或进程参数。
Principal RemoteClient::pair(const QByteArray &pairingCredential) {
    if (pairingCredential.size() != 32)
        throw Error(ExitCode::Config, QStringLiteral("配对文件凭据无效"), "pair");
    return account(request(next::Type::Pair, next::Type::Paired,
                           {{"client", profile_.client.toString(QUuid::WithoutBraces)},
                            {"pairing", QString::fromLatin1(pairingCredential.toHex())},
                            {"credential", QString::fromLatin1(profile_.credential.toHex())}}));
}

// 日期：2026-11-04；配对完成后每次连接重新认证，不能只依靠客户端本地 paired 标志授权。
Principal RemoteClient::authenticate() {
    return account(request(next::Type::Authenticate, next::Type::Authenticated,
                           {{"client", profile_.client.toString(QUuid::WithoutBraces)},
                            {"credential", QString::fromLatin1(profile_.credential.toHex())}}));
}

// 日期：2026-11-05；新秘密只走已认证 TLS，未知能力拒绝且不退回原版入口。
Principal RemoteClient::rotateCredential(const QByteArray &replacement) {
    if (!capabilities_.contains("credential-rotation-v1"))
        throw Error(ExitCode::Config, QStringLiteral("服务器不支持凭据轮换，请先升级服务器"),
                    "auth");
    if (replacement.size() != 32 || secureEqual(replacement, profile_.credential))
        throw Error(ExitCode::Config, QStringLiteral("新凭据长度无效或与原凭据相同"), "auth");
    const auto result =
        account(request(next::Type::RotateCredential, next::Type::CredentialRotated,
                        {{"credential", QString::fromLatin1(replacement.toHex())}}));
    profile_.credential = replacement;
    return result;
}

// 日期：2026-11-04；客户端只提交共享名称/相对路径/不透明游标，不提交服务端绝对路径。
QJsonObject RemoteClient::list(const QString &share, const QString &relative,
                               const QString &cursor) {
    return request(next::Type::List, next::Type::Listing,
                   {{"share", share}, {"path", relative}, {"cursor", cursor}});
}

// 日期：2026-11-04；只公开当前 TLS 连接所返回并与既有记录核对的服务 UUID。
QUuid RemoteClient::serverId() const {
    return server_;
}

// 日期：2026-11-05；只公开协商过且严格校验的时长，不从访问令牌或系统时间推算。
int RemoteClient::sessionSeconds() const {
    return sessionSeconds_;
}

// 日期：2026-11-04；任务控制仅传规范 UUID，响应必须绑定同一任务和明确实际执行状态。
QJsonObject RemoteClient::manage(const QUuid &task, next::Type operation) {
    if (task.isNull() || (operation != next::Type::TaskQuery && operation != next::Type::Pause &&
                          operation != next::Type::Cancel && operation != next::Type::Resume))
        throw Error(ExitCode::Config, QStringLiteral("任务控制参数无效"), "task");
    const auto result = request(operation, next::Type::TaskState,
                                {{"taskId", task.toString(QUuid::WithoutBraces)}});
    if (result["taskId"] != task.toString(QUuid::WithoutBraces) ||
        !result["executionActive"].isBool() || !result["state"].isString())
        throw Error(ExitCode::Integrity, QStringLiteral("任务控制结果身份无效"), "task");
    return result;
}

// 日期：2026-11-04；任务列表是持久记录索引，实际执行者与停止状态仍由单任务查询确认。
QJsonObject RemoteClient::tasks(quint64 after) {
    const auto result =
        request(next::Type::TaskQuery, next::Type::TaskState, {{"after", QString::number(after)}});
    if (result.size() != 3 || !result["tasks"].isArray() || !result["more"].isBool() ||
        next::decimal(result["after"], std::numeric_limits<qint64>::max()) < after ||
        (result["more"].toBool() && result["after"] == QString::number(after)))
        throw Error(ExitCode::Integrity, QStringLiteral("任务分页响应无效"), "task");
    for (const auto &value : result["tasks"].toArray()) {
        const auto task = value.toObject();
        const QUuid id(task["taskId"].toString());
        if (id.isNull() || task["taskId"] != id.toString(QUuid::WithoutBraces) ||
            !task["state"].isString() || !task["share"].isString())
            throw Error(ExitCode::Integrity, QStringLiteral("任务分页条目身份无效"), "task");
    }
    return result;
}

// 日期：2026-11-04；关闭应答只确认会话结束，不替代任何文件任务的完整性或持久完成确认。
void RemoteClient::close() {
    if (!closed_) {
        request(next::Type::Close, next::Type::Closed, {});
        closed_ = true;
    }
}

// 日期：2026-11-04；线程尚未启动时不创建 socket、数据库连接或其他线程归属的 Qt 对象。
ServiceWorker::ServiceWorker(qintptr descriptor, QString state, ServiceIdentity identity,
                             int timeoutMs, QObject *parent)
    : QThread(parent), descriptor_(descriptor), state_(std::move(state)),
      identity_(std::move(identity)), timeoutMs_(timeoutMs) {
}

// 日期：2026-11-04；只修改取消原子量，TLS 通道在自己的工作线程执行关闭。
void ServiceWorker::cancel() {
    cancelled_.store(true);
}

// 日期：2026-11-04；Qt 不允许销毁运行中的 QThread，退出前等待所有原生资源释放。
ServiceWorker::~ServiceWorker() {
    cancel();
    wait();
}

// 日期：2026-11-05；构造授信失败也关闭已接收的描述符；错误响应和日志不包含认证秘密。
void ServiceWorker::run() {
    std::unique_ptr<next::SecureChannel> connection;
    quint64 correlation = 1;
    try {
        try {
            connection.reset(new next::SecureChannel(timeoutMs_, &cancelled_));
        } catch (...) {
            // 日期：2026-11-05；TLS 对象尚未接管 socket，额度拒绝/分配异常仍须归还原生连接。
            QTcpSocket rejected;
            if (rejected.setSocketDescriptor(descriptor_))
                rejected.abort();
            throw;
        }
        auto &channel = *connection;
        channel.accept(descriptor_, identity_.configuration());
        PrivateStore store(state_);
        AuthStore auth(store);
        const auto sessionSeconds = loadSessionSeconds(store);
        const auto first = channel.read();
        correlation = first.header.correlation;
        hello(first);
        channel.write(next::Type::HelloAck, correlation,
                      {{"version", "1.0"},
                       {"capabilities", capabilities()},
                       {"sessionSeconds", QString::number(sessionSeconds)},
                       {"serverId", identity_.id.toString(QUuid::WithoutBraces)}});
        auto frame = channel.read();
        if (frame.header.correlation <= correlation)
            throw Error(ExitCode::Config, QStringLiteral("请求序号必须递增"), "protocol");
        correlation = frame.header.correlation;
        const auto object = next::parseControl(frame.payload);
        const auto client = QUuid(object["client"].toString());
        auto credential = secret(object["credential"]);
        Principal account;
        if (frame.header.type == next::Type::Pair) {
            account = auth.pair(secret(object["pairing"]), client, credential);
            channel.write(next::Type::Paired, correlation, account.publicInfo());
            emit event({{"eventVersion", 1},
                        {"event", "paired"},
                        {"client", client.toString(QUuid::WithoutBraces)}});
        } else if (frame.header.type == next::Type::Authenticate) {
            account = auth.authenticate(client, credential);
            channel.write(next::Type::Authenticated, correlation, account.publicInfo());
        } else {
            throw Error(ExitCode::Permission, QStringLiteral("请先配对或认证"), "auth");
        }
        AuthenticatedSession session(sessionSeconds);
        const auto reauthenticate = [&]() {
            // 日期：2026-11-05；原连接到期不可通过重复业务续命，恢复必须建立新认证连接。
            session.check();
            return auth.authenticate(client, credential);
        };
        for (int operations = 0; operations < 100000; ++operations) {
            frame = channel.read();
            if (frame.header.correlation <= correlation)
                throw Error(ExitCode::Config, QStringLiteral("请求序号必须递增"), "protocol");
            correlation = frame.header.correlation;
            account = reauthenticate();
            const auto request = next::parseControl(frame.payload);
            if (frame.header.type == next::Type::RotateCredential) {
                if (request.size() != 1 || !request.contains("credential"))
                    throw Error(ExitCode::Config, QStringLiteral("轮换凭据字段无效"), "auth");
                const auto replacement = secret(request["credential"]);
                account = auth.rotate(client, credential, replacement);
                credential = replacement;
                session.check();
                channel.write(next::Type::CredentialRotated, correlation, account.publicInfo());
                emit event({{"eventVersion", 1},
                            {"event", "credential-rotated"},
                            {"client", client.toString(QUuid::WithoutBraces)},
                            {"revision", QString::number(account.revision)}});
                continue;
            }
            if (frame.header.type == next::Type::Close) {
                if (!request.isEmpty())
                    throw Error(ExitCode::Config, QStringLiteral("关闭请求含未知字段"), "protocol");
                channel.write(next::Type::Closed, correlation, {});
                return;
            }
            if (frame.header.type == next::Type::CreateUpload ||
                frame.header.type == next::Type::CreateDownload) {
                serveTransfer(channel, store, account, reauthenticate, request, frame.header.type,
                              correlation);
                continue;
            }
            if (frame.header.type == next::Type::Attach) {
                serveParallelLane(channel, store, account, reauthenticate, request, correlation);
                continue;
            }
            if (frame.header.type == next::Type::TaskQuery ||
                frame.header.type == next::Type::Pause || frame.header.type == next::Type::Cancel ||
                frame.header.type == next::Type::Resume) {
                const auto result = manageTransfer(store, account, request, frame.header.type);
                const auto current = reauthenticate();
                // 日期：2026-11-05；页查询期间撤权或共享根改配后，不发布旧根的相对路径明细。
                if (request.contains("itemsAfter") || request.contains("itemsInfo")) {
                    TaskStore tasks(store);
                    const auto task =
                        tasks.task(current.client, QUuid(request["taskId"].toString()));
                    const auto held = Shares(store).open(
                        current, task.share,
                        task.direction == "upload" ? Access::Upload : Access::Download);
                    if (held->share().root != task.root)
                        throw Error(ExitCode::Permission,
                                    QStringLiteral("明细查询期间共享根已改配"), "items");
                }
                channel.write(next::Type::TaskState, correlation, result);
                continue;
            }
            if (frame.header.type == next::Type::List) {
                if (request.size() != 3 || !request["share"].isString() ||
                    !request["path"].isString() || !request["cursor"].isString())
                    throw Error(ExitCode::Config, QStringLiteral("浏览请求字段无效"), "browse");
                const auto share = request["share"].toString();
                QString authorizedRoot;
                BrowseStore browse(store, &cancelled_, [&]() {
                    // 日期：2026-11-04；扫描中每
                    // 250ms、发布前和回包前重新认证；根被改配也不能泄露旧根列表。
                    channel.checkpoint("browse");
                    const auto current = reauthenticate();
                    const auto held = Shares(store).open(current, share, Access::Browse);
                    const auto root = held->share().root;
                    if (!authorizedRoot.isEmpty() && authorizedRoot != root)
                        throw Error(ExitCode::Permission,
                                    QStringLiteral("共享根在浏览期间已改配，请重新浏览"), "browse");
                    authorizedRoot = root;
                });
                channel.write(next::Type::Listing, correlation,
                              browse.list(account, request["share"].toString(),
                                          request["path"].toString(),
                                          request["cursor"].toString()));
                continue;
            }
            throw Error(ExitCode::Config, QStringLiteral("当前服务未协商此命令能力"), "protocol");
        }
        throw Error(ExitCode::Config, QStringLiteral("控制会话请求数量已达上限，请重新连接"),
                    "protocol");
    } catch (const Error &error) {
        try {
            if (connection)
                connection->write(next::Type::Failure, correlation,
                                  {{"code", static_cast<int>(error.code)},
                                   {"stage", error.stage},
                                   {"message", error.message}});
        } catch (const Error &) {
        }
        auto event = error.json();
        event["event"] = "service-connection-closed";
        emit this->event(event);
    } catch (const std::exception &) {
        emit event(Error(ExitCode::Runtime, QStringLiteral("服务连接内部错误"), "service").json());
    }
}

// 日期：2026-11-05；启动前核对已有身份与会话策略，损坏策略不能静默回到宽松默认值。
ServiceListener::ServiceListener(const QString &state, int timeoutMs, QObject *parent)
    : QTcpServer(parent), state_(state), timeoutMs_(timeoutMs) {
    if (timeoutMs < 100 || timeoutMs > 3600000)
        throw Error(ExitCode::Config, QStringLiteral("服务连接超时无效"), "service");
    PrivateStore store(state);
    identity_ = loadIdentity(store);
    loadSessionSeconds(store);
    setMaxPendingConnections(32);
}

// 日期：2026-11-04；关闭监听与工作线程，不留下后台不受管理的 TLS 连接。
ServiceListener::~ServiceListener() {
    stop();
}

// 日期：2026-11-04；先统一通知取消再等待，多个连接不会各自串行等待完整网络超时。
void ServiceListener::stop() {
    close();
    const auto active = workers_;
    for (auto worker : active) {
        QObject::disconnect(worker, nullptr, this, nullptr);
        worker->cancel();
    }
    for (auto worker : active) {
        worker->wait();
        delete worker;
    }
    workers_.clear();
}

// 日期：2026-11-05；公开身份和之后新连接将采用的时长，不包含秘密或已有连接的私有状态。
QJsonObject ServiceListener::publicInfo() const {
    auto result = identity_.publicInfo();
    result["sessionSeconds"] = QString::number(loadSessionSeconds(PrivateStore(state_)));
    return result;
}

// 日期：2026-11-04；每连接占用一个固定上限工作槽位，完成后立刻归还而非累积线程对象。
void ServiceListener::incomingConnection(qintptr descriptor) {
    if (workers_.size() >= 32) {
        QTcpSocket rejected;
        rejected.setSocketDescriptor(descriptor);
        rejected.abort();
        emit event({{"eventVersion", 1},
                    {"event", "service-busy"},
                    {"message", QStringLiteral("服务活动连接已达上限")}});
        return;
    }
    auto worker = new ServiceWorker(descriptor, state_, identity_, timeoutMs_, this);
    workers_.insert(worker);
    QObject::connect(worker, &ServiceWorker::event, this, &ServiceListener::event);
    QObject::connect(worker, &QThread::finished, this, [this, worker]() {
        // 日期：2026-11-04；回调只在监听线程运行，不能与 incomingConnection 并发修改活动集合。
        workers_.remove(worker);
        worker->deleteLater();
    });
    worker->start();
}
} // namespace dukto
