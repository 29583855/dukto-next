#include "statebudget.h"
#include "buffercredit.h"
#include "error.h"
#include "privatestore.h"
#include <QCryptographicHash>
#include <QJsonArray>
#include <QStringList>
#include <QtEndian>
#include <limits>

namespace dukto {
constexpr int StateBudget::SlotCount;
constexpr qint64 StateBudget::FileBytes;
namespace {
constexpr int HeaderBytes = 512;
constexpr int SlotBytes = 256;
constexpr int JournalBytes = 4096;
constexpr qint64 JournalOffset = 4096;
constexpr qint64 SlotOffset = 8192;

// 日期：2026-11-08；所有格式错误停止准入，不将未知记录、损坏槽或版本差异当作空白。
void invalid() {
    throw Error(ExitCode::Integrity, QStringLiteral("预算账本格式、身份或记录不一致，保留现场"),
                "budget");
}

// 日期：2026-11-08；整数均按固定宽度小端编码，禁止依赖结构体填充和主机字节序。
void put(QByteArray &bytes, int offset, quint64 value) {
    qToLittleEndian(value, reinterpret_cast<uchar *>(bytes.data() + offset));
}

// 日期：2026-11-08；读取固定偏移的无符号整数，长度在调用前由格式契约验证。
quint64 get(const QByteArray &bytes, int offset) {
    return qFromLittleEndian<quint64>(reinterpret_cast<const uchar *>(bytes.constData() + offset));
}

// 日期：2026-11-08；持久长度只接受非负有符号64位范围，不能让高位值绕过总量限制。
qint64 amount(quint64 value) {
    if (value > quint64(std::numeric_limits<qint64>::max()))
        invalid();
    return qint64(value);
}

// 日期：2026-11-08；固定记录末32字节保存前缀SHA-256，不读取或散列业务正文。
QByteArray seal(QByteArray bytes) {
    const auto hash =
        QCryptographicHash::hash(bytes.left(bytes.size() - 32), QCryptographicHash::Sha256);
    bytes.replace(bytes.size() - 32, 32, hash);
    return bytes;
}

// 日期：2026-11-08；严格核对记录尺寸、校验和与保留字节，未知扩展不能被旧程序静默忽略。
void checkSeal(const QByteArray &bytes, int length, int used) {
    if (bytes.size() != length ||
        bytes.mid(used, length - 32 - used) != QByteArray(length - 32 - used, '\0') ||
        seal(bytes) != bytes)
        invalid();
}

// 日期：2026-11-08；聚合与修订不允许溢出，耗尽明确拒绝，避免回绕后伪造小占用或旧代数。
qint64 add(qint64 left, qint64 right) {
    if (left < 0 || right < 0 || left > std::numeric_limits<qint64>::max() - right)
        invalid();
    return left + right;
}

// 日期：2026-11-08；空和超长业务键均拒绝，键须由登记者结合真实生命周期生成，不能直接取文件名。
void checkKey(const QByteArray &key) {
    if (key.size() != 32 || key == QByteArray(32, '\0'))
        throw Error(ExitCode::Config, QStringLiteral("预算对象登记键必须为32字节非零身份"),
                    "budget");
}
} // namespace

struct StateBudget::Header {
    QUuid domain;
    QByteArray root;
    Limits limits;
    std::array<qint64, 4> committed{};
    std::array<qint64, 4> reserved{};
    quint64 revision = 1;
    int next = 0;
    // 日期：2026-11-08；头只保存固定四类别合计、固定额度和域身份，末尾保留零用于版本拒绝。
    QByteArray encode() const {
        QByteArray bytes(HeaderBytes, '\0');
        bytes.replace(0, 8, QByteArray("DKBUDG01", 8));
        put(bytes, 8, 1);
        bytes.replace(16, 16, domain.toRfc4122());
        bytes.replace(32, 32, root);
        put(bytes, 64, StateBudget::SlotCount);
        put(bytes, 72, revision);
        put(bytes, 80, quint64(limits.total));
        put(bytes, 88, quint64(next));
        for (int index = 0; index < 4; ++index) {
            put(bytes, 96 + 8 * index, quint64(limits.categories[index]));
            put(bytes, 128 + 8 * index, quint64(committed[index]));
            put(bytes, 160 + 8 * index, quint64(reserved[index]));
        }
        return seal(bytes);
    }
    // 日期：2026-11-08；版本、槽数、域、额度和合计均严格解析；账本自身的固定占用不能丢失。
    static Header decode(const QByteArray &bytes) {
        checkSeal(bytes, HeaderBytes, 192);
        if (bytes.left(8) != QByteArray("DKBUDG01", 8) || get(bytes, 8) != 1 ||
            get(bytes, 64) != StateBudget::SlotCount || get(bytes, 88) >= StateBudget::SlotCount)
            invalid();
        Header result;
        result.domain = QUuid::fromRfc4122(bytes.mid(16, 16));
        result.root = bytes.mid(32, 32);
        result.revision = get(bytes, 72);
        result.limits.total = amount(get(bytes, 80));
        result.next = int(get(bytes, 88));
        if (result.domain.isNull() || !result.revision || result.root == QByteArray(32, '\0'))
            invalid();
        for (int index = 0; index < 4; ++index) {
            result.limits.categories[index] = amount(get(bytes, 96 + 8 * index));
            result.committed[index] = amount(get(bytes, 128 + 8 * index));
            result.reserved[index] = amount(get(bytes, 160 + 8 * index));
        }
        if (result.committed[1] < StateBudget::FileBytes ||
            result.limits.total < StateBudget::FileBytes ||
            result.limits.categories[1] < StateBudget::FileBytes)
            invalid();
        result.usage();
        return result;
    }
    // 日期：2026-11-08；合计始终重新校验64位范围；真实超额照实报告并阻止新增预留。
    Usage usage() const {
        Usage result;
        result.domain = domain;
        result.revision = revision;
        result.limits = limits;
        result.committed = committed;
        result.reserved = reserved;
        for (int index = 0; index < 4; ++index) {
            result.totalCommitted = add(result.totalCommitted, committed[index]);
            result.totalReserved = add(result.totalReserved, reserved[index]);
            result.overdrawn = result.overdrawn ||
                               add(committed[index], reserved[index]) > limits.categories[index];
        }
        result.overdrawn =
            result.overdrawn || add(result.totalCommitted, result.totalReserved) > limits.total;
        return result;
    }
};

struct StateBudget::Slot {
    Record record;
    int phase = 0; // 0为空，1为已对账，2为未决，3为已退役墓碑。
    // 日期：2026-11-08；每槽固定256字节，业务身份、登记代数、操作代数和金额在同一校验记录中。
    QByteArray encode() const {
        if (phase == 0)
            return QByteArray(SlotBytes, '\0');
        QByteArray bytes(SlotBytes, '\0');
        put(bytes, 0, quint64(phase));
        bytes.replace(8, 32, record.key);
        bytes.replace(40, 16, record.registration.toRfc4122());
        bytes.replace(56, 16, record.operation.toRfc4122());
        bytes.replace(72, 16, record.actor.toRfc4122());
        put(bytes, 88, record.revision);
        put(bytes, 96, quint64(record.category));
        put(bytes, 104, quint64(record.committed));
        put(bytes, 112, quint64(record.reserved));
        return seal(bytes);
    }
    // 日期：2026-11-08；空槽只接受全零，墓碑保留旧登记代数；未决标记与操作身份必须同时有效。
    static Slot decode(const QByteArray &bytes, int index) {
        Slot result;
        result.record.slot = index;
        if (bytes == QByteArray(SlotBytes, '\0'))
            return result;
        checkSeal(bytes, SlotBytes, 120);
        const auto phase = get(bytes, 0);
        if (phase < 1 || phase > 3 || get(bytes, 96) > 3)
            invalid();
        result.phase = int(phase);
        auto &record = result.record;
        record.key = bytes.mid(8, 32);
        record.registration = QUuid::fromRfc4122(bytes.mid(40, 16));
        record.operation = QUuid::fromRfc4122(bytes.mid(56, 16));
        record.actor = QUuid::fromRfc4122(bytes.mid(72, 16));
        record.revision = get(bytes, 88);
        record.category = Category(get(bytes, 96));
        record.committed = amount(get(bytes, 104));
        record.reserved = amount(get(bytes, 112));
        record.pending = phase == 2;
        if (record.key == QByteArray(32, '\0') || record.registration.isNull() ||
            !record.revision || record.operation.isNull() != record.actor.isNull() ||
            (record.pending && record.operation.isNull()) ||
            (!record.pending && record.reserved != 0) ||
            (phase == 3 && (record.committed != 0 || !record.operation.isNull())))
            invalid();
        add(record.committed, record.reserved);
        return result;
    }
};

// 日期：2026-11-08；固定文件一次创建，初始化失败保留不完整原件并拒绝后续正常打开，绝不覆盖重试。
void StateBudget::initialize(const PrivateStore &store, const QUuid &domain, const Limits &limits) {
    if (domain.isNull() || limits.total < FileBytes || limits.categories[1] < FileBytes)
        throw Error(ExitCode::Config, QStringLiteral("预算域或账本固定保留额度无效"), "budget");
    for (const auto value : limits.categories)
        if (value < 0)
            throw Error(ExitCode::Config, QStringLiteral("预算类别额度不能为负"), "budget");
    BufferCredit credit(65536);
    BudgetFile file(store, true);
    BudgetFile::Lock lock(file, {}, 0);
    Header header;
    header.domain = domain;
    header.root = QCryptographicHash::hash(file.rootIdentity(), QCryptographicHash::Sha256);
    header.limits = limits;
    header.committed[1] = FileBytes;
    header.usage();
    const QByteArray zero(8192, '\0');
    for (qint64 offset = 0; offset < FileBytes; offset += zero.size())
        file.write(offset, zero.left(int(qMin<qint64>(zero.size(), FileBytes - offset))));
    file.write(0, header.encode());
    file.synchronize();
    file.verify();
}

// 日期：2026-11-08；打开后完整核对一次；恢复写前日志失败时原预留保持，不创建替代账本。
StateBudget::StateBudget(const PrivateStore &store, const QUuid &domain,
                         std::function<void()> check, int timeoutMs)
    : store_(store), file_(store, false), domain_(domain),
      root_(QCryptographicHash::hash(file_.rootIdentity(), QCryptographicHash::Sha256)),
      check_(std::move(check)), timeoutMs_(timeoutMs) {
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    audit(load());
}

// 日期：2026-11-08；析构只关闭本实例文件，未决授信与已登记占用保留给实际后续核对。
StateBudget::~StateBudget() = default;

// 日期：2026-11-08；先核对日志及其前后完整状态，再按固定新状态重放；损坏日志从不降级为无日志。
StateBudget::Header StateBudget::load() {
    file_.verify();
    if (file_.size() != FileBytes)
        invalid();
    if (file_.read(HeaderBytes, int(JournalOffset - HeaderBytes)) !=
        QByteArray(int(JournalOffset - HeaderBytes), '\0'))
        invalid();
    const auto journal = file_.read(JournalOffset, JournalBytes);
    if (journal != QByteArray(JournalBytes, '\0')) {
        const bool configuration = journal.left(8) == QByteArray("DKBUDCF1", 8);
        checkSeal(journal, JournalBytes, configuration ? 1064 : 1576);
        if (configuration
                ? get(journal, 8) != 1
                : (journal.left(8) != QByteArray("DKBUDTX1", 8) || get(journal, 8) >= SlotCount))
            invalid();
        const int index = int(get(journal, 8));
        const auto oldHeader = Header::decode(journal.mid(40, HeaderBytes));
        const auto newHeader = Header::decode(journal.mid(552, HeaderBytes));
        const auto oldSlot = Slot::decode(journal.mid(1064, SlotBytes), index);
        const auto newSlot = Slot::decode(journal.mid(1320, SlotBytes), index);
        if (oldHeader.domain != domain_ || oldHeader.root != root_ || newHeader.domain != domain_ ||
            newHeader.root != root_ || oldHeader.revision == std::numeric_limits<quint64>::max() ||
            newHeader.revision != oldHeader.revision + 1 ||
            get(journal, 16) != oldHeader.revision || get(journal, 24) != newHeader.revision ||
            get(journal, 32) != 0)
            invalid();
        const auto expected = configuration ? configured(oldHeader, newHeader.limits)
                                            : adjusted(oldHeader, oldSlot, newSlot, false);
        if (expected.encode() != newHeader.encode())
            invalid();
        const auto currentHeader = file_.read(0, HeaderBytes);
        const auto currentSlot =
            configuration ? QByteArray()
                          : file_.read(SlotOffset + qint64(index) * SlotBytes, SlotBytes);
        if ((seal(currentHeader) == currentHeader && currentHeader != oldHeader.encode() &&
             currentHeader != newHeader.encode()) ||
            (!configuration &&
             (currentSlot == QByteArray(SlotBytes, '\0') || seal(currentSlot) == currentSlot) &&
             currentSlot != oldSlot.encode() && currentSlot != newSlot.encode()))
            invalid();
        if (!configuration)
            file_.write(SlotOffset + qint64(index) * SlotBytes, newSlot.encode());
        file_.write(0, newHeader.encode());
        file_.synchronize();
        audit(newHeader);
        file_.write(JournalOffset, QByteArray(JournalBytes, '\0'));
        file_.synchronize();
    }
    auto result = Header::decode(file_.read(0, HeaderBytes));
    if (result.domain != domain_ || result.root != root_)
        invalid();
    file_.verify();
    return result;
}

// 日期：2026-11-08；固定槽逐项核对，不一次读取全部登记或随对象数增长内存；墓碑不占已用总量。
void StateBudget::audit(const Header &header) {
    std::array<qint64, 4> committed{}, reserved{};
    committed[1] = FileBytes;
    for (int index = 0; index < SlotCount; ++index) {
        const auto slot =
            Slot::decode(file_.read(SlotOffset + qint64(index) * SlotBytes, SlotBytes), index);
        if (slot.phase == 1 || slot.phase == 2) {
            const auto category = int(slot.record.category);
            committed[category] = add(committed[category], slot.record.committed);
            reserved[category] = add(reserved[category], slot.record.reserved);
        }
    }
    if (committed != header.committed || reserved != header.reserved)
        invalid();
}

// 日期：2026-11-08；合计变更只来自同一固定槽的差异，事务不等待网络、扫描业务目录或调用SQLite。
StateBudget::Header StateBudget::adjusted(const Header &before, const Slot &oldSlot,
                                          const Slot &newSlot, bool admission) const {
    auto result = before;
    if (result.revision == std::numeric_limits<quint64>::max())
        invalid();
    ++result.revision;
    if (oldSlot.phase == 1 || oldSlot.phase == 2) {
        const int category = int(oldSlot.record.category);
        if (result.committed[category] < oldSlot.record.committed ||
            result.reserved[category] < oldSlot.record.reserved)
            invalid();
        result.committed[category] -= oldSlot.record.committed;
        result.reserved[category] -= oldSlot.record.reserved;
    }
    if (newSlot.phase == 1 || newSlot.phase == 2) {
        const int category = int(newSlot.record.category);
        result.committed[category] = add(result.committed[category], newSlot.record.committed);
        result.reserved[category] = add(result.reserved[category], newSlot.record.reserved);
    }
    result.next = (newSlot.record.slot + 1) % SlotCount;
    if (admission && result.usage().overdrawn) {
        for (int index = 0; index < 4; ++index)
            if (add(result.committed[index], result.reserved[index]) >
                add(before.committed[index], before.reserved[index]))
                throw Error(ExitCode::Disk, QStringLiteral("磁盘预算不足，原对象与恢复记录保持"),
                            "budget-full");
    }
    result.usage();
    return result;
}

// 日期：2026-11-08；额度不能为负或丢失控制区，不能用缩小额度掩盖保留的实际占用和未决预留。
StateBudget::Header StateBudget::configured(const Header &before, const Limits &limits) const {
    if (limits.total < FileBytes || limits.categories[1] < FileBytes)
        throw Error(ExitCode::Config, QStringLiteral("预算不能低于固定控制区占用"), "budget");
    for (const auto value : limits.categories)
        if (value < 0)
            throw Error(ExitCode::Config, QStringLiteral("预算类别额度不能为负"), "budget");
    auto after = before;
    if (after.revision == std::numeric_limits<quint64>::max())
        invalid();
    ++after.revision;
    after.limits = limits;
    if (after.usage().overdrawn)
        throw Error(ExitCode::Disk, QStringLiteral("新预算小于已有占用及保留额，原配置保持"),
                    "budget-full");
    return after;
}

// 日期：2026-11-08；意图同步成功后才更新数据；任何阶段失败均不返回已发放资格，下次仅向前重放。
void StateBudget::commit(const Header &before, const Header &after, int index,
                         const QByteArray &oldSlot, const QByteArray &newSlot) {
    QByteArray journal(JournalBytes, '\0');
    journal.replace(0, 8, QByteArray("DKBUDTX1", 8));
    put(journal, 8, quint64(index));
    put(journal, 16, before.revision);
    put(journal, 24, after.revision);
    journal.replace(40, HeaderBytes, before.encode());
    journal.replace(552, HeaderBytes, after.encode());
    journal.replace(1064, SlotBytes, oldSlot);
    journal.replace(1320, SlotBytes, newSlot);
    file_.write(JournalOffset, seal(journal));
    file_.synchronize();
    file_.write(SlotOffset + qint64(index) * SlotBytes, newSlot);
    file_.write(0, after.encode());
    file_.synchronize();
    file_.write(JournalOffset, QByteArray(JournalBytes, '\0'));
    file_.synchronize();
    file_.verify();
}

// 日期：2026-11-08；固定配置意图与原槽事务互斥，意图/头/清零分别同步；失败保留现场供向前恢复。
void StateBudget::commitConfiguration(const Header &before, const Header &after) {
    QByteArray journal(JournalBytes, '\0');
    journal.replace(0, 8, QByteArray("DKBUDCF1", 8));
    put(journal, 8, 1);
    put(journal, 16, before.revision);
    put(journal, 24, after.revision);
    journal.replace(40, HeaderBytes, before.encode());
    journal.replace(552, HeaderBytes, after.encode());
    file_.write(JournalOffset, seal(journal));
    file_.synchronize();
    file_.write(0, after.encode());
    file_.synchronize();
    file_.write(JournalOffset, QByteArray(JournalBytes, '\0'));
    file_.synchronize();
    file_.verify();
}

// 日期：2026-11-08；调用方观察必须与当前槽的全部状态匹配，不能用旧金额或新构造nonce绕过并发协调。
StateBudget::Slot StateBudget::checked(const Record &record, const Header &header) {
    Q_UNUSED(header)
    if (record.slot < 0 || record.slot >= SlotCount)
        invalid();
    const auto slot = Slot::decode(
        file_.read(SlotOffset + qint64(record.slot) * SlotBytes, SlotBytes), record.slot);
    const auto &actual = slot.record;
    if ((slot.phase != 1 && slot.phase != 2) || actual.key != record.key ||
        actual.registration != record.registration || actual.operation != record.operation ||
        actual.actor != record.actor || actual.revision != record.revision ||
        actual.category != record.category || actual.committed != record.committed ||
        actual.reserved != record.reserved || actual.pending != record.pending)
        throw Error(ExitCode::Integrity, QStringLiteral("预算对象观察已过期，需重新核对实际对象"),
                    "budget-stale");
    return slot;
}

// 日期：2026-11-08；逐槽查找既有生命周期键并记录首个空槽；未决/同键不能重建一份新额度。
StateBudget::Record StateBudget::enroll(const QByteArray &key, Category category,
                                        qint64 committed) {
    checkKey(key);
    if (quint64(category) > 3 || committed < 0)
        throw Error(ExitCode::Config, QStringLiteral("预算类别或登记占用无效"), "budget");
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    const auto header = load();
    int free = -1;
    QByteArray old;
    for (int offset = 0; offset < SlotCount; ++offset) {
        const int index = (header.next + offset) % SlotCount;
        const auto raw = file_.read(SlotOffset + qint64(index) * SlotBytes, SlotBytes);
        const auto slot = Slot::decode(raw, index);
        if ((slot.phase == 1 || slot.phase == 2) && slot.record.key == key) {
            if (slot.record.category != category || slot.record.committed != committed ||
                slot.record.pending)
                throw Error(ExitCode::Integrity, QStringLiteral("预算重复登记与当前对象不一致"),
                            "budget-stale");
            return slot.record;
        }
        if ((slot.phase == 0 || slot.phase == 3) && free < 0) {
            free = index;
            old = raw;
        }
    }
    if (free < 0)
        throw Error(ExitCode::Disk, QStringLiteral("预算固定记录槽已满，需核对并退役已释放对象"),
                    "budget-slots");
    Slot slot;
    slot.phase = 1;
    slot.record = {free, key, QUuid::createUuid(), {}, {}, 1, category, committed, 0, false};
    const auto after = adjusted(header, Slot::decode(old, free), slot, true);
    commit(header, after, free, old, slot.encode());
    return slot.record;
}

// 日期：2026-11-08；有界逐槽读取真实记录，缺失不是零占用的新对象；调用方须显式登记生命周期。
StateBudget::Record StateBudget::lookup(const QByteArray &key) {
    checkKey(key);
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    load();
    for (int index = 0; index < SlotCount; ++index) {
        const auto slot =
            Slot::decode(file_.read(SlotOffset + qint64(index) * SlotBytes, SlotBytes), index);
        if ((slot.phase == 1 || slot.phase == 2) && slot.record.key == key)
            return slot.record;
    }
    throw Error(ExitCode::Config, QStringLiteral("预算对象尚未登记或已经退役"), "budget-missing");
}

// 日期：2026-11-08；已有数据不受新准入额度否认，持久记录只增不减；未决操作和其他类别不得被覆盖。
StateBudget::Record StateBudget::accountExisting(const QByteArray &key, qint64 observedCharge) {
    if (!store_.maintenance())
        throw Error(ExitCode::Permission, QStringLiteral("已有对象计量需要协调根独占维护"),
                    "budget");
    checkKey(key);
    if (observedCharge < 0)
        throw Error(ExitCode::Config, QStringLiteral("已有对象占用不能为负数"), "budget");
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    const auto header = load();
    int selected = -1;
    QByteArray previous;
    for (int index = 0; index < SlotCount; ++index) {
        const auto raw = file_.read(SlotOffset + qint64(index) * SlotBytes, SlotBytes);
        const auto slot = Slot::decode(raw, index);
        if ((slot.phase == 1 || slot.phase == 2) && slot.record.key == key) {
            if (slot.record.category != Category::Unknown || slot.record.pending)
                throw Error(ExitCode::Integrity,
                            QStringLiteral("已有对象类别或未决授信不能被观察覆盖"), "budget-stale");
            if (slot.record.committed >= observedCharge)
                return slot.record;
            selected = index;
            previous = raw;
            break;
        }
        if ((slot.phase == 0 || slot.phase == 3) && selected < 0) {
            selected = index;
            previous = raw;
        }
    }
    if (selected < 0)
        throw Error(ExitCode::Disk, QStringLiteral("预算固定记录槽已满，已有计量保留，需显式核对"),
                    "budget-slots");
    const auto old = Slot::decode(previous, selected);
    Slot slot = old;
    if (old.phase == 1) {
        if (slot.record.revision == std::numeric_limits<quint64>::max())
            invalid();
        ++slot.record.revision;
        slot.record.committed = observedCharge;
    } else {
        slot.phase = 1;
        slot.record = {selected, key,  QUuid::createUuid(), {},
                       {},       1,    Category::Unknown,   observedCharge,
                       0,        false};
    }
    const auto after = adjusted(header, old, slot, false);
    commit(header, after, selected, previous, slot.encode());
    return slot.record;
}

// 日期：2026-11-08；先持久化对象级未决状态；相同对象的另一连接必须在预算锁外重新核对或等待。
StateBudget::Record StateBudget::reserve(const Record &expected, qint64 maximumCharge) {
    if (maximumCharge < 0)
        throw Error(ExitCode::Config, QStringLiteral("预算增长上界无效"), "budget");
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    const auto header = load();
    const auto old = checked(expected, header);
    if (old.phase != 1)
        throw Error(ExitCode::Disk, QStringLiteral("预算对象有未决I/O，保留预留并等待核对"),
                    "budget-pending");
    auto slot = old;
    if (slot.record.revision == std::numeric_limits<quint64>::max())
        invalid();
    ++slot.record.revision;
    slot.phase = 2;
    slot.record.pending = true;
    slot.record.operation = QUuid::createUuid();
    slot.record.actor = actor_;
    slot.record.reserved = qMax<qint64>(0, maximumCharge - slot.record.committed);
    const auto after = adjusted(header, old, slot, true);
    commit(header, after, expected.slot, old.encode(), slot.encode());
    return slot.record;
}

// 日期：2026-11-09；角色包络在独立短锁内持久增加，额度不足不改变旧槽或允许后续原生I/O。
StateBudget::Record StateBudget::admitHighWater(const QByteArray &key, Category category,
                                                qint64 maximumCharge) {
    checkKey(key);
    if (quint64(category) > 3 || maximumCharge < 0)
        throw Error(ExitCode::Config, QStringLiteral("预算高水位参数无效"), "budget");
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    const auto header = load();
    int selected = -1;
    QByteArray previous;
    for (int index = 0; index < SlotCount; ++index) {
        const auto raw = file_.read(SlotOffset + qint64(index) * SlotBytes, SlotBytes);
        const auto slot = Slot::decode(raw, index);
        if ((slot.phase == 1 || slot.phase == 2) && slot.record.key == key) {
            if (slot.record.category != category || slot.record.pending)
                throw Error(ExitCode::Integrity, QStringLiteral("预算高水位角色存在冲突"),
                            "budget-stale");
            if (slot.record.committed >= maximumCharge)
                return slot.record;
            selected = index;
            previous = raw;
            break;
        }
        if ((slot.phase == 0 || slot.phase == 3) && selected < 0) {
            selected = index;
            previous = raw;
        }
    }
    if (selected < 0)
        throw Error(ExitCode::Disk, QStringLiteral("预算固定角色槽已满"), "budget-slots");
    const auto old = Slot::decode(previous, selected);
    Slot slot = old;
    if (old.phase == 1) {
        if (slot.record.revision == std::numeric_limits<quint64>::max())
            invalid();
        ++slot.record.revision;
        slot.record.committed = maximumCharge;
    } else {
        slot.phase = 1;
        slot.record = {selected, key,      QUuid::createUuid(), {}, {},
                       1,        category, maximumCharge,       0,  false};
    }
    const auto after = adjusted(header, old, slot, true);
    commit(header, after, selected, previous, slot.encode());
    return slot.record;
}

// 日期：2026-11-09；扩展保持同一执行者与操作UUID，先持久增加预留；旧通知不能结算新修订。
StateBudget::Record StateBudget::extend(const Record &reservation, qint64 maximumCharge) {
    if (!reservation.pending || reservation.actor != actor_ || maximumCharge < 0)
        throw Error(ExitCode::Config, QStringLiteral("预算预留扩展参数无效"), "budget");
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    const auto header = load();
    const auto old = checked(reservation, header);
    if (old.phase != 2)
        throw Error(ExitCode::Integrity, QStringLiteral("预算扩展不属于未决操作"), "budget-stale");
    if (maximumCharge <= old.record.committed + old.record.reserved)
        return old.record;
    auto slot = old;
    if (slot.record.revision == std::numeric_limits<quint64>::max())
        invalid();
    ++slot.record.revision;
    slot.record.reserved = maximumCharge - slot.record.committed;
    const auto after = adjusted(header, old, slot, true);
    commit(header, after, reservation.slot, old.encode(), slot.encode());
    return slot.record;
}

// 日期：2026-11-08；完成通知幂等只接受最近一次确切操作；真实超预期占用不丢弃，后续准入受透支约束。
StateBudget::Record StateBudget::settle(const Record &reservation, qint64 actualCharge) {
    if (!reservation.pending || reservation.operation.isNull() || actualCharge < 0 ||
        reservation.slot < 0 || reservation.slot >= SlotCount)
        throw Error(ExitCode::Config, QStringLiteral("预算完成观察无效"), "budget");
    if (reservation.actor != actor_ && !store_.maintenance())
        throw Error(ExitCode::Permission, QStringLiteral("其他执行者的预算预留需要独占维护核对"),
                    "budget");
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    const auto header = load();
    const auto current = Slot::decode(
        file_.read(SlotOffset + qint64(reservation.slot) * SlotBytes, SlotBytes), reservation.slot);
    if (current.phase == 1 && current.record.key == reservation.key &&
        current.record.registration == reservation.registration &&
        current.record.operation == reservation.operation &&
        current.record.actor == reservation.actor &&
        reservation.revision < std::numeric_limits<quint64>::max() &&
        current.record.revision == reservation.revision + 1 &&
        current.record.category == reservation.category && current.record.committed == actualCharge)
        return current.record;
    const auto old = checked(reservation, header);
    auto slot = old;
    if (slot.record.revision == std::numeric_limits<quint64>::max())
        invalid();
    ++slot.record.revision;
    slot.phase = 1;
    slot.record.pending = false;
    slot.record.committed = actualCharge;
    slot.record.reserved = 0;
    const auto after = adjusted(header, old, slot, false);
    commit(header, after, reservation.slot, old.encode(), slot.encode());
    return slot.record;
}

// 日期：2026-11-08；仅独占维护允许按已证明释放的对象退款；墓碑与登记代数让重复调用无副作用。
void StateBudget::retire(const Record &expected) {
    if (!store_.maintenance())
        throw Error(ExitCode::Permission, QStringLiteral("预算退役需要独占维护及对象释放证据"),
                    "budget");
    if (expected.slot < 0 || expected.slot >= SlotCount)
        invalid();
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    const auto header = load();
    const auto current = Slot::decode(
        file_.read(SlotOffset + qint64(expected.slot) * SlotBytes, SlotBytes), expected.slot);
    if (current.phase == 3 && current.record.key == expected.key &&
        current.record.registration == expected.registration &&
        expected.revision < std::numeric_limits<quint64>::max() &&
        current.record.revision == expected.revision + 1)
        return;
    const auto old = checked(expected, header);
    if (old.phase != 1 || old.record.revision == std::numeric_limits<quint64>::max())
        throw Error(ExitCode::Integrity, QStringLiteral("未决预算对象不能退役"), "budget-pending");
    auto slot = old;
    slot.phase = 3;
    ++slot.record.revision;
    slot.record.committed = 0;
    slot.record.operation = QUuid();
    slot.record.actor = QUuid();
    const auto after = adjusted(header, old, slot, false);
    commit(header, after, expected.slot, old.encode(), slot.encode());
}

// 日期：2026-11-08；已停止所有状态使用者后才能解决遗留授信，仍通过确切操作与修订做幂等对账。
StateBudget::Record StateBudget::reconcile(const Record &expected, qint64 actualCharge) {
    if (!store_.maintenance())
        throw Error(ExitCode::Permission, QStringLiteral("遗留预算核对需要独占维护"), "budget");
    return settle(expected, actualCharge);
}

// 日期：2026-11-08；在同一短锁下读取持久合计，不遍历业务目录或打开SQLite连接。
StateBudget::Usage StateBudget::usage() {
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    return load().usage();
}

// 日期：2026-11-08；修订比较与持久更新处于同一账本锁内，相同配置不写盘；旧观察明确拒绝。
StateBudget::Usage StateBudget::configure(quint64 expectedRevision, const Limits &limits) {
    if (!store_.maintenance())
        throw Error(ExitCode::Permission, QStringLiteral("预算配置需要协调根独占维护"), "budget");
    BufferCredit credit(65536);
    BudgetFile::Lock lock(file_, check_, timeoutMs_);
    const auto before = load();
    if (before.revision != expectedRevision)
        throw Error(ExitCode::Integrity, QStringLiteral("预算修订已变化，请重新查询后修改"),
                    "budget-stale");
    if (before.limits.total == limits.total && before.limits.categories == limits.categories)
        return before.usage();
    const auto after = configured(before, limits);
    commitConfiguration(before, after);
    return after.usage();
}
// 日期：2026-11-08；只序列化已核对的固定合计，不枚举业务文件；剩余额度同时受类别和总额约束。
QJsonObject StateBudget::report(const Usage &usage, const QString &operation) {
    qint64 committed = 0, reserved = 0;
    bool overdrawn = false;
    for (int index = 0; index < 4; ++index) {
        if (usage.limits.categories[index] < 0)
            invalid();
        committed = add(committed, usage.committed[index]);
        reserved = add(reserved, usage.reserved[index]);
        overdrawn = overdrawn || add(usage.committed[index], usage.reserved[index]) >
                                     usage.limits.categories[index];
    }
    const auto consumed = add(committed, reserved);
    overdrawn = overdrawn || consumed > usage.limits.total;
    if (usage.domain.isNull() || !usage.revision || usage.limits.total < 0 ||
        committed != usage.totalCommitted || reserved != usage.totalReserved ||
        overdrawn != usage.overdrawn)
        invalid();
    const auto available = qMax(qint64(0), usage.limits.total - consumed);
    QJsonArray categories;
    const QStringList names{"history", "metadata", "body", "unknown"};
    for (int index = 0; index < 4; ++index) {
        const auto used = add(usage.committed[index], usage.reserved[index]);
        const auto limit = usage.limits.categories[index];
        categories.append(QJsonObject{
            {"name", names[index]},
            {"limit", QString::number(limit)},
            {"committed", QString::number(usage.committed[index])},
            {"reserved", QString::number(usage.reserved[index])},
            {"available",
             QString::number(overdrawn ? 0 : qMin(available, qMax(qint64(0), limit - used)))},
            {"deficit", QString::number(qMax(qint64(0), used - limit))},
            {"capacityState",
             used > limit ? "overdrawn"
                          : (overdrawn ? "domain-overdrawn"
                                       : (available == 0 ? "total-exhausted"
                                                         : (used == limit ? "category-exhausted"
                                                                          : "available")))}});
    }
    return {{"eventVersion", 1},
            {"event", "state-budget"},
            {"operation", operation},
            {"domain", usage.domain.toString(QUuid::WithoutBraces)},
            {"revision", QString::number(usage.revision)},
            {"limit", QString::number(usage.limits.total)},
            {"committed", QString::number(committed)},
            {"reserved", QString::number(reserved)},
            {"available", QString::number(overdrawn ? 0 : available)},
            {"deficit", QString::number(qMax(qint64(0), consumed - usage.limits.total))},
            {"capacityState",
             overdrawn ? "overdrawn" : (available == 0 ? "total-exhausted" : "available")},
            {"overdrawn", overdrawn},
            {"categories", categories},
            {"scope", "registered-ledger-objects"},
            {"wholeDomainAccounted", false},
            {"productionQuotaEnforced", false},
            {"reclaimableKnown", false},
            {"reclaimableBytes", QJsonValue(QJsonValue::Null)},
            {"message",
             QStringLiteral(
                 "已读取已登记状态预算；未覆盖全部磁盘占用，生产写前限制和自动回收尚未启用")}};
}
} // namespace dukto
