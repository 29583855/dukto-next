#include "paralleltransfer.h"
#include "error.h"
#include "files.h"
#include "identity.h"
#include "service.h"
#include "shares.h"
#include "sourcefile.h"
#include "taskstore.h"
#include "transferprogress.h"
#include "transferscheduler.h"
#include <QDateTime>
#include <QElapsedTimer>
#include <array>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <exception>
#include <limits>
#include <map>
#include <mutex>
#include <vector>

namespace dukto {
namespace {
std::mutex registryMutex;
std::map<QString, std::weak_ptr<ParallelState>> registry;
int serverLanes = 0;
constexpr int MaximumLanes = 16;
} // namespace

struct ParallelState {
    struct Lane {
        bool attached = false;
        bool finished = false;
        std::deque<next::Frame> incoming;
        std::deque<next::Frame> outgoing;
        std::condition_variable ready;
    };
    QString directory;
    QUuid owner;
    QUuid task;
    QUuid session;
    QByteArray token;
    QByteArray identity;
    QPair<QString, QString> source;
    bool receiver = false;
    bool server = false;
    int count = 0;
    int cursor = 0;
    qint64 expires = 0;
    std::atomic_bool cancelled{false};
    std::mutex mutex;
    std::condition_variable changed;
    std::exception_ptr failure;
    std::array<Lane, MaximumLanes> lanes;
    std::unique_ptr<BufferCredit> credit;
    std::shared_ptr<TransferAdmission> admission;

    // 日期：2026-11-04；服务数据槽随最后一个工作者归还，弱注册记录不会持有已完成任务。
    ~ParallelState() {
        if (server) {
            std::lock_guard<std::mutex> lock(registryMutex);
            serverLanes -= count;
        }
    }
    // 日期：2026-11-05；失败广播给控制与每条通道，普通数据通知不会遗漏取消或异常等待者。
    void stop(const std::exception_ptr &error = {}) {
        std::lock_guard<std::mutex> lock(mutex);
        if (error && !failure)
            failure = error;
        cancelled.store(true);
        changed.notify_all();
        for (auto &lane : lanes)
            lane.ready.notify_all();
    }
    // 日期：2026-11-04；异常以原始明确错误返回，普通销毁取消不伪造成传输成功。
    void check() {
        std::lock_guard<std::mutex> lock(mutex);
        if (failure)
            std::rethrow_exception(failure);
        if (cancelled.load())
            throw Error(ExitCode::Cancelled, QStringLiteral("多通道会话已停止"), "parallel");
    }
    // 日期：2026-11-05；加入只通知控制等待者，同一数据槽不可重复加入或重放票据。
    void attach(int lane) {
        check();
        std::lock_guard<std::mutex> lock(mutex);
        if (lane < 0 || lane >= count || lanes[lane].attached ||
            QDateTime::currentMSecsSinceEpoch() > expires)
            throw Error(ExitCode::Permission, QStringLiteral("数据通道票据失效或重复加入"),
                        "parallel");
        lanes[lane].attached = true;
        changed.notify_one();
    }
    // 日期：2026-11-05；实际线程完成后只唤醒控制方，不能提前释放源清单或广播空闲数据通道。
    void finished(int lane) {
        std::lock_guard<std::mutex> lock(mutex);
        lanes[lane].finished = true;
        changed.notify_one();
    }
    // 日期：2026-11-05；控制与各数据槽独立等待，每 25ms 仍核对授权、断开和取消。
    void wait(const std::function<void()> &work, int lane = -1) {
        {
            std::unique_lock<std::mutex> lock(mutex);
            auto &condition = lane < 0 ? changed : lanes[lane].ready;
            condition.wait_for(lock, std::chrono::milliseconds(25));
        }
        check();
        if (work)
            work();
    }
    // 日期：2026-11-04；只有全部实际加入/结束才继续；加入期限不因单个通道发心跳而无限延长。
    void waitAll(bool finish, const std::function<void()> &work) {
        for (;;) {
            check();
            bool ready = true;
            {
                std::lock_guard<std::mutex> lock(mutex);
                for (int lane = 0; lane < count; ++lane)
                    ready = ready && (finish ? lanes[lane].finished : lanes[lane].attached);
            }
            if (ready)
                return;
            if (!finish && QDateTime::currentMSecsSinceEpoch() > expires)
                throw Error(ExitCode::Network, QStringLiteral("等待多数据通道加入超时"),
                            "parallel");
            wait(work);
        }
    }
    // 日期：2026-11-05；每通道最多两条控制消息，只唤醒所属工作者，避免每个片段广播所有线程。
    void send(int lane, next::Frame frame, const std::function<void()> &work) {
        for (;;) {
            check();
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (lanes[lane].outgoing.size() < 2) {
                    lanes[lane].outgoing.push_back(std::move(frame));
                    lanes[lane].ready.notify_one();
                    return;
                }
            }
            wait(work);
        }
    }
    // 日期：2026-11-05；网络线程仅等待所属通道，取出任务后通知控制方有空余队列槽。
    next::Frame command(int lane, const std::function<void()> &work) {
        for (;;) {
            check();
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (!lanes[lane].outgoing.empty()) {
                    auto result = std::move(lanes[lane].outgoing.front());
                    lanes[lane].outgoing.pop_front();
                    changed.notify_one();
                    return result;
                }
            }
            wait(work, lane);
        }
    }
    // 日期：2026-11-05；每通道仅一个片段槽，背压只等待所属槽，交付后只唤醒控制接收者。
    void deliver(int lane, next::Frame frame, const std::function<void()> &work) {
        for (;;) {
            check();
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (lanes[lane].incoming.empty()) {
                    lanes[lane].incoming.push_back(std::move(frame));
                    changed.notify_one();
                    return;
                }
            }
            wait(work, lane);
        }
    }
    // 日期：2026-11-05；轮转消费就绪通道，归还片段槽时只通知其生产者而不惊醒全部通道。
    std::pair<int, next::Frame> receive(const std::function<void()> &work) {
        for (;;) {
            check();
            {
                std::lock_guard<std::mutex> lock(mutex);
                for (int index = 0; index < count; ++index) {
                    const int lane = (cursor + index) % count;
                    if (!lanes[lane].incoming.empty()) {
                        auto result = std::move(lanes[lane].incoming.front());
                        lanes[lane].incoming.pop_front();
                        cursor = (lane + 1) % count;
                        lanes[lane].ready.notify_one();
                        return {lane, std::move(result)};
                    }
                }
            }
            wait(work);
        }
    }
};

namespace {
// 日期：2026-11-04；帧创建统一受协议正文上限检查，队列中不出现任意长度的控制对象。
next::Frame message(next::Type type, quint64 correlation, const QJsonObject &value) {
    const auto bytes = next::encodeControl(value);
    return {{type, correlation, static_cast<quint32>(bytes.size())}, bytes};
}

// 日期：2026-11-04；控制与数据通道都消费精确 busy 心跳，其他同类型消息不能被误吞。
next::Frame read(next::SecureChannel &channel, quint64 correlation,
                 const std::function<void()> &check) {
    for (;;) {
        if (check)
            check();
        auto frame = channel.read();
        if (frame.header.correlation != correlation)
            throw Error(ExitCode::Integrity, QStringLiteral("并行数据请求序号不同"), "parallel");
        if (frame.header.type == next::Type::TaskState &&
            next::parseControl(frame.payload) == QJsonObject{{"state", "busy"}})
            continue;
        if (frame.header.type == next::Type::Failure) {
            const auto value = next::parseControl(frame.payload);
            const int code = value["code"].toInt(-1);
            if (code < 1 || code > 7 || !value["stage"].isString() || !value["message"].isString())
                throw Error(ExitCode::Config, QStringLiteral("并行通道错误响应无效"), "parallel");
            throw Error(static_cast<ExitCode>(code), value["message"].toString(),
                        value["stage"].toString());
        }
        return frame;
    }
}

class Pulse final {
  public:
    // 日期：2026-11-04；每个 socket 的心跳仅由所属线程发出，不能在跨线程队列锁内操作网络。
    Pulse(next::SecureChannel &channel, quint64 correlation, ParallelState &state,
          std::function<void()> check)
        : channel_(channel), correlation_(correlation), state_(state), check_(std::move(check)) {
        elapsed_.start();
    }
    // 日期：2026-11-04；慢恢复/最终校验/队列背压期间仍检查断开、授权和所有会话失败。
    void operator()() {
        state_.check();
        channel_.checkpoint("parallel");
        if (check_)
            check_();
        if (elapsed_.elapsed() >= 250) {
            channel_.write(next::Type::TaskState, correlation_, {{"state", "busy"}});
            elapsed_.restart();
        }
    }

  private:
    next::SecureChannel &channel_;
    quint64 correlation_;
    ParallelState &state_;
    std::function<void()> check_;
    QElapsedTimer elapsed_;
};

// 日期：2026-11-04；任意数据任务都绑定任务、强清单和文件，块序号另显式加入。
QJsonObject identity(const ParallelState &state, quint64 file) {
    return {{"taskId", state.task.toString(QUuid::WithoutBraces)},
            {"manifest", QString::fromLatin1(state.identity.toHex())},
            {"file", QString::number(file)}};
}

// 日期：2026-11-05；发送工作者只从本机重验的冻结清单取源路径，远端任务不能传入绝对源路径。
void senderLane(next::SecureChannel &channel, ParallelState &state,
                const QPair<QString, QString> &backing, quint64 correlation,
                const std::function<void()> &check) {
    Pulse pulse(channel, correlation, state, check);
    const auto work = [&]() {
        // 日期：2026-11-04；重载清单和逐片读取都维持当前通道心跳，不把阻塞移到 GUI 线程。
        pulse();
    };
    PrivateStore local(backing.first);
    // 日期：2026-11-05；只读数据线程采用 1 MiB 页缓存目标，保留全部清单重验并使 16 通道适配总预算。
    StrongManifest manifest(local, backing.second, false, work, 1024);
    if (manifest.summary()["sha256"] != QString::fromLatin1(state.identity.toHex()))
        throw Error(ExitCode::Integrity, QStringLiteral("并行源清单身份不同"), "parallel");
    for (;;) {
        const auto frame = read(channel, correlation, work);
        const auto job = next::parseControl(frame.payload);
        if (frame.header.type == next::Type::Close &&
            job == QJsonObject{{"sessionId", state.session.toString(QUuid::WithoutBraces)}}) {
            channel.write(next::Type::Closed, correlation, job);
            return;
        }
        const auto file = next::decimal(job["file"], 10000000);
        const auto block = next::decimal(job["block"], std::numeric_limits<qint64>::max());
        auto expected = identity(state, file);
        expected["block"] = QString::number(block);
        if (frame.header.type != next::Type::Attach || job != expected)
            throw Error(ExitCode::Integrity, QStringLiteral("并行块任务绑定无效"), "parallel");
        const auto entry = manifest.entry(file);
        const auto blocks = manifest.blocks(file, block);
        if (entry.directory || entry.source.isEmpty() || blocks.isEmpty() ||
            blocks[0].toObject()["block"] != QString::number(block))
            throw Error(ExitCode::Integrity, QStringLiteral("并行块任务超出清单"), "parallel");
        const auto declared = blocks[0].toObject();
        const auto length = next::decimal(declared["bytes"], StrongBlockBytes);
        SourceFile source(entry.source);
        if (source.device().size() != entry.bytes ||
            !source.device().seek(static_cast<qint64>(block) * StrongBlockBytes))
            throw Error(ExitCode::Integrity, QStringLiteral("并行发送源长度或偏移已变化"),
                        "parallel");
        QCryptographicHash hash(QCryptographicHash::Sha256);
        for (quint32 offset = 0; offset < length;) {
            work();
            const auto bytes = source.device().read(qMin<qint64>(BufferSize, length - offset));
            if (bytes.isEmpty())
                throw Error(ExitCode::Integrity, QStringLiteral("并行发送源意外截断"), "parallel");
            hash.addData(bytes);
            source.verify();
            const auto body = next::encodeFragment({state.task, file, block, offset, bytes});
            channel.write(
                {{next::Type::Data, correlation, static_cast<quint32>(body.size())}, body});
            offset += static_cast<quint32>(bytes.size());
        }
        if (hash.result().toHex() != declared["sha256"].toString().toLatin1())
            throw Error(ExitCode::Integrity, QStringLiteral("并行发送源块内容已变化"), "parallel");
        source.verify();
        channel.write(next::Type::BlockDone, correlation, job);
        const auto ack = read(channel, correlation, work);
        if (ack.header.type != next::Type::BlockAck || next::parseControl(ack.payload) != job)
            throw Error(ExitCode::Integrity, QStringLiteral("并行持久块确认不匹配"), "parallel");
    }
}

// 日期：2026-11-04；网络接收工作者不碰文件日志；一个片段槽和 Qt 固定缓冲共同限制慢写入积压。
void receiverLane(next::SecureChannel &channel, ParallelState &state, int lane, quint64 correlation,
                  const std::function<void()> &check) {
    Pulse pulse(channel, correlation, state, check);
    const auto work = [&]() {
        // 日期：2026-11-04；空闲等待和慢磁盘背压仍泵送所属线程事件并观察任务取消。
        pulse();
    };
    for (;;) {
        auto command = state.command(lane, work);
        command.header.correlation = correlation;
        channel.write(command);
        if (command.header.type == next::Type::Close) {
            const auto closing = [&]() {
                // 日期：2026-11-04；Close
                // 之后只接收最后确认，不能再发心跳成为服务下一条旧序号请求。
                state.check();
                channel.checkpoint("parallel");
                if (check)
                    check();
            };
            const auto closed = read(channel, correlation, closing);
            if (closed.header.type != next::Type::Closed || closed.payload != command.payload)
                throw Error(ExitCode::Integrity, QStringLiteral("并行通道结束确认不同"),
                            "parallel");
            return;
        }
        if (command.header.type != next::Type::Attach)
            throw Error(ExitCode::Config, QStringLiteral("并行通道调度状态无效"), "parallel");
        for (;;) {
            auto frame = read(channel, correlation, work);
            const bool done = frame.header.type == next::Type::BlockDone;
            if (!done && frame.header.type != next::Type::Data)
                throw Error(ExitCode::Config, QStringLiteral("并行数据帧类型无效"), "parallel");
            state.deliver(lane, std::move(frame), work);
            if (done)
                break;
        }
        auto ack = state.command(lane, work);
        if (ack.header.type != next::Type::BlockAck)
            throw Error(ExitCode::Config, QStringLiteral("并行块尚未持久确认"), "parallel");
        ack.header.correlation = correlation;
        channel.write(ack);
    }
}
} // namespace

// 日期：2026-11-04；输入必须为规范十进制档位，既不接受零也不接受浮点或非支持的中间值。
int checkedChannels(const QJsonValue &value) {
    const int count = static_cast<int>(next::decimal(value, MaximumLanes));
    if (count != 1 && count != 2 && count != 4 && count != 8 && count != 16)
        throw Error(ExitCode::Config, QStringLiteral("并发通道须选择 1/2/4/8/16"), "parallel");
    return count;
}

// 日期：2026-11-05；只使用已获准的通道，所有数据工作线程退出前不提前归还全局任务及通道额度。
std::unique_ptr<ParallelTransfer>
ParallelTransfer::createServer(const QString &directory, const QUuid &owner, const QUuid &task,
                               StrongManifest &manifest, bool receiver, int requested,
                               const std::shared_ptr<TransferAdmission> &admission) {
    checkedChannels(QString::number(requested));
    auto state = std::make_shared<ParallelState>();
    if (!admission || admission->lanes() != requested)
        throw Error(ExitCode::Config, QStringLiteral("多通道缺少对应的全局授信"), "scheduler");
    state->admission = admission;
    state->directory = directory;
    state->owner = owner;
    state->task = task;
    state->session = QUuid::createUuid();
    state->token = randomCredential();
    state->identity = QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1());
    state->source = manifest.backing();
    state->receiver = receiver;
    state->expires = QDateTime::currentMSecsSinceEpoch() + 30000;
    {
        std::lock_guard<std::mutex> lock(registryMutex);
        int count = requested;
        while (count > MaximumLanes - serverLanes)
            count /= 2;
        if (!count)
            throw Error(ExitCode::Permission, QStringLiteral("数据通道额度繁忙，请稍后重试"),
                        "parallel");
        state->count = count;
        state->credit.reset(new BufferCredit(count * 1024 * 1024, true));
        state->server = true;
        serverLanes += count;
        for (auto item = registry.begin(); item != registry.end();) {
            if (item->second.expired())
                item = registry.erase(item);
            else
                ++item;
        }
        registry[state->session.toString(QUuid::WithoutBraces)] = state;
    }
    return std::unique_ptr<ParallelTransfer>(new ParallelTransfer(state));
}

// 日期：2026-11-04；服务包装对象不启动额外隐藏线程，数据线程由已有监听器创建和回收。
ParallelTransfer::ParallelTransfer(std::shared_ptr<ParallelState> state)
    : state_(std::move(state)) {
}

// 日期：2026-11-04；票据字段精确匹配，服务端授信通道数与秘密都不允许宽松转换。
ParallelTransfer::ParallelTransfer(const QJsonObject &ticket, const QUuid &task,
                                   const QByteArray &manifest, bool receiver)
    : state_(std::make_shared<ParallelState>()) {
    const QUuid session(ticket["sessionId"].toString());
    const auto token = QByteArray::fromHex(ticket["token"].toString().toLatin1());
    if (ticket.size() != 5 || session.isNull() ||
        ticket["sessionId"] != session.toString(QUuid::WithoutBraces) ||
        ticket["taskId"] != task.toString(QUuid::WithoutBraces) || manifest.size() != 32 ||
        ticket["manifest"] != QString::fromLatin1(manifest.toHex()) || token.size() != 32 ||
        ticket["token"] != QString::fromLatin1(token.toHex()))
        throw Error(ExitCode::Integrity, QStringLiteral("数据通道票据绑定无效"), "parallel");
    state_->task = task;
    state_->session = session;
    state_->token = token;
    state_->identity = manifest;
    state_->count = checkedChannels(ticket["lanes"]);
    state_->credit.reset(new BufferCredit(state_->count * 1024 * 1024, true));
    state_->receiver = receiver;
    state_->expires = QDateTime::currentMSecsSinceEpoch() + 30000;
}

// 日期：2026-11-04；退出时原子取消先唤醒背压队列，再等候客户端数据线程完成全部析构。
ParallelTransfer::~ParallelTransfer() {
    state_->stop();
    for (auto worker : workers_) {
        worker->wait();
        delete worker;
    }
}

// 日期：2026-11-04；随机秘密只用于当前进程活动会话，不持久化到任务表或 GUI 状态。
QJsonObject ParallelTransfer::ticket() const {
    return {{"sessionId", state_->session.toString(QUuid::WithoutBraces)},
            {"taskId", state_->task.toString(QUuid::WithoutBraces)},
            {"manifest", QString::fromLatin1(state_->identity.toHex())},
            {"token", QString::fromLatin1(state_->token.toHex())},
            {"lanes", QString::number(state_->count)}};
}

// 日期：2026-11-04；显示实际授予值，不以请求的线程数伪造活动网络并行度。
int ParallelTransfer::lanes() const {
    return state_->count;
}

// 日期：2026-11-04；每个 QThread 只拥有自己的 TLS 与只读清单，父线程只持有取消/队列状态。
void ParallelTransfer::startClients(const ClientProfile &profile, int timeoutMs,
                                    StrongManifest *sender) {
    if (!workers_.isEmpty() || state_->server || (!state_->receiver && !sender))
        throw Error(ExitCode::Config, QStringLiteral("客户端数据通道启动状态无效"), "parallel");
    const auto source = sender ? sender->backing() : QPair<QString, QString>();
    const auto value = ticket();
    for (int lane = 0; lane < state_->count; ++lane) {
        const auto state = state_;
        auto worker = QThread::create([profile, timeoutMs, source, value, lane, state]() {
            // 日期：2026-11-04；失败只向会话传播一次，任何通道失败都阻止批次假成功。
            try {
                RemoteClient remote(profile, timeoutMs, &state->cancelled);
                remote.authenticate();
                remote.runDataLane(value, lane, state, source);
                remote.close();
            } catch (...) {
                state->stop(std::current_exception());
            }
            state->finished(lane);
        });
        workers_.append(worker);
        worker->start();
    }
}

// 日期：2026-11-05；认证及加入匹配后核对数据授信，实际循环结束时撤销临时取消指针。
void ParallelTransfer::clientLane(next::SecureChannel &channel, const QJsonObject &, int lane,
                                  const std::shared_ptr<ParallelState> &state,
                                  const QPair<QString, QString> &source, quint64 correlation) {
    channel.classifyAsData();
    state->attach(lane);
    channel.observeCancellation(&state->cancelled);
    try {
        if (state->receiver)
            receiverLane(channel, *state, lane, correlation, {});
        else
            senderLane(channel, *state, source, correlation, {});
        channel.observeCancellation(nullptr);
    } catch (...) {
        channel.observeCancellation(nullptr);
        throw;
    }
}

// 日期：2026-11-05；数据连接认证并核对实时授权后转入数据额度，不能仅凭公开任务 UUID 加入。
void serveParallelLane(next::SecureChannel &channel, PrivateStore &store,
                       const Principal &principal, const std::function<Principal()> &reauthenticate,
                       const QJsonObject &request, quint64 correlation) {
    const QUuid id(request["sessionId"].toString());
    const auto token = QByteArray::fromHex(request["token"].toString().toLatin1());
    if (request.size() != 3 || id.isNull() ||
        request["sessionId"] != id.toString(QUuid::WithoutBraces) || token.size() != 32 ||
        request["token"] != QString::fromLatin1(token.toHex()))
        throw Error(ExitCode::Permission, QStringLiteral("数据通道加入凭据无效"), "parallel");
    std::shared_ptr<ParallelState> state;
    {
        std::lock_guard<std::mutex> lock(registryMutex);
        const auto found = registry.find(id.toString(QUuid::WithoutBraces));
        if (found != registry.end())
            state = found->second.lock();
    }
    if (!state || state->owner != principal.client || state->directory != store.directory() ||
        !secureEqual(state->token, token))
        throw Error(ExitCode::Permission, QStringLiteral("数据通道票据不属于当前活动任务"),
                    "parallel");
    const auto lane = static_cast<int>(next::decimal(request["lane"], state->count - 1));
    TaskStore tasks(store, false);
    const auto task = tasks.task(principal.client, state->task);
    const auto access = state->receiver ? Access::Upload : Access::Download;
    auto root = Shares(store).open(principal, task.share, access);
    if (root->share().root != task.root || task.manifest != state->identity ||
        task.state != "transferring" || !task.desired.isEmpty())
        throw Error(ExitCode::Permission, QStringLiteral("数据通道任务权限或状态已经变化"),
                    "parallel");
    channel.classifyAsData();
    state->attach(lane);
    QElapsedTimer authorization;
    authorization.start();
    const auto work = [&]() {
        // 日期：2026-11-04；每片段固定根检查，每 250ms 重查凭据/授权/停止请求，保持撤权语义。
        root->verify();
        if (authorization.elapsed() >= 250) {
            const auto current = Shares(store).open(reauthenticate(), task.share, access);
            const auto status = tasks.task(principal.client, task.id);
            if (current->share().root != task.root || !status.desired.isEmpty())
                throw Error(ExitCode::Permission, QStringLiteral("数据通道授权或任务请求已变化"),
                            "parallel");
            authorization.restart();
        }
    };
    channel.observeCancellation(&state->cancelled);
    try {
        channel.write(next::Type::Attached, correlation,
                      {{"sessionId", request["sessionId"]}, {"lane", request["lane"]}});
        if (state->receiver)
            receiverLane(channel, *state, lane, correlation, work);
        else
            senderLane(channel, *state, state->source, correlation, work);
        channel.observeCancellation(nullptr);
        state->finished(lane);
    } catch (...) {
        channel.observeCancellation(nullptr);
        state->stop(std::current_exception());
        state->finished(lane);
        throw;
    }
}

// 日期：2026-11-04；发送控制循环只交换目录/文件完成，实际块由各数据线程同时从固定源读取。
void ParallelTransfer::sendTree(
    next::SecureChannel &control, StrongManifest &manifest, quint64 correlation,
    const std::function<void()> &check,
    const std::function<void(const StrongEntry &, const QString &)> &completed) {
    const auto work = [&]() {
        // 日期：2026-11-04；控制心跳只由接收调度者发送，避免双向空闲心跳遗留到下一条请求。
        state_->check();
        control.checkpoint("parallel");
        if (check)
            check();
    };
    state_->waitAll(false, work);
    const auto count = next::decimal(manifest.summary()["entries"], 10000000);
    for (quint64 file = 1; file <= count; ++file) {
        const auto entry = manifest.entry(file);
        auto object = identity(*state_, file);
        object["kind"] = entry.directory ? "directory" : "parallel-file";
        const auto response = read(control, correlation, work);
        const auto value = next::parseControl(response.payload);
        object["path"] = value["path"];
        if (response.header.type != next::Type::Completed || value != object ||
            !value["path"].isString())
            throw Error(ExitCode::Integrity, QStringLiteral("并行文件完成确认不同"), "parallel");
        const auto path = validateRelativePath(value["path"].toString());
        if (completed)
            completed(entry, path);
    }
    if (!count) {
        const auto response = read(control, correlation, work);
        if (response.header.type != next::Type::Completed ||
            next::parseControl(response.payload) !=
                QJsonObject{{"taskId", state_->task.toString(QUuid::WithoutBraces)},
                            {"manifest", QString::fromLatin1(state_->identity.toHex())},
                            {"kind", "empty"}})
            throw Error(ExitCode::Integrity, QStringLiteral("空清单并行确认不同"), "parallel");
    }
    state_->waitAll(true, work);
}

// 日期：2026-11-05；单一日志执行者轮转消费 16 条网络输入，确认后即给空闲通道派发下一个缺块。
void ParallelTransfer::receiveTree(
    next::SecureChannel &control, StrongManifest &manifest, DurableReceive &receiver,
    quint64 correlation, const std::function<void()> &check,
    const std::function<void(const StrongEntry &, const QString &)> &completed,
    TransferProgress *progress) {
    Pulse pulse(control, correlation, *state_, check);
    const auto work = [&]() {
        // 日期：2026-11-04；日志重读、网络等待和全文件摘要共用当前控制心跳及实时授权检查。
        pulse();
    };
    state_->waitAll(false, work);
    const auto count = next::decimal(manifest.summary()["entries"], 10000000);
    const auto closeLanes = [&]() {
        // 日期：2026-11-04；最后文件完成前结束数据通道，确保完成消息之后没有旧 correlation 心跳。
        for (int lane = 0; lane < state_->count; ++lane)
            state_->send(lane,
                         message(next::Type::Close, 1,
                                 {{"sessionId", state_->session.toString(QUuid::WithoutBraces)}}),
                         work);
        state_->waitAll(true, work);
    };
    struct FileJob {
        StrongEntry entry;
        QString path;
        quint64 next = 0;
        quint64 blocks = 0;
    };
    for (quint64 first = 1; first <= count; first += MaximumLanes) {
        std::vector<FileJob> window;
        const auto last = qMin<quint64>(count, first + MaximumLanes - 1);
        for (quint64 file = first; file <= last; ++file) {
            work();
            FileJob item;
            item.entry = manifest.entry(file);
            item.path = receiver.prepare(file, work);
            if (!item.entry.directory) {
                receiver.openConcurrent(file, item.path, work);
                if (progress)
                    progress->restored(receiver.confirmed());
                item.blocks = static_cast<quint64>(item.entry.bytes / StrongBlockBytes +
                                                   (item.entry.bytes % StrongBlockBytes != 0));
            }
            window.push_back(std::move(item));
        }
        std::array<QJsonObject, MaximumLanes> jobs;
        std::array<quint32, MaximumLanes> offsets{};
        std::array<int, MaximumLanes> files{};
        size_t cursor = 0;
        int active = 0;
        const auto assign = [&](int lane) {
            // 日期：2026-11-04；文件窗口内轮转分配块，多个小文件与大文件可同时占用数据通道。
            for (size_t scanned = 0; scanned < window.size(); ++scanned) {
                const auto index = cursor;
                cursor = (cursor + 1) % window.size();
                auto &item = window[index];
                if (item.entry.directory || item.next == item.blocks)
                    continue;
                receiver.activate(item.entry.id);
                while (item.next < item.blocks && receiver.hasBlock(item.next)) {
                    work();
                    ++item.next;
                }
                if (item.next == item.blocks)
                    continue;
                auto job = identity(*state_, item.entry.id);
                job["block"] = QString::number(item.next++);
                jobs[lane] = job;
                offsets[lane] = 0;
                files[lane] = static_cast<int>(index);
                state_->send(lane, message(next::Type::Attach, 1, job), work);
                return true;
            }
            return false;
        };
        for (int lane = 0; lane < state_->count; ++lane)
            active += assign(lane) ? 1 : 0;
        while (active) {
            work();
            auto item = state_->receive(work);
            const int lane = item.first;
            const auto &frame = item.second;
            const auto &job = jobs[lane];
            if (job.isEmpty())
                throw Error(ExitCode::Integrity, QStringLiteral("空闲通道收到未分配数据"),
                            "parallel");
            const auto file = window[files[lane]].entry.id;
            receiver.activate(file);
            const auto block = job["block"].toString().toULongLong();
            if (frame.header.type == next::Type::Data) {
                const auto data = next::decodeFragment(frame.payload);
                if (data.task != state_->task || data.file != file || data.block != block ||
                    data.offset != offsets[lane])
                    throw Error(ExitCode::Integrity, QStringLiteral("并行片段超出分配块或顺序不同"),
                                "parallel");
                const auto before = receiver.confirmed();
                receiver.write(block, data.offset, data.bytes, work);
                if (progress)
                    progress->written(data.bytes.size(), receiver.confirmed() - before);
                offsets[lane] += static_cast<quint32>(data.bytes.size());
            } else if (frame.header.type == next::Type::BlockDone &&
                       next::parseControl(frame.payload) == job && receiver.hasBlock(block)) {
                state_->send(lane, message(next::Type::BlockAck, 1, job), work);
                jobs[lane] = {};
                if (!assign(lane))
                    --active;
            } else {
                throw Error(ExitCode::Integrity, QStringLiteral("并行块未完整同步或结束绑定不同"),
                            "parallel");
            }
        }
        for (auto &item : window) {
            // 日期：2026-11-04；窗口所有块均已确认才做长全摘要，其他通道此时空闲心跳而非阻塞写入。
            if (!item.entry.directory) {
                receiver.activate(item.entry.id);
                item.path = receiver.finish(work);
                receiver.closeCurrent();
            }
            if (item.entry.id == count) {
                closeLanes();
                if (progress)
                    progress->publish(true);
            }
            auto object = identity(*state_, item.entry.id);
            object["kind"] = item.entry.directory ? "directory" : "parallel-file";
            object["path"] = item.path;
            control.write(next::Type::Completed, correlation, object);
            if (completed)
                completed(item.entry, item.path);
        }
    }
    if (!count) {
        closeLanes();
        if (progress)
            progress->publish(true);
        control.write(next::Type::Completed, correlation,
                      {{"taskId", state_->task.toString(QUuid::WithoutBraces)},
                       {"manifest", QString::fromLatin1(state_->identity.toHex())},
                       {"kind", "empty"}});
    }
}
} // namespace dukto
