#include "serverpanel.h"
#include "core/endpoint.h"
#include "core/error.h"
#include "core/paralleltransfer.h"
#include "core/sessionpolicy.h"
#include "core/shares.h"
#include "core/statesession.h"
#include "core/strongmanifest.h"
#include "core/transferoperation.h"
#include "core/uploadmanifest.h"
#include <QDir>
#include <QFileDialog>
#include <QFileInfo>
#include <QJsonArray>
#include <QRegularExpression>
#include <limits>

namespace {
// 日期：2026-11-04；界面勾选与 CLI 同样要求显式读/写授权，不因提供共享名默认开放。
QList<dukto::Grant> grants(const QVariantMap &options) {
    QList<dukto::Grant> result{{options["share"].toString(), options["browse"].toBool(),
                                options["download"].toBool(), options["upload"].toBool()}};
    dukto::encodeGrants(result);
    return result;
}

// 日期：2026-11-04；规范 UUID 用于任务/客户端键，禁止空值、括号或路径文本。
QUuid id(const QVariant &value) {
    const auto text = value.toString();
    const QUuid result(text);
    if (result.isNull() || text != result.toString(QUuid::WithoutBraces))
        throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("请提供规范 UUID"), "arguments");
    return result;
}
// 日期：2026-11-05；续期和迁移只接受用户核对的完整公开指纹，非法文本不能被fromHex宽松接受。
QByteArray checkedFingerprint(const QVariant &value) {
    const auto text = value.toString();
    if (!QRegularExpression("\\A[0-9a-fA-F]{64}\\z").match(text).hasMatch())
        throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("请核对完整64位证书指纹"),
                           "arguments");
    return QByteArray::fromHex(text.toLatin1());
}
} // namespace

// 日期：2026-11-04；参数只保存公开目标与本机路径，凭据在工作线程从 PrivateStore 读取。
ServerAction::ServerAction(QString directory, QString operation, QVariantMap options,
                           QObject *parent)
    : QThread(parent), directory_(std::move(directory)), operation_(std::move(operation)),
      options_(std::move(options)) {
}

// 日期：2026-11-04；原子取消由 SecureChannel 和扫描检查点持续观察。
void ServerAction::cancel() {
    cancelled_.store(true);
}

// 日期：2026-11-04；退出前先停止数据操作，等待 Qt 线程内析构 socket/SQLite。
ServerAction::~ServerAction() {
    cancel();
    wait();
}

// 日期：2026-11-04；有界覆盖旧快照，界面繁忙不造成生产者内存增长。
void ServerAction::progress(const QJsonObject &event) {
    QMutexLocker lock(&mutex_);
    progress_ = event;
}

// 日期：2026-11-04；每次取走并清空单槽，GUI 在自己的定时器里更新。
QJsonObject ServerAction::takeProgress() {
    QMutexLocker lock(&mutex_);
    const auto event = progress_;
    progress_ = {};
    return event;
}

// 日期：2026-11-04；调用者须已等待线程完成，不从运行线程并发读取结果。
QJsonObject ServerAction::result() const {
    return result_;
}

// 日期：2026-11-04；GUI 保留规范错误码，不能将查询成功解释成传输完成。
int ServerAction::code() const {
    return code_;
}

// 日期：2026-11-08；GUI工作线程保留同目录协调资格，取消在预算锁外观察，私有状态不进入界面事件。
void ServerAction::run() {
    try {
        if (operation_ == "budget-show") {
            // 日期：2026-11-08；查询只打开已有中央根，不建立目录/域/成员，不读取身份或任何秘密正文。
            dukto::PrivateStore coordinator(QDir(directory_).filePath("budget"));
            dukto::StateDomain domain(coordinator, [this]() {
                // 日期：2026-11-08；共享查询与真实传输并行，取消仍在账本锁外检查。
                if (cancelled_.load())
                    throw dukto::Error(dukto::ExitCode::Cancelled, QStringLiteral("预算查询已取消"),
                                       "state-budget");
            });
            result_ = dukto::StateBudget::report(domain.usage(), "show");
            return;
        }
        if (!QDir().mkpath(directory_))
            throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("无法准备服务器状态目录"));
        const auto stateCheck = [this]() {
            // 日期：2026-11-08；与网络共用同一取消来源，不在预算原生锁内等待GUI或其他线程。
            if (cancelled_.load())
                throw dukto::Error(dukto::ExitCode::Cancelled, QStringLiteral("状态准备已取消"),
                                   "state-session");
        };
        const auto stateRoot = [&](const QString &name, bool create = false) {
            // 日期：2026-11-08；directory_是界面公开的实际服务父目录，CLI指向同目录即核对同一中央登记。
            return dukto::StateSession::root(directory_, name, create,
                                             dukto::PrivateStore::Use::Shared, stateCheck);
        };
        const auto service = QDir(directory_).filePath("service");
        if (QStringList{"init", "info", "renew", "shares", "share-add", "share-remove", "pairing",
                        "grant", "revoke", "clients", "session-show", "session-set"}
                .contains(operation_)) {
            auto bound = stateRoot("service", operation_ == "init");
            auto &store = *bound;
            if (operation_ == "init" || operation_ == "info" || operation_ == "renew") {
                if (operation_ == "init" || operation_ == "renew") {
                    const auto names = options_["names"].toString().split(
                        QRegularExpression("[,;\\s]+"), Qt::SkipEmptyParts);
                    const auto daysText = options_.value("certificateDays", "365").toString();
                    bool validDays = false;
                    const auto days = daysText.toInt(&validDays);
                    if (!validDays || QString::number(days) != daysText || days < 1 || days > 825)
                        throw dukto::Error(dukto::ExitCode::Config,
                                           QStringLiteral("证书有效期须为1..825天"), "arguments");
                    if (operation_ == "init")
                        result_ = dukto::initializeIdentity(store, names, days).publicInfo();
                    else
                        result_ = dukto::renewIdentity(
                            store, checkedFingerprint(options_["fingerprint"]), names, days);
                } else
                    result_ = dukto::inspectIdentity(store);
                result_["sessionSeconds"] = QString::number(dukto::loadSessionSeconds(store));
                result_["event"] = "identity";
                return;
            }
            dukto::loadIdentity(store);
            if (operation_ == "session-show" || operation_ == "session-set") {
                if (operation_ == "session-set")
                    dukto::setSessionSeconds(store, options_["sessionSeconds"].toString());
                result_ = dukto::sessionPolicyInfo(store);
                return;
            }
            dukto::Shares shares(store);
            if (operation_ == "share-add" || operation_ == "share-remove" ||
                operation_ == "shares") {
                if (operation_ == "share-add")
                    shares.set({grants(options_).first(), options_["path"].toString()});
                else if (operation_ == "share-remove")
                    shares.remove(options_["share"].toString());
                QJsonArray entries;
                for (const auto &share : shares.all())
                    entries.append(
                        QJsonObject{{"name", share.permissions.share},
                                    {"root", share.root},
                                    {"permissions", dukto::encodeGrants({share.permissions})[0]}});
                result_ = {{"event", "shares"}, {"entries", entries}};
                return;
            }
            dukto::AuthStore auth(store);
            if (operation_ == "clients") {
                result_ = auth.clients(options_["after"].toString());
                return;
            }
            if (operation_ == "pairing") {
                const auto permissions = grants(options_);
                shares.validate(permissions);
                const auto offer = auth.issue(permissions);
                const auto name = "pairing-export-" +
                                  QUuid::createUuid().toString(QUuid::WithoutBraces) + ".json";
                store.write(name,
                            dukto::next::encodeControl(
                                {{"version", 1},
                                 {"credential", QString::fromLatin1(offer.credential.toHex())},
                                 {"expires", offer.expires.toString(Qt::ISODate)}}));
                result_ = {
                    {"event", "pairing-issued"},
                    {"credentialFile", QDir(service).filePath(name)},
                    {"message", QStringLiteral("配对文件：%1").arg(QDir(service).filePath(name))}};
                return;
            }
            const auto client = id(options_["client"]);
            if (operation_ == "revoke")
                auth.revoke(client);
            else {
                const auto permissions = grants(options_);
                shares.validate(permissions);
                auth.setGrants(client, permissions);
            }
            result_ = auth.clients();
            result_["changedClient"] = client.toString(QUuid::WithoutBraces);
            result_["message"] = QStringLiteral("客户端授权已更新，列表已刷新到第一页");
            return;
        }
        auto boundClients = stateRoot("clients", true);
        auto &clients = *boundClients;
        const auto alias = options_.value("profile", "default").toString();
        if (operation_ == "profile-info") {
            result_ = dukto::profileInfo(clients, alias);
            return;
        }
        if (operation_ == "trust") {
            result_ = dukto::migrateProfileFingerprint(
                clients, alias, checkedFingerprint(options_["oldFingerprint"]),
                checkedFingerprint(options_["fingerprint"]), 30000, &cancelled_);
            return;
        }
        dukto::ClientProfile profile;
        QByteArray pairing;
        if (operation_ == "pair") {
            const auto target = dukto::parseEndpoint(options_["target"].toString(), 4646);
            const auto text = options_["fingerprint"].toString();
            if (!QRegularExpression("\\A[0-9a-fA-F]{64}\\z").match(text).hasMatch())
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("请核对完整的 64 位服务器指纹"), "pair");
            profile = dukto::prepareProfile(clients, alias, target.host, target.port,
                                            options_.value("peerName", target.host).toString(),
                                            QByteArray::fromHex(text.toLatin1()));
            const QFileInfo file(options_["credentialFile"].toString());
            dukto::PrivateStore secret(file.absolutePath());
            const auto credential =
                dukto::next::parseControl(secret.read(file.fileName()))["credential"].toString();
            if (!QRegularExpression("\\A[0-9a-f]{64}\\z").match(credential).hasMatch())
                throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("配对文件凭据无效"),
                                   "pair");
            pairing = QByteArray::fromHex(credential.toLatin1());
        } else {
            profile = dukto::loadProfile(clients, alias);
            if (!profile.paired)
                throw dukto::Error(dukto::ExitCode::Permission,
                                   QStringLiteral("请先完成服务器配对"), "auth");
            if (operation_ != "rotate" && !profile.pendingCredential.isEmpty())
                throw dukto::Error(dukto::ExitCode::Permission,
                                   QStringLiteral("凭据轮换尚待确认，请点击轮换凭据后继续"),
                                   "profile");
        }
        auto operation = operation_;
        if (operation == "rotate") {
            result_ = dukto::rotateProfile(clients, alias, 30000, &cancelled_);
            return;
        }
        auto share = options_["share"].toString();
        auto relative = options_["remotePath"].toString();
        auto conflict =
            dukto::checkedConflictPolicy(options_.value("conflict", "rename").toString());
        QUuid request = options_["requestId"].toString().isEmpty() ? QUuid::createUuid()
                                                                   : id(options_["requestId"]);
        std::unique_ptr<dukto::TransferOperation> transfer;
        if (operation == "upload" || operation == "download" || operation == "resume")
            transfer.reset(new dukto::TransferOperation(
                dukto::checkedTransferPolicy(options_.value("retries", "0").toString(),
                                             options_.value("deadlineSeconds", "86400").toString()),
                &cancelled_, [this, &conflict](const QJsonObject &event) {
                    // 日期：2026-11-05；单槽可能合并掉初始任务，后续快照仍携带固定策略且不累计事件。
                    auto snapshot = event;
                    if (snapshot.contains("taskId") && conflict != dukto::ConflictPolicy::Rename)
                        snapshot["conflict"] = dukto::conflictPolicyName(conflict);
                    progress(snapshot);
                }));
        const auto stop = transfer ? transfer->cancellation() : &cancelled_;
        QUuid resume;
        if (operation == "resume") {
            resume = id(options_["taskId"]);
            const auto task = transfer->run([&]() {
                // 日期：2026-11-05；恢复参数查找计入同一操作的时间与重试预算。
                dukto::RemoteClient query(profile, 30000, stop);
                query.authenticate();
                const auto value = query.manage(resume);
                query.close();
                return value;
            });
            operation = task["direction"].toString();
            if (operation != "upload" && operation != "download")
                throw dukto::Error(dukto::ExitCode::Integrity, QStringLiteral("原任务方向无效"),
                                   "task");
            share = task["share"].toString();
            relative = task["path"].toString();
            request = id(task["requestId"].toVariant());
            // 日期：2026-11-05；恢复从服务任务取原策略，不能采用用户后来改变的下拉框值。
            conflict = task.contains("conflict")
                           ? dukto::checkedConflictPolicy(task["conflict"].toString())
                           : dukto::ConflictPolicy::Rename;
        }
        std::shared_ptr<dukto::PrivateStore> transfers;
        std::unique_ptr<dukto::UploadManifest> manifest;
        if (operation == "upload" || operation == "download") {
            dukto::checkedChannels(options_.value("channels", "1").toString());
            if (operation == "download" && options_["output"].toString().isEmpty())
                throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("请选择本地保存目录"),
                                   "arguments");
            transfers = stateRoot("transfers", true);
            transfer->bindRequest(request);
            transfer->report({{"requestId", request.toString(QUuid::WithoutBraces)},
                              {"state", "scanning"},
                              {"message", QStringLiteral("准备传输，重试请求 ID：%1")
                                              .arg(request.toString(QUuid::WithoutBraces))}});
            if (operation == "upload") {
                auto paths = options_["paths"].toStringList();
                if (paths.isEmpty() && !options_["path"].toString().isEmpty())
                    paths.append(options_["path"].toString());
                transfer->run([&]() {
                    // 日期：2026-11-06；GUI与CLI共用持久冻结源，不因重启重扫或更换原请求清单。
                    manifest.reset(new dukto::UploadManifest(*transfers, request, profile, share,
                                                             relative, conflict, paths, stop));
                    return QJsonObject{};
                });
            }
        }
        if (transfer) {
            result_ = transfer->run([&]() {
                // 日期：2026-11-05；GUI 与 CLI
                // 共用重连预算及幂等请求，所有通道仍在当前工作线程内回收。
                dukto::RemoteClient remote(profile, 30000, stop);
                remote.authenticate();
                transfer->resume(remote, resume);
                const auto update = [&](const QJsonObject &event) {
                    // 日期：2026-11-05；逐文件及字节快照继续有界覆盖，最终确认独立保留。
                    transfer->report(event);
                };
                auto value =
                    operation == "upload"
                        ? remote.upload(
                              request, share, relative, *transfers, manifest->get(), update,
                              dukto::checkedChannels(options_.value("channels", "1").toString()),
                              conflict)
                        : remote.download(
                              request, share, relative, *transfers,
                              QFileInfo(options_["output"].toString()).absoluteFilePath(), update,
                              dukto::checkedChannels(options_.value("channels", "1").toString()),
                              conflict);
                dukto::TransferOperation::closeCompleted(remote);
                return value;
            });
            return;
        }
        dukto::RemoteClient remote(profile, 30000, &cancelled_);
        const auto account = operation == "pair" ? remote.pair(pairing) : remote.authenticate();
        if (operation == "pair") {
            profile.server = remote.serverId();
            profile.paired = true;
            dukto::saveProfile(clients, profile);
            result_ = account.publicInfo();
            result_["event"] = "paired";
            result_["message"] = QStringLiteral("配对成功；客户端 UUID：%1")
                                     .arg(account.client.toString(QUuid::WithoutBraces));
        } else if (operation == "auth") {
            result_ = account.publicInfo();
            result_["message"] = QStringLiteral("连接认证成功");
        } else if (operation == "list") {
            result_ = remote.list(share, relative, options_["cursor"].toString());
            result_["event"] = "listing";
        } else if (operation == "task" || operation == "pause" || operation == "cancel") {
            result_ = remote.manage(id(options_["taskId"]),
                                    operation == "pause"    ? dukto::next::Type::Pause
                                    : operation == "cancel" ? dukto::next::Type::Cancel
                                                            : dukto::next::Type::TaskQuery);
        } else if (operation == "task-items") {
            auto bound = stateRoot("transfers", true);
            auto &local = *bound;
            result_ = remote.items(id(options_["taskId"]), local,
                                   dukto::next::decimal(options_.value("after", "0").toString(),
                                                        std::numeric_limits<qint64>::max()));
            result_["event"] = "task-items";
            result_["profile"] = alias;
        } else if (operation == "tasks") {
            result_ = remote.tasks(dukto::next::decimal(options_.value("after", "0").toString(),
                                                        std::numeric_limits<qint64>::max()));
            result_["event"] = "tasks";
        } else {
            throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("服务器操作无效"),
                               "arguments");
        }
        remote.close();
    } catch (const dukto::Error &error) {
        result_ = error.json();
        code_ = static_cast<int>(error.code);
    } catch (const std::exception &) {
        result_ = {{"message", QStringLiteral("服务器操作内部错误")}};
        code_ = 1;
    }
}

// 日期：2026-11-04；定时器仅取有界快照，不让后台文件数决定主线程队列长度。
ServerPanel::ServerPanel(const QString &directory, QObject *parent)
    : QObject(parent), directory_(directory),
      status_(QStringLiteral("输入服务器地址配对，或配置本机共享")) {
    timer_.setInterval(100);
    connect(&timer_, &QTimer::timeout, this, [this]() {
        // 日期：2026-11-04；控制与数据快照独立轮询，先显示数据再显示明确控制结果。
        for (auto action : {action_, control_})
            if (action)
                accept(action->takeProgress());
    });
    timer_.start();
}

// 日期：2026-11-04；先统一发取消，再等待双方及监听器，避免逐连接等待完整超时。
ServerPanel::~ServerPanel() {
    timer_.stop();
    if (action_)
        action_->cancel();
    if (control_)
        control_->cancel();
    delete listener_;
    delete action_;
    delete control_;
}

// 日期：2026-11-04；是否存在尚未收尾的普通操作。
bool ServerPanel::busy() const {
    return action_ != nullptr;
}
// 日期：2026-11-04；是否存在尚未收尾的控制操作。
bool ServerPanel::controlBusy() const {
    return control_ != nullptr;
}
// 日期：2026-11-04；监听状态来自真实 socket。
bool ServerPanel::serving() const {
    return listener_ && listener_->isListening();
}
// 日期：2026-11-04；返回实际状态快照。
QString ServerPanel::status() const {
    return status_;
}
// 日期：2026-11-04；返回本机受保护资料的上级状态目录。
QString ServerPanel::directory() const {
    return directory_;
}
// 日期：2026-11-04；转换公开身份对象供纯文本显示。
QVariantMap ServerPanel::identity() const {
    return identity_.toVariantMap();
}
// 日期：2026-11-04；转换当前任务快照，大小固定有界。
QVariantMap ServerPanel::task() const {
    return task_.toVariantMap();
}
// 日期：2026-11-04；只暴露当前页，下一页替换而非追加。
QVariantList ServerPanel::entries() const {
    return entries_.toVariantList();
}

// 日期：2026-11-04；列表模型由响应事件确定类型，切页不会混用另一种本机/远程记录。
QString ServerPanel::listingKind() const {
    return listingKind_;
}

// 日期：2026-11-04；公开结果便于选择客户端/配对文件，不解析本地化状态说明。
QVariantMap ServerPanel::outcome() const {
    return outcome_.toVariantMap();
}

// 日期：2026-11-04；任务页随网络结果替换，不累计所有历史或路径。
QVariantList ServerPanel::tasks() const {
    return tasks_.toVariantList();
}
// 日期：2026-11-04；任务页序号只交给已认证服务继续核对。
QString ServerPanel::tasksAfter() const {
    return tasksAfter_;
}
// 日期：2026-11-04；不从本页条数猜测还有下一页。
bool ServerPanel::tasksMore() const {
    return tasksMore_;
}
// 日期：2026-11-04；游标保持不透明字符串。
QString ServerPanel::cursor() const {
    return cursor_;
}

// 日期：2026-11-05；仅返回本机当前主体页，旧页随刷新或翻页释放。
QVariantList ServerPanel::clients() const {
    return clients_.toVariantList();
}
// 日期：2026-11-05；不把主体游标用于远程文件或任务列表。
QString ServerPanel::clientsAfter() const {
    return clientsAfter_;
}
// 日期：2026-11-05；按钮按真实返回的 more 启用，不以当前页大小推断。
bool ServerPanel::clientsMore() const {
    return clientsMore_;
}

// 日期：2026-11-05；时长模型独立于远程资料与目录，避免切页改变本机策略输入。
int ServerPanel::sessionSeconds() const {
    return sessionSeconds_;
}

// 日期：2026-11-05；返回完整单页身份，界面据此阻止另一任务或资料的旧明细混入当前任务。
QVariantMap ServerPanel::itemPage() const {
    return itemPage_.toVariantMap();
}

// 日期：2026-11-08；独立于任务/目录模型，后续进度事件不会覆盖已查询预算。
QVariantMap ServerPanel::budget() const {
    return budget_.toVariantMap();
}

// 日期：2026-11-05；按实际返回类型刷新模型，错误保留既有任务供重新查询与恢复。
void ServerPanel::accept(const QJsonObject &event, int code) {
    if (event.isEmpty())
        return;
    outcome_ = event;
    if (event["event"] == "state-budget")
        budget_ = event;
    if (event.contains("taskId") && event.contains("state")) {
        if (task_["taskId"] != event["taskId"])
            task_ = {};
        if (event.contains("manifestInfo")) {
            // 日期：2026-11-05；恢复会重新校验检查点，不能沿用上次执行的瞬时字节、速率或剩余时间。
            for (const auto &key :
                 {"receivedBytes", "restoredBytes", "bytesPerSecond", "etaSeconds"})
                task_.remove(key);
        }
        for (auto item = event.begin(); item != event.end(); ++item)
            task_[item.key()] = item.value();
        if (event["state"] == "completed") {
            // 日期：2026-11-06；新计量已有实际接收量，不能用包含跳过的逻辑完成量覆盖。
            if (!event.contains("receivedBytes"))
                task_["receivedBytes"] = event.value("bytes");
            task_["bytesPerSecond"] = 0;
            task_["etaSeconds"] = 0;
        }
    }
    if (event["event"] == "identity") {
        identity_ = event;
        if (listener_) {
            try {
                const auto active = listener_->publicInfo();
                identity_["activeFingerprint"] = active["fingerprint"];
                identity_["restartRequired"] = identity_["fingerprint"] != active["fingerprint"];
            } catch (const dukto::Error &error) {
                identity_["activeCertificateError"] = error.message;
                identity_["restartRequired"] = true;
            }
        }
        sessionSeconds_ = event["sessionSeconds"].toString().toInt();
    }
    if (event["event"] == "session-policy")
        sessionSeconds_ = event["seconds"].toString().toInt();
    if (event["event"] == "task-items") {
        itemPage_ = event;
        status_ = event["available"].toBool()
                      ? QStringLiteral("本页接收明细%1项").arg(event["entries"].toArray().size())
                      : QStringLiteral("本机接收记录或冻结清单不可用");
    } else if (event["event"] == "clients") {
        clients_ = event["entries"].toArray();
        clientsAfter_ = event["after"].toString();
        clientsMore_ = event["more"].toBool();
    } else if (event["entries"].isArray()) {
        entries_ = event["entries"].toArray();
        listingKind_ = event["event"].toString();
        cursor_ = event["cursor"].toString();
    }
    if (event["event"] == "tasks") {
        tasks_ = event["tasks"].toArray();
        tasksAfter_ = event["after"].toString();
        tasksMore_ = event["more"].toBool();
        status_ = QStringLiteral("本页任务 %1 项；选择后查询最新状态").arg(tasks_.size());
    }
    if (!event["message"].toString().isEmpty())
        status_ = event["message"].toString();
    else if (event.contains("state"))
        status_ = QStringLiteral("任务状态：%1；请求：%2")
                      .arg(event["state"].toString(), event["desired"].toString());
    else if (event["event"] == "identity")
        status_ = QStringLiteral("本机服务身份已读取");
    else if (event["event"] == "listing" || event["event"] == "shares")
        status_ = QStringLiteral("当前页 %1 项").arg(entries_.size());
    else if (event["event"] == "file-completed")
        status_ = QStringLiteral("文件已完成：%1").arg(event["path"].toString());
    if (code)
        status_ = QStringLiteral("操作失败（%1）：%2").arg(code).arg(status_);
    emit changed();
}

// 日期：2026-11-04；普通操作一个槽、控制一个槽，拒绝无界创建线程。
void ServerPanel::execute(const QString &operation, const QVariantMap &options) {
    const bool control = operation == "tasks" || operation == "task" || operation == "pause" ||
                         operation == "cancel" || operation == "task-items" ||
                         operation == "budget-show";
    auto &slot = control ? control_ : action_;
    if (slot) {
        status_ = QStringLiteral("该操作槽仍忙，请等待或断开当前操作");
        emit changed();
        return;
    }
    if (operation == "budget-show")
        budget_ = {};
    auto action = new ServerAction(directory_, operation, options, this);
    slot = action;
    connect(action, &QThread::finished, this, [this, action, control]() {
        // 日期：2026-11-04；join 后读取最终结果，先消费最后快照，保留失败前的任务身份。
        action->wait();
        accept(action->takeProgress());
        accept(action->result(), action->code());
        (control ? control_ : action_) = nullptr;
        action->deleteLater();
        emit changed();
    });
    status_ = QStringLiteral("正在处理…");
    action->start();
    emit changed();
}

// 日期：2026-11-08；空闲及活动监听全过程保留协调资格；失败由局部RAII归还，停止先清理所有工作线程。
void ServerPanel::setServing(bool enabled, const QString &address, int port) {
    try {
        if (!enabled) {
            delete listener_;
            listener_ = nullptr;
            listenerState_.reset();
            status_ = QStringLiteral("本机 TLS 服务已停止");
        } else if (!listener_) {
            const QHostAddress bind(address);
            if (bind.isNull() || port < 1 || port > 65535)
                throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("监听地址或端口无效"));
            auto bound = dukto::StateSession::root(directory_, "service");
            std::unique_ptr<dukto::ServiceListener> listener(
                new dukto::ServiceListener(bound->directory(), 30000));
            if (!listener->listen(bind, static_cast<quint16>(port)))
                throw dukto::Error(dukto::ExitCode::Network,
                                   QStringLiteral("本机服务端口无法监听"));
            const auto info = listener->publicInfo();
            listenerState_ = std::move(bound);
            listener_ = listener.release();
            identity_ = info;
            connect(listener_, &dukto::ServiceListener::event, this,
                    [this](const QJsonObject &event) {
                        // 日期：2026-11-04；服务事件不累计，远端文件数据仍由核心工作线程流式处理。
                        accept(event);
                    });
            status_ = QStringLiteral("本机 TLS 服务监听 %1:%2").arg(address).arg(port);
        }
    } catch (const dukto::Error &error) {
        status_ = error.message;
    }
    emit changed();
}

// 日期：2026-11-04；原生多选文件或单目录，选择完成才创建传输任务。
void ServerPanel::chooseUpload(const QVariantMap &options, bool folder) {
    QStringList paths;
    if (folder) {
        const auto path =
            QFileDialog::getExistingDirectory(nullptr, QStringLiteral("选择上传目录"));
        if (!path.isEmpty())
            paths.append(path);
    } else {
        paths = QFileDialog::getOpenFileNames(nullptr, QStringLiteral("选择上传文件"));
    }
    if (paths.isEmpty())
        return;
    auto values = options;
    values["paths"] = paths;
    execute("upload", values);
}

// 日期：2026-11-04；主线程原生目录对话框，调用者决定用于共享或下载。
QString ServerPanel::chooseDirectory() {
    return QFileDialog::getExistingDirectory(nullptr, QStringLiteral("选择目录"));
}

// 日期：2026-11-04；仅返回路径，权限与秘密格式由生产核心后台核验。
QString ServerPanel::chooseCredential() {
    return QFileDialog::getOpenFileName(nullptr, QStringLiteral("选择配对文件"), QString(),
                                        QStringLiteral("JSON (*.json)"));
}

// 日期：2026-11-04；断开不同于取消终态，保留原 task/request 供继续。
void ServerPanel::disconnectTransfer() {
    if (action_)
        action_->cancel();
}
