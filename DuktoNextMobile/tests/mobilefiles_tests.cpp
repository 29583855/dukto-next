#include "mobilefiles.h"
#include <QDir>
#include <QFile>
#include <QSet>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTimer>
#include <QtTest>

class MobileFilesTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-25；测试文件全部置于独立测试应用目录，禁止接触用户Documents。
    void initTestCase() {
        QCoreApplication::setOrganizationName("DuktoNextTests");
        QCoreApplication::setApplicationName("MobileFilesPagination");
        QStandardPaths::setTestModeEnabled(true);
    }
    // 日期：2026-11-25；跨三页读取1200项，验证没有丢失、重复或越界路径。
    void paginatesAllFiles() {
        MobileFiles files;
        QTemporaryDir directory(QDir(files.documents()).filePath("page-XXXXXX"));
        QVERIFY(directory.isValid());
        for (int index = 1199; index >= 0; --index) {
            QFile file(QDir(directory.path())
                           .filePath(QString("中文-%1.bin").arg(index, 4, 10, QChar('0'))));
            QVERIFY(file.open(QIODevice::WriteOnly));
        }
        QString after;
        QSet<QString> seen;
        int pages = 0;
        do {
            const auto page = files.entries(directory.path(), after);
            const auto rows = page.value("rows").toList();
            QVERIFY(rows.size() <= 512);
            QVERIFY(!rows.isEmpty());
            for (const auto &row : rows) {
                const auto entry = row.toMap();
                const auto name = entry.value("name").toString();
                QVERIFY(!seen.contains(name));
                QVERIFY(name > after);
                QVERIFY(entry.value("path").toString().startsWith(directory.path() + '/'));
                seen.insert(name);
            }
            after = page.value("next").toString();
            ++pages;
            QVERIFY(pages <= 3);
        } while (!after.isEmpty());
        QCOMPARE(pages, 3);
        QCOMPARE(seen.size(), 1200);
    }
    // 日期：2026-11-25；沙箱外路径不能浏览、创建子目录或导出认证文件。
    void rejectsOutsideAndEscapes() {
        MobileFiles files;
        QTemporaryDir outside;
        QVERIFY(files.entries(outside.path()).value("rows").toList().isEmpty());
        QVERIFY(!files.createDirectory(outside.path(), "denied"));
        QVERIFY(!files.createDirectory(files.documents(), "../escape"));
        files.exportPath(outside.path());
        QVERIFY(!files.busy());
        QVERIFY(files.message().contains(QStringLiteral("仅支持导出")));
#ifndef Q_OS_WIN
        QTemporaryDir directory(QDir(files.documents()).filePath("links-XXXXXX"));
        QVERIFY(QFile::link(outside.path(), QDir(directory.path()).filePath("escape")));
        QVERIFY(files.entries(directory.path()).value("rows").toList().isEmpty());
        QVERIFY(!files.createDirectory(QDir(directory.path()).filePath("escape"), "denied"));
#endif
    }
    // 日期：2026-11-25；异步沙箱选择器返回已验证目录，原生替身失败不会留下忙状态。
    void chooserUnwinds() {
        MobileFiles files;
        connect(&files, &MobileFiles::directoryRequested, &files,
                [&files](const QString &) { files.finishDirectory(files.documents()); });
        QCOMPARE(files.chooseDirectory("test"), files.documents());
        QVERIFY(!files.busy());
        QVERIFY(files.importFiles().isEmpty());
        QVERIFY(!files.busy());
        QVERIFY(files.message().contains(QStringLiteral("主机测试")));
    }
};
QTEST_GUILESS_MAIN(MobileFilesTests)
#include "mobilefiles_tests.moc"
