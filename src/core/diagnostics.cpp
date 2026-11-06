#include "diagnostics.h"
#include "buffercredit.h"
#include "error.h"
#include "files.h"
#include "sourcefile.h"
#include "tcplistener.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSqlDatabase>
#include <QSslSocket>
#include <QSysInfo>
#include <QTemporaryFile>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <io.h>
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace dukto {
namespace {
constexpr int MaximumReportBytes = 64 * 1024;

class DiagnosticTemporary final {
  public:
    // 日期：2026-11-07；固定既有父目录后独占创建临时普通文件，绝不创建用户目录树。
    explicit DiagnosticTemporary(const QString &directory) {
#ifdef Q_OS_WIN
        parent_.reset(new NativeDirectoryLock(directory, false));
        file_.reset(new QTemporaryFile(QDir(directory).filePath(".dukto-diagnostic-XXXXXX.part")));
        if (!static_cast<QTemporaryFile *>(file_.get())->open())
            throw Error(ExitCode::Disk, QStringLiteral("无法创建诊断临时文件"), "doctor");
        temporary_ = file_->fileName();
#else
        parent_.reset(new PosixDirectory(directory, false));
        file_.reset(new QFile);
        const int descriptor = parent_->createTemporary(temporary_);
        if (!file_->open(descriptor, QIODevice::WriteOnly, QFileDevice::AutoCloseHandle)) {
            ::close(descriptor);
            parent_->removeTemporary(temporary_);
            throw Error(ExitCode::Disk, QStringLiteral("无法打开诊断临时文件"), "doctor");
        }
#endif
    }
    // 日期：2026-11-07；异常只清理本次唯一临时文件，未提交报告不会留半份最终文件。
    ~DiagnosticTemporary() {
        file_.reset();
#ifdef Q_OS_WIN
        if (!temporary_.isEmpty())
            QFile::remove(temporary_);
#else
        parent_->removeTemporary(temporary_);
#endif
    }
    // 日期：2026-11-07；探测与导出共用短写检测及磁盘同步，真实盘满不能报告为成功。
    void write(const QByteArray &bytes) {
        writeAll(*file_, bytes);
        if (!file_->flush())
            throw Error(ExitCode::Disk, QStringLiteral("诊断文件刷新失败"), "doctor");
#ifdef Q_OS_WIN
        const bool synchronized =
            FlushFileBuffers(reinterpret_cast<HANDLE>(_get_osfhandle(file_->handle())));
#else
        const bool synchronized = ::fsync(file_->handle()) == 0;
#endif
        if (!synchronized)
            throw Error(ExitCode::Disk, QStringLiteral("诊断文件同步失败"), "doctor");
    }
    // 日期：2026-11-07；探测成功后显式检查删除结果，仍由固定父目录约束路径。
    void remove() {
#ifdef Q_OS_WIN
        static_cast<QTemporaryFile *>(file_.get())->setAutoRemove(false);
        file_.reset();
        if (!QFile::remove(temporary_))
            throw Error(ExitCode::Disk, QStringLiteral("诊断临时文件清理失败"), "doctor");
#else
        file_.reset();
        parent_->discardTemporary(temporary_);
#endif
        temporary_.clear();
    }
    // 日期：2026-11-07；最终报告仅独占发布给用户指定名称，同名竞争时保留已有文件。
    void commit(const QString &destination) {
#ifdef Q_OS_WIN
        static_cast<QTemporaryFile *>(file_.get())->setAutoRemove(false);
        file_.reset();
        const bool committed = renameNoReplace(temporary_, destination, true);
#else
        file_.reset();
        const bool committed =
            parent_->commitTemporary(temporary_, QFileInfo(destination).fileName());
#endif
        if (!committed)
            throw Error(ExitCode::Config, QStringLiteral("诊断报告目标已存在，请指定新名称"),
                        "doctor");
        temporary_.clear();
#ifndef Q_OS_WIN
        parent_->synchronize();
#endif
    }

  private:
    QString temporary_;
    std::unique_ptr<QFile> file_;
#ifdef Q_OS_WIN
    std::unique_ptr<NativeDirectoryLock> parent_;
#else
    std::unique_ptr<PosixDirectory> parent_;
#endif
};

// 日期：2026-11-07；只读取四个生产配置键，不枚举私有资料、令牌或任意用户目录。
QString validateSettings(QSettings &settings) {
    for (const auto &key : QStringList{"port", "timeout", "bind", "output"}) {
        if (!settings.contains(key))
            continue;
        const auto value = settings.value(key).toString();
        if (value.size() > 4096 || value.contains(QChar::Null))
            throw Error(ExitCode::Config, QStringLiteral("配置值长度或格式无效"), "doctor");
        if (key == "port" || key == "timeout") {
            bool valid = false;
            const auto number = value.toUInt(&valid);
            if (!valid || number == 0 || number > (key == "port" ? 65535U : 86400U))
                throw Error(ExitCode::Config, QStringLiteral("配置数值无效"), "doctor");
        }
        if (key == "bind" && QHostAddress(value).isNull())
            throw Error(ExitCode::Config, QStringLiteral("配置监听地址无效"), "doctor");
    }
    if (settings.status() != QSettings::NoError)
        throw Error(ExitCode::Config, QStringLiteral("配置不可读取或格式无效"), "doctor");
    return settings.value("output").toString();
}

// 日期：2026-11-07；INI先从固定普通源有界读取再解析独立快照，拒绝超大文件及路径替换。
QString inspectIni(const QString &path, bool required) {
    if (!QFileInfo::exists(path) && !isLinkedPath(path)) {
        if (required)
            throw Error(ExitCode::Config, QStringLiteral("显式配置文件不存在"), "doctor");
        return {};
    }
    SourceFile source(path);
    const auto bytes = source.device().read(MaximumReportBytes + 1);
    if (source.device().error() != QFileDevice::NoError || bytes.size() > MaximumReportBytes)
        throw Error(ExitCode::Config, QStringLiteral("诊断配置必须为不超过64KiB的普通INI文件"),
                    "doctor");
    source.verify();
    QTemporaryFile snapshot;
    if (!snapshot.open())
        throw Error(ExitCode::Disk, QStringLiteral("无法建立配置诊断快照"), "doctor");
    writeAll(snapshot, bytes);
    if (!snapshot.flush())
        throw Error(ExitCode::Disk, QStringLiteral("配置诊断快照写入失败"), "doctor");
    QSettings parsed(snapshot.fileName(), QSettings::IniFormat);
    return validateSettings(parsed);
}
} // namespace

// 日期：2026-11-07；每项独立失败仍继续后项；检查表和报告大小恒定，不返回原始异常/路径/配置正文。
QJsonObject collectDiagnostics(QSettings &settings, const DiagnosticOptions &options) {
    BufferCredit credit(512 * 1024);
    QJsonArray checks;
    int exitCode = 0;
    // 日期：2026-11-07；固定状态字段保持可脚本消费，第一项失败决定退出码。
    const auto append = [&](const QString &id, const QString &status, int code,
                            const QString &message) {
        checks.append(
            QJsonObject{{"id", id}, {"status", status}, {"code", code}, {"message", message}});
        if (!exitCode && code)
            exitCode = code;
    };
    const bool sqlite = QSqlDatabase::isDriverAvailable("QSQLITE");
    const bool tls = QSslSocket::supportsSsl();
    append("dependencies", sqlite && tls ? "passed" : "failed", sqlite && tls ? 0 : 2,
           sqlite && tls ? QStringLiteral("Qt、SQLite和TLS运行库可用")
                         : QStringLiteral("请安装匹配的SQLite/TLS运行依赖"));
    QString configuredOutput;
    try {
        configuredOutput = !options.configurationFile.isEmpty()
                               ? inspectIni(options.configurationFile, options.requireConfiguration)
                           : settings.format() == QSettings::IniFormat
                               ? inspectIni(settings.fileName(), options.requireConfiguration)
                               : validateSettings(settings);
        append("configuration", "passed", 0, QStringLiteral("已检查已知配置键；未导出配置值"));
    } catch (const Error &error) {
        append("configuration", "failed", static_cast<int>(error.code),
               QStringLiteral("请检查配置格式、长度、数值和访问权限"));
    }
    // 日期：2026-11-07；只对指定目录写入固定探针；未建立的默认目录明确待创建，显式不存在则失败。
    const auto directory = [&](const QString &id, const QString &path, bool required) {
        if (path.isEmpty() || (!QFileInfo::exists(path) && !isLinkedPath(path))) {
            append(id, required ? "failed" : "not-created", required ? 2 : 0,
                   QStringLiteral("目录尚未建立；诊断不会自动创建目录"));
            return;
        }
        try {
            DiagnosticTemporary probe(path);
            probe.write("Dukto Next diagnostic probe\n");
            probe.remove();
            append(id, "passed", 0, QStringLiteral("临时创建、写入、同步和清理通过"));
        } catch (const Error &) {
            append(id, "failed", 5, QStringLiteral("请检查目录权限、剩余空间及是否经过链接"));
        }
    };
    directory("state-directory", options.stateDirectory, options.requireStateDirectory);
    directory("output-directory", options.outputDirectory, options.requireOutputDirectory);
    if (!configuredOutput.isEmpty() && configuredOutput != options.outputDirectory)
        directory("configured-output-directory", configuredOutput, true);
    if (options.listenerActive) {
        append("tcp-listener", "active-in-this-instance", 0,
               QStringLiteral("当前实例已实际监听接收端口"));
    } else if (options.checkPort) {
        TcpListener probe;
        const bool listening = !options.bindAddress.isNull() && options.port &&
                               probe.listen(options.bindAddress, options.port);
        append("tcp-listener", listening ? "passed" : "failed", listening ? 0 : 3,
               listening ? QStringLiteral("指定TCP地址与端口绑定成功，探针已关闭")
                         : QStringLiteral("请检查监听地址及端口占用；不会修改防火墙"));
        probe.close();
    } else {
        append("tcp-listener", "not-requested", 0,
               QStringLiteral("可显式指定--bind和--port检查TCP绑定"));
    }
    return {{"eventVersion", 1},
            {"event", "doctor"},
            {"reportVersion", 1},
            {"timestampUtc", QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs)},
            {"applicationVersion", DUKTO_VERSION},
            {"qt", qVersion()},
            {"cxxStandard", "C++14"},
            {"platform", QSysInfo::productType()},
            {"architecture", QSysInfo::currentCpuArchitecture()},
            {"sqlite", sqlite},
            {"tls", tls},
            {"tlsBuild", QSslSocket::sslLibraryBuildVersionString()},
            {"tlsRuntime", QSslSocket::sslLibraryVersionString()},
            {"checks", checks},
            {"exitCode", exitCode},
            {"passed", exitCode == 0},
            {"peer", QJsonObject{{"status", "not-requested"}}},
            {"message", exitCode ? QStringLiteral("诊断发现问题，请查看checks及对应处理建议")
                                 : QStringLiteral("请求的诊断项目通过；未执行的项目已明确标记")}};
}

// 日期：2026-11-07；只导出程序生成的有界诊断JSON，不合并配置、日志、路径或用户文件。
void exportDiagnostics(const QJsonObject &report, const QString &destination) {
    if (destination.isEmpty() || destination.size() > 4096 || destination.contains(QChar::Null))
        throw Error(ExitCode::Config, QStringLiteral("诊断报告路径无效"), "doctor");
    const QFileInfo target(destination);
    validateRelativePath(target.fileName());
    BufferCredit credit(512 * 1024);
    const auto bytes = QJsonDocument(report).toJson(QJsonDocument::Indented);
    if (bytes.size() > MaximumReportBytes)
        throw Error(ExitCode::Config, QStringLiteral("诊断报告超过64KiB上限"), "doctor");
    DiagnosticTemporary file(target.absolutePath());
    file.write(bytes);
    file.commit(target.absoluteFilePath());
}
} // namespace dukto
