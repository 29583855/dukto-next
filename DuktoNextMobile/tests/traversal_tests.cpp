#include "core/error.h"
#include "core/nativecommit.h"
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QTextStream>
#include <cerrno>
#include <fcntl.h>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>

namespace {
// 日期：2026-11-25；失败立即中止，构建使用Release时也执行所有原生权限断言。
void require(bool condition, const char *message) {
    if (!condition)
        throw std::runtime_error(message);
}

struct PermissionRestore {
    QByteArray path;
    // 日期：2026-11-25；异常时恢复测试目录权限，由QTemporaryDir安全清理自建数据。
    ~PermissionRestore() {
        ::chmod(path.constData(), 0700);
    }
};

// 日期：2026-11-25；真实无读取权限祖先仍须可遍历，最终目录保留读写、身份复验和持久同步。
void exerciseSearchOnlyParent(const QString &root) {
    const auto parent = root + "/search-only";
    const auto child = parent + "/private";
    require(QDir().mkpath(child), "create directory");
    PermissionRestore restore{QFile::encodeName(parent)};
    require(::chmod(restore.path.constData(), 0111) == 0, "restrict ancestor permissions");
    const int denied = ::open(restore.path.constData(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    const int code = errno;
    if (denied >= 0)
        ::close(denied);
    require(denied < 0 && code == EACCES, "fixture must deny ancestor read");
    const int descriptors =
        QDir("/proc/self/fd").entryList(QDir::AllEntries | QDir::NoDotAndDotDot).size();
    for (int iteration = 0; iteration < 128; ++iteration) {
        dukto::PosixDirectory directory(child, false);
        directory.verify();
        require(!directory.identity().isEmpty(), "read stable identity");
        require(directory.createChild("nested") == (iteration == 0),
                "create child relative to pinned directory");
        directory.synchronize();
        dukto::PosixDirectory nested(child + "/nested/new", true);
        nested.verify();
    }
    require(QDir("/proc/self/fd").entryList(QDir::AllEntries | QDir::NoDotAndDotDot).size() ==
                descriptors,
            "directory traversal leaked descriptors");
}

// 日期：2026-11-25；O_PATH不允许中间或末级链接绕过逐层检查，路径替换仍被身份复验拒绝。
void exerciseRefusal(const QString &root) {
    const auto target = root + "/target";
    const auto alias = root + "/alias";
    require(QDir().mkpath(target + "/child"), "create symlink target");
    require(
        ::symlink(QFile::encodeName(target).constData(), QFile::encodeName(alias).constData()) == 0,
        "create test symlink");
    for (const auto &path : {alias, alias + "/child"}) {
        bool refused = false;
        try {
            dukto::PosixDirectory directory(path, false);
        } catch (const dukto::Error &error) {
            refused = error.code == dukto::ExitCode::Permission;
        }
        require(refused, "symlink directory must be refused");
    }
    dukto::PosixDirectory pinned(target, false);
    require(QDir().rename(target, target + "-old"), "rename pinned directory");
    require(QDir().mkpath(target), "replace pinned path");
    bool replaced = false;
    try {
        pinned.verify();
    } catch (const dukto::Error &error) {
        replaced = error.code == dukto::ExitCode::Permission;
    }
    require(replaced, "replaced directory identity must be refused");
}
} // namespace

// 日期：2026-11-25；非root Linux运行，输出机器可读收据，不将主机权限测试记为手机验收。
int main(int argc, char *argv[]) {
    QCoreApplication application(argc, argv);
    try {
        require(::geteuid() != 0, "test must run as non-root");
        QTemporaryDir directory;
        require(directory.isValid(), "create isolated test root");
        exerciseSearchOnlyParent(directory.path());
        exerciseRefusal(directory.path());
        const QJsonObject result{{"passed", true},
                                 {"deviceTest", false},
                                 {"searchOnlyAncestor", true},
                                 {"pinnedChildOperations", true},
                                 {"symlinkRefused", true},
                                 {"replacementRefused", true},
                                 {"iterations", 128},
                                 {"descriptorGrowth", 0}};
        QTextStream(stdout) << QJsonDocument(result).toJson(QJsonDocument::Compact) << '\n';
        return 0;
    } catch (const std::exception &error) {
        QTextStream(stderr) << error.what() << '\n';
        return 1;
    }
}
