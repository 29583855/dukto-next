#include "statedomain.h"
#include "error.h"
#include "files.h"
#include "privatestore.h"
#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>
#include <QtEndian>

namespace dukto {
constexpr int StateDomain::MarkerBytes;
namespace {
using Binding = StateDomain::Binding;

// 日期：2026-11-08；不完整、复制、换代或跨域绑定均停止使用，保留控制文件和原登记供显式恢复。
void invalid() {
    throw Error(ExitCode::Integrity, QStringLiteral("状态根预算域关联无效，保留原登记和标记"),
                "state-domain");
}

// 日期：2026-11-08；根观察只散列固定原生身份，路径别名不参与域身份或额度划分。
QByteArray nativeIdentity(const PrivateStore &store) {
    return QCryptographicHash::hash(store.identity(), QCryptographicHash::Sha256);
}

// 日期：2026-11-08；域、协调根代数、本地代数和两端原生身份共同生成根生命周期键。
QByteArray rootKey(const Binding &binding) {
    const auto input = QByteArray("dukto-state-root-v1\0", 20) + binding.domain.toRfc4122() +
                       binding.coordinator.toRfc4122() + binding.generation.toRfc4122() +
                       binding.nativeCoordinator + binding.nativeRoot +
                       QByteArray(1, binding.coordinatorRoot ? '\1' : '\2');
    return QCryptographicHash::hash(input, QCryptographicHash::Sha256);
}

// 日期：2026-11-08；固定256字节、小端版本/角色、零保留区和SHA-256，不存储用户绝对路径。
QByteArray encode(const Binding &binding) {
    QByteArray bytes(StateDomain::MarkerBytes, '\0');
    bytes.replace(0, 8, QByteArray("DKDOMN01", 8));
    qToLittleEndian(quint64(1), reinterpret_cast<uchar *>(bytes.data() + 8));
    qToLittleEndian(quint64(binding.coordinatorRoot ? 1 : 2),
                    reinterpret_cast<uchar *>(bytes.data() + 16));
    bytes.replace(24, 16, binding.domain.toRfc4122());
    bytes.replace(40, 16, binding.coordinator.toRfc4122());
    bytes.replace(56, 16, binding.generation.toRfc4122());
    bytes.replace(72, 16, binding.registration.toRfc4122());
    bytes.replace(88, 32, binding.nativeCoordinator);
    bytes.replace(120, 32, binding.nativeRoot);
    bytes.replace(152, 32, binding.key);
    bytes.replace(224, 32, QCryptographicHash::hash(bytes.left(224), QCryptographicHash::Sha256));
    return bytes;
}

// 日期：2026-11-08；先核对完整格式，再核对生命周期键及当前原生根，损坏或未知版本不视为空白。
Binding read(BudgetFile &file, const std::function<void()> &check, int timeoutMs) {
    BudgetFile::Lock lock(file, check, timeoutMs);
    if (file.size() != StateDomain::MarkerBytes)
        invalid();
    const auto bytes = file.read(0, StateDomain::MarkerBytes);
    const auto integer = [&bytes](int offset) {
        // 日期：2026-11-08；固定长度已核对，整数不依赖主机字节序或结构体布局。
        return qFromLittleEndian<quint64>(
            reinterpret_cast<const uchar *>(bytes.constData() + offset));
    };
    if (bytes.left(8) != QByteArray("DKDOMN01", 8) || integer(8) != 1 ||
        (integer(16) != 1 && integer(16) != 2))
        invalid();
    Binding result{QUuid::fromRfc4122(bytes.mid(24, 16)),
                   QUuid::fromRfc4122(bytes.mid(40, 16)),
                   QUuid::fromRfc4122(bytes.mid(56, 16)),
                   QUuid::fromRfc4122(bytes.mid(72, 16)),
                   bytes.mid(88, 32),
                   bytes.mid(120, 32),
                   bytes.mid(152, 32),
                   integer(16) == 1};
    if (result.domain.isNull() || result.coordinator.isNull() || result.generation.isNull() ||
        result.registration.isNull() || result.key != rootKey(result) || encode(result) != bytes ||
        result.nativeRoot !=
            QCryptographicHash::hash(file.rootIdentity(), QCryptographicHash::Sha256) ||
        (result.coordinatorRoot && (result.coordinator != result.generation ||
                                    result.nativeCoordinator != result.nativeRoot)))
        invalid();
    file.verify();
    return result;
}

// 日期：2026-11-08；比较全部固定观察，不能只比较UUID而忽略原生身份、角色和登记代数。
bool same(const Binding &left, const Binding &right) {
    return encode(left) == encode(right);
}

// 日期：2026-11-08；存在检查只决定是否尝试创建，权限和链接仍由实际原生打开核对。
bool markerExists(const PrivateStore &store) {
    const auto path = QDir(store.directory()).filePath("state-domain.bin");
    return QFileInfo::exists(path) || isLinkedPath(path);
}

// 日期：2026-11-08；固定标记只写新建空对象，短写/同步失败不回收已登记额度或覆盖未知现场。
void createMarker(const PrivateStore &store, const Binding &binding,
                  const std::function<void()> &check, int timeoutMs) {
    BudgetFile file(store, true, BudgetFile::Kind::Domain);
    BudgetFile::Lock lock(file, check, timeoutMs);
    file.write(0, encode(binding));
    file.synchronize();
    file.verify();
}
} // namespace

// 日期：2026-11-08；初始化先验证最低额度和空控制区；标记的256字节在写入之前由中央账本持久扣除。
void StateDomain::initialize(const PrivateStore &store, const StateBudget::Limits &limits) {
    if (!store.maintenance())
        throw Error(ExitCode::Permission, QStringLiteral("预算域初始化需要独占维护"),
                    "state-domain");
    if (limits.total < StateBudget::FileBytes + MarkerBytes ||
        limits.categories[1] < StateBudget::FileBytes + MarkerBytes)
        throw Error(ExitCode::Config, QStringLiteral("预算域额度不足以保存固定控制文件"),
                    "state-domain");
    const auto ledger = QDir(store.directory()).filePath("state-budget.bin");
    if (markerExists(store) || QFileInfo::exists(ledger) || isLinkedPath(ledger))
        invalid();
    Binding binding;
    binding.domain = QUuid::createUuid();
    binding.coordinator = binding.generation = QUuid::createUuid();
    binding.nativeCoordinator = binding.nativeRoot = nativeIdentity(store);
    binding.coordinatorRoot = true;
    binding.key = rootKey(binding);
    StateBudget::initialize(store, binding.domain, limits);
    StateBudget budget(store, binding.domain);
    binding.registration =
        budget.enroll(binding.key, StateBudget::Category::Metadata, MarkerBytes).registration;
    createMarker(store, binding, {}, 1000);
}

// 日期：2026-11-08；每次重开都验证中央标记和真实账本，复制整套控制文件也不能迁移原生根身份。
StateDomain::StateDomain(const PrivateStore &store, std::function<void()> check, int timeoutMs)
    : store_(store), marker_(store, false, BudgetFile::Kind::Domain), check_(std::move(check)),
      timeoutMs_(timeoutMs) {
    coordinator_ = read(marker_, check_, timeoutMs_);
    if (!coordinator_.coordinatorRoot)
        invalid();
    budget_.reset(new StateBudget(store_, coordinator_.domain, check_, timeoutMs_));
    verifyRegistration(coordinator_);
}

// 日期：2026-11-08；成员按逆序关闭，PrivateStore由调用方保证比域实例活得更久。
StateDomain::~StateDomain() = default;

// 日期：2026-11-08；每个使用入口重验协调根，中央标记换代不因旧句柄或相同域UUID被忽略。
void StateDomain::verifyCoordinator() {
    if (!same(read(marker_, check_, timeoutMs_), coordinator_))
        invalid();
    verifyRegistration(coordinator_);
}

// 日期：2026-11-08；根绑定只关联固定Metadata登记，旧/退役/未决记录不能重新自动登记为零占用。
void StateDomain::verifyRegistration(const Binding &binding) {
    const auto record = budget_->lookup(binding.key);
    if (record.registration != binding.registration ||
        record.category != StateBudget::Category::Metadata || record.pending ||
        record.committed != MarkerBytes || record.reserved != 0)
        invalid();
}

// 日期：2026-11-08；目标独占锁先于中央账本锁；创建失败保留已计量登记，不因异常退出退款。
StateDomain::Binding StateDomain::bind(const PrivateStore &store) {
    if (!store.maintenance())
        throw Error(ExitCode::Permission, QStringLiteral("状态根登记需要该根独占维护"),
                    "state-domain");
    verifyCoordinator();
    if (markerExists(store))
        return root(store);
    Binding binding;
    binding.domain = coordinator_.domain;
    binding.coordinator = coordinator_.coordinator;
    binding.generation = QUuid::createUuid();
    binding.nativeCoordinator = coordinator_.nativeRoot;
    binding.nativeRoot = nativeIdentity(store);
    binding.key = rootKey(binding);
    binding.registration =
        budget_->enroll(binding.key, StateBudget::Category::Metadata, MarkerBytes).registration;
    if (check_)
        check_();
    createMarker(store, binding, check_, timeoutMs_);
    return root(store);
}

// 日期：2026-11-08；共享根不创建任何文件；域、中央代数、两端原生身份及中央登记必须同时一致。
StateDomain::Binding StateDomain::root(const PrivateStore &store) {
    verifyCoordinator();
    BudgetFile file(store, false, BudgetFile::Kind::Domain);
    const auto binding = read(file, check_, timeoutMs_);
    if (binding.domain != coordinator_.domain || binding.coordinator != coordinator_.coordinator ||
        binding.nativeCoordinator != coordinator_.nativeRoot ||
        (binding.coordinatorRoot && !same(binding, coordinator_)) ||
        (!binding.coordinatorRoot && binding.nativeRoot == coordinator_.nativeRoot))
        invalid();
    verifyRegistration(binding);
    file.verify();
    return binding;
}

// 日期：2026-11-08；重新读取实际标记和中央登记后比较旧观察，目录生命周期换代不会继承旧资格。
void StateDomain::verify(const PrivateStore &store, const Binding &expected) {
    if (!same(root(store), expected))
        invalid();
}

// 日期：2026-11-08；账本内只有已登记对象；该查询不宣称任意文件、历史或临时正文已进入总额。
StateBudget::Usage StateDomain::usage() {
    verifyCoordinator();
    return budget_->usage();
}

// 日期：2026-11-08；配置不重建域、不换根代数、不退款；协调标记或登记失效时禁止改写账本。
StateBudget::Usage StateDomain::configure(quint64 expectedRevision,
                                          const StateBudget::Limits &limits) {
    verifyCoordinator();
    return budget_->configure(expectedRevision, limits);
}
} // namespace dukto
