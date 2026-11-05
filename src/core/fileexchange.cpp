#include "fileexchange.h"
#include "error.h"
#include "files.h"
#include "sourcefile.h"
#include "transferprogress.h"
#include <QElapsedTimer>
#include <QJsonArray>
#include <limits>

namespace dukto {
namespace {
// 日期：2026-11-04；子交换内所有帧必须绑定同一请求序号，不允许其他控制请求插入数据流。
next::Frame frame(next::SecureChannel &channel, next::Type type, quint64 correlation,
                  const std::function<void()> &check) {
    next::Frame value;
    for (;;) {
        if (check)
            check();
        value = channel.read();
        if (value.header.correlation != correlation || value.header.type != next::Type::TaskState)
            break;
        if (next::parseControl(value.payload) != QJsonObject{{"state", "busy"}})
            throw Error(ExitCode::Config, QStringLiteral("文件交换心跳字段无效"), "transfer");
    }
    if (value.header.correlation == correlation && value.header.type == next::Type::Failure) {
        const auto failure = next::parseControl(value.payload);
        const auto code = failure["code"].toInt(-1);
        if (code < 1 || code > 7 || !failure["stage"].isString() || !failure["message"].isString())
            throw Error(ExitCode::Config, QStringLiteral("文件交换错误响应无效"), "transfer");
        throw Error(static_cast<ExitCode>(code), failure["message"].toString(),
                    failure["stage"].toString());
    }
    if (value.header.correlation != correlation || value.header.type != type)
        throw Error(ExitCode::Config, QStringLiteral("文件交换响应类型或请求序号不符"), "transfer");
    return value;
}

// 日期：2026-11-04；文件控制消息绑定任务、文件 ID 和强清单身份，不能只凭连接顺序指定落盘对象。
QJsonObject identity(const QUuid &task, quint64 file, StrongManifest &manifest) {
    if (task.isNull() || !file)
        throw Error(ExitCode::Config, QStringLiteral("文件交换任务身份无效"), "transfer");
    return {{"taskId", task.toString(QUuid::WithoutBraces)},
            {"file", QString::number(file)},
            {"manifest", manifest.summary()["sha256"]}};
}

// 日期：2026-11-04；长读写每片段检查授权/取消，网络断开通过通道检查点及时观察。
void checkpoint(next::SecureChannel &channel, const std::function<void()> &check) {
    channel.checkpoint("transfer");
    if (check)
        check();
}

class SendFailureScope final {
  public:
    // 日期：2026-11-05；整个发送树包含目录/空文件/正文，任何阶段先保留同请求远端原始失败。
    SendFailureScope(next::SecureChannel &channel, quint64 correlation) : channel_(channel) {
        channel_.observePeerFailure(correlation);
    }
    // 日期：2026-11-05；异常退出也撤销观察，后续任务控制响应仍由其原有读取器严格验证。
    ~SendFailureScope() {
        channel_.observePeerFailure(0);
    }

  private:
    next::SecureChannel &channel_;
};

class Pulse final {
  public:
    // 日期：2026-11-04；本地清单冻结/恢复重读期间发送小心跳，避免对端误判为空闲超时。
    Pulse(next::SecureChannel &channel, quint64 correlation, const std::function<void()> &check)
        : channel_(channel), correlation_(correlation), check_(check) {
        elapsed_.start();
    }
    // 日期：2026-11-04；心跳不表示块确认或任务完成，每次仍先检查断开、取消和实时授权。
    void operator()() {
        checkpoint(channel_, check_);
        if (elapsed_.elapsed() >= 250) {
            channel_.write(next::Type::TaskState, correlation_, {{"state", "busy"}});
            elapsed_.restart();
        }
    }

  private:
    next::SecureChannel &channel_;
    quint64 correlation_;
    std::function<void()> check_;
    QElapsedTimer elapsed_;
};
} // namespace

// 日期：2026-11-04；每页等待导入确认，最终 seal 才确认持久冻结；每页至多 100 项，不累计队列。
void sendStrongManifest(next::SecureChannel &channel, const QUuid &task, StrongManifest &manifest,
                        quint64 correlation, const std::function<void()> &check) {
    if (task.isNull())
        throw Error(ExitCode::Config, QStringLiteral("清单交换任务身份无效"), "manifest");
    quint64 index = 0;
    const auto send = [&](const QString &kind, const QJsonValue &value) {
        // 日期：2026-11-04；序号只用于当前清单交换顺序，不能代替持久请求键或任务所属主体。
        checkpoint(channel, check);
        const QJsonObject message{{"taskId", task.toString(QUuid::WithoutBraces)},
                                  {"index", QString::number(index)},
                                  {"kind", kind},
                                  {"value", value}};
        channel.write(next::Type::Manifest, correlation, message);
        const auto ack =
            next::parseControl(frame(channel, next::Type::ManifestAck, correlation, check).payload);
        if (ack != QJsonObject{{"taskId", message["taskId"]}, {"index", message["index"]}})
            throw Error(ExitCode::Integrity, QStringLiteral("清单分页确认不匹配"), "manifest");
        ++index;
    };
    send("summary", manifest.summary());
    quint64 after = 0;
    for (;;) {
        const auto entries = manifest.entries(after);
        if (entries.isEmpty())
            break;
        send("entries", entries);
        for (const auto &value : entries) {
            const auto object = value.toObject();
            after = object["id"].toString().toULongLong();
            quint64 first = 0;
            if (object["type"] == "directory")
                continue;
            for (;;) {
                const auto blocks = manifest.blocks(after, first);
                if (blocks.isEmpty())
                    break;
                send("blocks", QJsonObject{{"file", QString::number(after)}, {"rows", blocks}});
                first += static_cast<quint64>(blocks.size());
            }
        }
    }
    send("seal", manifest.summary());
}

// 日期：2026-11-04；输入数据只能进入未冻结清单，最终 seal 重算内容编码而非信任远端摘要声明。
void receiveStrongManifest(next::SecureChannel &channel, const QUuid &task,
                           StrongManifest &manifest, const QByteArray &expected,
                           quint64 correlation, const std::function<void()> &check) {
    if (task.isNull() || expected.size() != 32)
        throw Error(ExitCode::Config, QStringLiteral("接收清单任务或期望身份无效"), "manifest");
    QJsonObject summary;
    Pulse pulse(channel, correlation, check);
    for (quint64 index = 0;; ++index) {
        checkpoint(channel, check);
        const auto message =
            next::parseControl(frame(channel, next::Type::Manifest, correlation, check).payload);
        if (message.size() != 4 || message["taskId"] != task.toString(QUuid::WithoutBraces) ||
            message["index"] != QString::number(index) || !message["kind"].isString())
            throw Error(ExitCode::Integrity, QStringLiteral("清单分页身份或顺序不匹配"),
                        "manifest");
        const auto kind = message["kind"].toString();
        const auto value = message["value"];
        bool sealed = false;
        if (index == 0) {
            if (kind != "summary" || !value.isObject() ||
                value.toObject()["sha256"] != QString::fromLatin1(expected.toHex()))
                throw Error(ExitCode::Integrity, QStringLiteral("清单初始内容身份不匹配"),
                            "manifest");
            summary = value.toObject();
        } else if (kind == "entries" && value.isArray() && !value.toArray().isEmpty()) {
            for (const auto &item : value.toArray()) {
                const auto entry = item.toObject();
                const auto hash = QByteArray::fromHex(entry["sha256"].toString().toLatin1());
                if (check)
                    check();
                if (entry.size() != 5 || !entry["path"].isString() || !entry["sha256"].isString() ||
                    entry["sha256"] != QString::fromLatin1(hash.toHex()) ||
                    (entry["type"] != "file" && entry["type"] != "directory"))
                    throw Error(ExitCode::Integrity, QStringLiteral("清单公开条目字段无效"),
                                "manifest");
                manifest.append({next::decimal(entry["id"], 10000000), entry["path"].toString(), "",
                                 entry["type"] == "directory",
                                 static_cast<qint64>(next::decimal(
                                     entry["bytes"], std::numeric_limits<qint64>::max())),
                                 hash});
            }
        } else if (kind == "blocks" && value.isObject()) {
            const auto object = value.toObject();
            if (object.size() != 2 || !object["rows"].isArray() ||
                object["rows"].toArray().isEmpty())
                throw Error(ExitCode::Integrity, QStringLiteral("清单块分页字段无效"), "manifest");
            const auto file = next::decimal(object["file"], 10000000);
            for (const auto &item : object["rows"].toArray()) {
                if (check)
                    check();
                const auto block = item.toObject();
                const auto hash = QByteArray::fromHex(block["sha256"].toString().toLatin1());
                if (block.size() != 3 || !block["sha256"].isString() ||
                    block["sha256"] != QString::fromLatin1(hash.toHex()))
                    throw Error(ExitCode::Integrity, QStringLiteral("清单块摘要字段无效"),
                                "manifest");
                manifest.appendBlock(
                    file, next::decimal(block["block"], std::numeric_limits<qint64>::max()),
                    static_cast<qint64>(next::decimal(block["bytes"], StrongBlockBytes)), hash);
            }
        } else if (kind == "seal" && value.isObject() && value.toObject() == summary) {
            manifest.seal(expected, [&]() {
                // 日期：2026-11-04；冻结重读受本地磁盘速度影响，周期心跳保持远端确认等待有效。
                pulse();
            });
            if (manifest.summary() != summary)
                throw Error(ExitCode::Integrity, QStringLiteral("清单冻结总计不匹配"), "manifest");
            sealed = true;
        } else {
            throw Error(ExitCode::Config, QStringLiteral("清单交换状态或页面类型无效"), "manifest");
        }
        channel.write(next::Type::ManifestAck, correlation,
                      {{"taskId", message["taskId"]}, {"index", message["index"]}});
        if (sealed)
            return;
    }
}

// 日期：2026-11-05；按强清单顺序发送，限定同请求失败观察；接收最终映射仍只返回相对路径。
void sendStrongTree(next::SecureChannel &channel, const QUuid &task, StrongManifest &manifest,
                    quint64 correlation, const std::function<void()> &check,
                    const std::function<void(const StrongEntry &, const QString &)> &completed) {
    SendFailureScope failureScope(channel, correlation);
    const auto count = next::decimal(manifest.summary()["entries"], 10000000);
    for (quint64 id = 1; id <= count; ++id) {
        checkpoint(channel, check);
        const auto entry = manifest.entry(id);
        QString path;
        if (entry.directory) {
            auto object = identity(task, id, manifest);
            object["kind"] = "directory";
            channel.write(next::Type::Attach, correlation, object);
            const auto ack = next::parseControl(
                frame(channel, next::Type::Attached, correlation, check).payload);
            auto expected = object;
            expected["path"] = ack["path"];
            if (ack != expected || !ack["path"].isString())
                throw Error(ExitCode::Integrity, QStringLiteral("目录接收确认身份无效"),
                            "transfer");
            path = validateRelativePath(ack["path"].toString());
        } else {
            path = sendStrongFile(channel, task, manifest, id, correlation, check);
        }
        if (completed)
            completed(entry, path);
    }
}

// 日期：2026-11-05；子文件始终进入本任务已预约父目录，目录/文件完成事件逐项报告。
void receiveStrongTree(next::SecureChannel &channel, const QUuid &task, StrongManifest &manifest,
                       DurableReceive &receiver, quint64 correlation,
                       const std::function<void()> &check,
                       const std::function<void(const StrongEntry &, const QString &)> &completed,
                       TransferProgress *progress) {
    const auto count = next::decimal(manifest.summary()["entries"], 10000000);
    Pulse pulse(channel, correlation, check);
    const auto work = [&]() {
        // 日期：2026-11-04；目录预约和文件恢复/校验也检查取消和连接，不能只在收数据时检查。
        pulse();
    };
    for (quint64 id = 1; id <= count; ++id) {
        const auto entry = manifest.entry(id);
        QString path;
        if (entry.directory) {
            auto object = identity(task, id, manifest);
            object["kind"] = "directory";
            const auto attach =
                next::parseControl(frame(channel, next::Type::Attach, correlation, check).payload);
            if (attach != object)
                throw Error(ExitCode::Integrity, QStringLiteral("目录接收绑定无效"), "transfer");
            path = receiver.prepare(id, work);
            object["path"] = path;
            if (progress && id == count)
                progress->publish(true);
            channel.write(next::Type::Attached, correlation, object);
        } else {
            const auto target = receiver.prepare(id, work);
            path = receiveStrongFile(channel, task, manifest, receiver, id, target, correlation,
                                     check, progress);
        }
        if (completed)
            completed(entry, path);
    }
}

// 日期：2026-11-04；只从固定源句柄读取，发送时同时校验块及全文件强摘要，不依赖大小/mtime。
QString sendStrongFile(next::SecureChannel &channel, const QUuid &task, StrongManifest &manifest,
                       quint64 file, quint64 correlation, const std::function<void()> &check) {
    const auto entry = manifest.entry(file);
    if (entry.directory || entry.source.isEmpty())
        throw Error(ExitCode::Config, QStringLiteral("发送文件缺少本地强清单源"), "transfer");
    auto object = identity(task, file, manifest);
    checkpoint(channel, check);
    channel.write(next::Type::Attach, correlation, object);
    const auto ready =
        next::parseControl(frame(channel, next::Type::Attached, correlation, check).payload);
    const auto blocks = static_cast<quint64>(entry.bytes / StrongBlockBytes +
                                             (entry.bytes % StrongBlockBytes != 0));
    const auto first = next::decimal(ready["block"], blocks);
    const auto bytes = next::decimal(ready["bytes"], static_cast<quint64>(entry.bytes));
    const auto expectedPrefix =
        first == blocks ? entry.bytes : static_cast<qint64>(first) * StrongBlockBytes;
    if (ready.size() != 5 || ready["taskId"] != object["taskId"] ||
        ready["file"] != object["file"] || ready["manifest"] != object["manifest"] ||
        bytes != static_cast<quint64>(expectedPrefix))
        throw Error(ExitCode::Integrity, QStringLiteral("接收端恢复确认不匹配"), "transfer");
    SourceFile source(entry.source);
    if (source.device().size() != entry.bytes)
        throw Error(ExitCode::Integrity, QStringLiteral("发送源长度与强清单不同"), "transfer");
    QCryptographicHash whole(QCryptographicHash::Sha256);
    Pulse pulse(channel, correlation, check);
    qint64 position = 0;
    for (quint64 block = 0; block < blocks; ++block) {
        const auto page = manifest.blocks(file, block);
        if (page.isEmpty())
            throw Error(ExitCode::Integrity, QStringLiteral("发送强清单缺少块"), "transfer");
        const auto expected = page[0].toObject();
        const auto length = expected["bytes"].toString().toLongLong();
        QCryptographicHash hash(QCryptographicHash::Sha256);
        for (qint64 offset = 0; offset < length;) {
            pulse();
            const auto data = source.device().read(qMin<qint64>(BufferSize, length - offset));
            if (data.isEmpty())
                throw Error(ExitCode::Integrity, QStringLiteral("发送源意外截断"), "transfer");
            hash.addData(data);
            whole.addData(data);
            if (block >= first) {
                const auto payload =
                    next::encodeFragment({task, file, block, static_cast<quint32>(offset), data});
                channel.write(
                    {{next::Type::Data, correlation, static_cast<quint32>(payload.size())},
                     payload});
            }
            offset += data.size();
            position += data.size();
        }
        if (hash.result().toHex() != expected["sha256"].toString().toLatin1())
            throw Error(ExitCode::Integrity, QStringLiteral("发送源块内容已变化"), "transfer");
        auto done = object;
        done["block"] = QString::number(block);
        channel.write(next::Type::BlockDone, correlation, done);
        const auto ack =
            next::parseControl(frame(channel, next::Type::BlockAck, correlation, check).payload);
        if (ack != done)
            throw Error(ExitCode::Integrity, QStringLiteral("接收块确认身份不匹配"), "transfer");
    }
    source.verify();
    if (position != entry.bytes || whole.result() != entry.sha256)
        throw Error(ExitCode::Integrity, QStringLiteral("发送源全文件内容与强清单不同"),
                    "transfer");
    checkpoint(channel, check);
    channel.write(next::Type::Finish, correlation, object);
    const auto completed =
        next::parseControl(frame(channel, next::Type::Completed, correlation, check).payload);
    if (completed.size() != 4 || completed["taskId"] != object["taskId"] ||
        completed["file"] != object["file"] || completed["manifest"] != object["manifest"] ||
        !completed["path"].isString())
        throw Error(ExitCode::Integrity, QStringLiteral("接收最终确认身份不匹配"), "transfer");
    return validateRelativePath(completed["path"].toString());
}

// 日期：2026-11-05；只有完整块落盘同步后发送块确认；最终独占提交和日志同步后发送文件完成。
QString receiveStrongFile(next::SecureChannel &channel, const QUuid &task, StrongManifest &manifest,
                          DurableReceive &receiver, quint64 file, const QString &destination,
                          quint64 correlation, const std::function<void()> &check,
                          TransferProgress *progress) {
    const auto object = identity(task, file, manifest);
    const auto attach =
        next::parseControl(frame(channel, next::Type::Attach, correlation, check).payload);
    if (attach != object)
        throw Error(ExitCode::Integrity, QStringLiteral("文件交换绑定与期望任务不同"), "transfer");
    Pulse pulse(channel, correlation, check);
    const auto work = [&]() {
        // 日期：2026-11-04；恢复重读和最终摘要期间同样持续重查授权及网络连接。
        pulse();
    };
    const auto first = receiver.open(file, destination, work);
    if (progress)
        progress->restored(receiver.confirmed());
    auto ready = object;
    ready["block"] = QString::number(first);
    ready["bytes"] = QString::number(receiver.confirmed());
    channel.write(next::Type::Attached, correlation, ready);
    const auto entry = manifest.entry(file);
    const auto blocks = static_cast<quint64>(entry.bytes / StrongBlockBytes +
                                             (entry.bytes % StrongBlockBytes != 0));
    for (quint64 block = 0; block < blocks; ++block) {
        const auto expected = manifest.blocks(file, block)[0].toObject();
        const auto length = expected["bytes"].toString().toLongLong();
        qint64 offset = 0;
        while (block >= first && offset < length) {
            const auto data =
                next::decodeFragment(frame(channel, next::Type::Data, correlation, check).payload);
            if (data.task != task || data.file != file || data.block != block ||
                data.offset != offset)
                throw Error(ExitCode::Integrity, QStringLiteral("文件片段身份或顺序不匹配"),
                            "transfer");
            const auto before = receiver.confirmed();
            receiver.write(block, data.offset, data.bytes, work);
            if (progress)
                progress->written(data.bytes.size(), receiver.confirmed() - before);
            offset += data.bytes.size();
        }
        auto done = object;
        done["block"] = QString::number(block);
        if (next::parseControl(frame(channel, next::Type::BlockDone, correlation, check).payload) !=
            done)
            throw Error(ExitCode::Integrity, QStringLiteral("块结束身份不匹配"), "transfer");
        channel.write(next::Type::BlockAck, correlation, done);
    }
    if (next::parseControl(frame(channel, next::Type::Finish, correlation, check).payload) !=
        object)
        throw Error(ExitCode::Integrity, QStringLiteral("文件结束身份不匹配"), "transfer");
    const auto path = receiver.finish(work);
    auto completed = object;
    completed["path"] = path;
    if (progress && file == next::decimal(manifest.summary()["entries"], 10000000))
        progress->publish(true);
    channel.write(next::Type::Completed, correlation, completed);
    return path;
}
} // namespace dukto
