#include "app/boundedfiledialog.h"
#include "app/controller.h"
#include "core/buffercredit.h"
#include "core/files.h"
#include <QApplication>
#include <QDir>
#include <QItemSelectionModel>
#include <QSignalSpy>
#include <QStandardItemModel>
#include <QStandardPaths>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QtEndian>
#include <QtTest>

class ControllerTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-08；界面路径选择在文件数或累计路径字符超预算时撤销新增项。
    void transferSelectionHasFixedBudget() {
        QStandardItemModel countModel;
        countModel.setColumnCount(1);
        countModel.setRowCount(dukto::MaxTransferRoots + 1);
        QItemSelectionModel countSelection(&countModel);
        bool countAccepted = true;
        connect(&countSelection, &QItemSelectionModel::selectionChanged, this,
                [&](const QItemSelection &added, const QItemSelection &) {
                    if (!added.isEmpty())
                        countAccepted = constrainTransferSelection(&countSelection, added, ".");
                });
        const QItemSelection tooMany(countModel.index(0, 0),
                                     countModel.index(dukto::MaxTransferRoots, 0));
        countSelection.select(tooMany, QItemSelectionModel::Select | QItemSelectionModel::Rows);
        QVERIFY(!countAccepted);
        QVERIFY(countSelection.selectedRows(0).isEmpty());

        QStandardItemModel pathModel;
        pathModel.setColumnCount(1);
        pathModel.setRowCount(1);
        pathModel.setData(pathModel.index(0, 0),
                          QString(dukto::MaxTransferRootCharacters + 1, QChar('x')));
        QItemSelectionModel pathSelection(&pathModel);
        bool pathAccepted = true;
        connect(&pathSelection, &QItemSelectionModel::selectionChanged, this,
                [&](const QItemSelection &added, const QItemSelection &) {
                    if (!added.isEmpty())
                        pathAccepted = constrainTransferSelection(&pathSelection, added, ".");
                });
        const QItemSelection tooLong(pathModel.index(0, 0), pathModel.index(0, 0));
        pathSelection.select(tooLong, QItemSelectionModel::Select | QItemSelectionModel::Rows);
        QVERIFY(!pathAccepted);
        QVERIFY(pathSelection.selectedRows(0).isEmpty());
    }

    // 日期：2026-11-07；保持原8MiB UTF-8能力，分别覆盖字符数/字节数超限、最大中文和代理对边界。
    void outgoingTextBounds_data() {
        QTest::addColumn<QString>("text");
        QTest::addColumn<bool>("accepted");
        const int limit = static_cast<int>(dukto::MaxTextBytes);
        QTest::newRow("empty") << QString() << true;
        QTest::newRow("maximum-ascii") << QString(limit, 'x') << true;
        QTest::newRow("maximum-chinese") << (QString(limit / 3, QChar(0x6c49)) + "ab") << true;
        QTest::newRow("maximum-surrogate-pair")
            << (QString(limit - 4, 'x') + QString::fromUtf8("🚀")) << true;
        QString isolated;
        isolated += QChar(0xd800);
        isolated += 'x';
        isolated += QChar(0xdfff);
        QTest::newRow("isolated-surrogates") << isolated << true;
        QTest::newRow("ascii-one-byte-over") << QString(limit + 1, 'x') << false;
        QTest::newRow("chinese-one-byte-over") << QString(limit / 3 + 1, QChar(0x6c49)) << false;
        QTest::newRow("large-input-before-conversion")
            << QString(32 * 1024 * 1024, QChar(0x6c49)) << false;
    }

    // 日期：2026-11-07；独立TCP端逐字节核对真实R6帧，拒绝项不得连接；所有路径最终归还临时及任务授信。
    void outgoingTextBounds() {
        QFETCH(QString, text);
        QFETCH(bool, accepted);
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", temporary.path());
        settings.sync();
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        Controller controller(port, nullptr, temporary.filePath("state"));
        QTcpServer receiver;
        QVERIFY(receiver.listen(QHostAddress::LocalHost, 0));
        QSignalSpy connected(&receiver, &QTcpServer::newConnection);
        const auto before = dukto::BufferCredit::usage()["dataUsed"].toString().toLongLong();
        QCOMPARE(controller.sendText("127.0.0.1", receiver.serverPort(), text), accepted);
        if (!accepted) {
            QVERIFY(!controller.busy());
            QVERIFY(controller.status().contains(QStringLiteral("8 MiB")));
            QTest::qWait(20);
            QCOMPARE(connected.count(), 0);
        } else {
            QTRY_COMPARE_WITH_TIMEOUT(connected.count(), 1, 5000);
            auto socket = receiver.nextPendingConnection();
            QVERIFY(socket);
            QByteArray frame;
            // 日期：2026-11-07；Qt事件循环驱动独立接收，不阻塞GUI线程等待工作线程的网络写入。
            const auto drain = [&]() { frame += socket->readAll(); };
            connect(socket, &QTcpSocket::readyRead, &controller, drain);
            drain();
            const auto payload = text.toUtf8();
            QTRY_COMPARE_WITH_TIMEOUT(frame.size(), 43 + payload.size(), 10000);
            QCOMPARE(qFromLittleEndian<qint64>(reinterpret_cast<const uchar *>(frame.constData())),
                     qint64(1));
            QCOMPARE(
                qFromLittleEndian<qint64>(reinterpret_cast<const uchar *>(frame.constData() + 8)),
                qint64(payload.size()));
            QCOMPARE(frame.mid(16, 19), QByteArray("___DUKTO___TEXT___\0", 19));
            QCOMPARE(
                qFromLittleEndian<qint64>(reinterpret_cast<const uchar *>(frame.constData() + 35)),
                qint64(payload.size()));
            QCOMPARE(frame.mid(43), payload);
            QTRY_VERIFY_WITH_TIMEOUT(!controller.busy(), 5000);
            QVERIFY(controller.status().contains(QStringLiteral("发送")));
            disconnect(socket, nullptr, &controller, nullptr);
        }
        QTRY_COMPARE(dukto::BufferCredit::usage()["dataUsed"].toString().toLongLong(), before);
    }

#ifdef Q_OS_LINUX
    // 日期：2026-11-04；独立 XDG 下载目录首次自动创建；用户已保存但缺失的目录只提示、不重建。
    void preparesFreshDefaultDownloadDirectory() {
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        const auto previous = qgetenv("XDG_CONFIG_HOME");
        const bool hadPrevious = qEnvironmentVariableIsSet("XDG_CONFIG_HOME");
        struct EnvironmentGuard {
            QByteArray previous;
            bool existed;
            // 日期：2026-11-04；无论断言成功或提前返回，都恢复当前进程的 XDG 配置路径。
            ~EnvironmentGuard() {
                if (existed)
                    qputenv("XDG_CONFIG_HOME", previous);
                else
                    qunsetenv("XDG_CONFIG_HOME");
            }
        } guard{previous, hadPrevious};
        const auto configuration = temporary.filePath("xdg");
        const auto downloads = temporary.filePath("fresh-downloads");
        QVERIFY(QDir().mkpath(configuration));
        QFile userDirectories(configuration + "/user-dirs.dirs");
        QVERIFY(userDirectories.open(QIODevice::WriteOnly));
        userDirectories.write(("XDG_DOWNLOAD_DIR=\"" + downloads + "\"\n").toUtf8());
        userDirectories.close();
        qputenv("XDG_CONFIG_HOME", configuration.toUtf8());
        // 日期：2026-11-04；构造控制器前先核对 Qt 已采用隔离目录，禁止写入真实用户下载目录。
        QCOMPARE(QStandardPaths::writableLocation(QStandardPaths::DownloadLocation), downloads);
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        {
            Controller controller(port, nullptr, temporary.filePath("state"));
            QCOMPARE(controller.outputDirectory(), downloads);
            QVERIFY(QFileInfo(downloads).isDir());
            QVERIFY(controller.status().contains(QStringLiteral("就绪")));
        }
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        const auto unavailable = temporary.filePath("saved-but-missing");
        settings.setValue("output", unavailable);
        settings.sync();
        {
            Controller controller(port, nullptr, temporary.filePath("state"));
            QVERIFY(!QFileInfo::exists(unavailable));
            QVERIFY(controller.status().contains(QStringLiteral("接收目录不可用")));
        }
    }
#endif
    // 日期：2026-11-06；完整遍历最大换行/单行正文和代理对边界，不以第一页正常代替完整内容。
    void largeTextPagingKeepsAllContent_data() {
        QTest::addColumn<QByteArray>("payload");
        QTest::newRow("maximum-paragraphs") << QByteArray(8 * 1024 * 1024, '\n');
        QTest::newRow("maximum-single-line") << QByteArray(8 * 1024 * 1024, 'x');
        auto unicode = QString(16383, 'x') + QString::fromUtf8("🚀") + QString(16383, 'y') +
                       QString::fromUtf8("🚀中文\r\n");
        unicode += QChar(0);
        unicode += QChar(0x2029);
        QTest::newRow("unicode-boundaries") << unicode.toUtf8();
    }

    // 日期：2026-11-06；从独立R6帧接收后逐页拼回全部正文，关闭/重开同一历史仍得到一致内容。
    void largeTextPagingKeepsAllContent() {
        QFETCH(QByteArray, payload);
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", temporary.path());
        settings.sync();
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        Controller controller(port, nullptr, temporary.filePath("state"));
        QSignalSpy opened(&controller, &Controller::receivedTextOpened);
        QTcpSocket sender;
        sender.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(sender.waitForConnected(2000));
        QByteArray header(16, '\0');
        qToLittleEndian<qint64>(1, reinterpret_cast<uchar *>(header.data()));
        qToLittleEndian<qint64>(payload.size(), reinterpret_cast<uchar *>(header.data() + 8));
        header.append("___DUKTO___TEXT___\0", 19);
        QByteArray size(8, '\0');
        qToLittleEndian<qint64>(payload.size(), reinterpret_cast<uchar *>(size.data()));
        QCOMPARE(sender.write(header + size + payload),
                 qint64(header.size() + size.size() + payload.size()));
        sender.flush();
        QTRY_COMPARE_WITH_TIMEOUT(opened.count(), 1, 15000);
        const auto original = QString::fromUtf8(payload.constData(), payload.size());
        const auto id = controller.history()[0].toMap()["id"].toString();
        QVERIFY(!id.isEmpty());
        for (int attempt = 0; attempt < 2; ++attempt) {
            QString assembled;
            assembled.reserve(original.size());
            int pages = 0;
            for (;;) {
                const auto page = controller.receivedTextPage();
                QVERIFY(page.size() <= 16384);
                int breaks = 0;
                for (const auto ch : page)
                    if (ch == '\r' || ch == '\n' || ch.unicode() == 0x2028 ||
                        ch.unicode() == 0x2029)
                        ++breaks;
                QVERIFY(breaks <= 512);
                if (!page.isEmpty()) {
                    QVERIFY(!page.front().isLowSurrogate());
                    QVERIFY(!page.back().isHighSurrogate());
                }
                assembled += page;
                ++pages;
                if (!controller.receivedTextHasNext())
                    break;
                controller.changeReceivedTextPage(1);
            }
            QCOMPARE(pages, controller.receivedTextPageCount());
            QCOMPARE(assembled, original);
            QCOMPARE(assembled.toUtf8(), payload);
            const auto position = controller.receivedTextPosition();
            controller.changeReceivedTextPage(2147483647);
            QCOMPARE(controller.receivedTextPosition(), position);
            controller.changeReceivedTextPage(-2147483647);
            QCOMPARE(controller.receivedTextPosition(), position);
            controller.releaseReceivedText();
            QCOMPARE(controller.receivedTextPageCount(), 0);
            QCOMPARE(controller.receivedTextPage(), QString());
            QTRY_COMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(), QString("0"));
            if (attempt == 0) {
                controller.openHistory(id);
                QCOMPARE(opened.count(), 2);
            }
        }
    }

    // 日期：2026-11-04；所有设置和历史使用独立临时目录，不能改变真实用户配置。
    void textHistorySurvivesRestart() {
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        const auto data = temporary.filePath("data");
        const auto output = temporary.filePath("received");
        QVERIFY(QDir().mkpath(output));
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", output);
        settings.sync();
        QVERIFY(settings.fileName().startsWith(temporary.path()));
        QTcpServer reserve;
        QVERIFY(reserve.listen(QHostAddress::LocalHost, 0));
        const auto port = reserve.serverPort();
        reserve.close();
        QString id;
        const auto content = QStringLiteral("持久文本\nUnicode café 🚀");
        {
            Controller controller(port, nullptr, data);
            QCOMPARE(controller.outputDirectory(), output);
            QCOMPARE(controller.themeColor(), QString("#268600"));
            QVERIFY(controller.addresses().contains("127.0.0.1"));
            QSignalSpy text(&controller, &Controller::textReceived);
            QTcpSocket sender;
            sender.connectToHost(QHostAddress::LocalHost, port);
            QVERIFY(sender.waitForConnected(2000));
            // 日期：2026-11-04；从独立包头输入文本，验证真实收发事件到历史查询链路。
            const auto number = [](qint64 value) {
                QByteArray bytes(8, '\0');
                qToLittleEndian(value, reinterpret_cast<uchar *>(bytes.data()));
                return bytes;
            };
            const auto bytes = content.toUtf8();
            sender.write(number(1) + number(bytes.size()) + "___DUKTO___TEXT___" + '\0' +
                         number(bytes.size()) + bytes);
            sender.flush();
            QTRY_COMPARE(text.count(), 1);
            QCOMPARE(text[0][0].toString(), content);
            QCOMPARE(controller.history().size(), 1);
            const auto item = controller.history()[0].toMap();
            QVERIFY(item["hasText"].toBool());
            QCOMPARE(item["peer"].toString(), QString("127.0.0.1"));
            id = item["id"].toString();
            controller.openHistory(id);
            QCOMPARE(text.count(), 2);
            QCOMPARE(text[1][0].toString(), content);
            QTRY_VERIFY(!controller.busy());
            const auto displayed = dukto::BufferCredit::usage()["dataUsed"].toString().toLongLong();
            QVERIFY(displayed >= content.toUtf8().size() * 10 + 64 * 1024);
            {
                dukto::BufferCredit saturated(120 * 1024 * 1024 - displayed, true);
                controller.sendText("127.0.0.1", port, "must-refuse-before-start");
                QVERIFY(!controller.busy());
                QVERIFY(controller.status().contains(QStringLiteral("授信")));
            }
            controller.releaseReceivedText();
            controller.releaseReceivedText();
            QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(), QString("0"));
            controller.setThemeColor("#0078d4");
            QTRY_VERIFY(!controller.busy());
        }
        {
            Controller controller(port, nullptr, data);
            QCOMPARE(controller.themeColor(), QString("#0078d4"));
            QCOMPARE(controller.history().size(), 1);
            QCOMPARE(controller.history()[0].toMap()["peer"].toString(), QString("127.0.0.1"));
            QSignalSpy text(&controller, &Controller::textReceived);
            controller.openHistory(id);
            QCOMPARE(text.count(), 1);
            QCOMPARE(text[0][0].toString(), content);
            controller.sendText("127.0.0.1", 65536, "must reject");
            QVERIFY(!controller.busy());
            QVERIFY(controller.status().contains(QStringLiteral("端口")));
            controller.openHistory("999999999");
            QVERIFY(controller.status().contains(QStringLiteral("不存在")));
            QSignalSpy batches(&controller, &Controller::batchOpened);
            QTcpSocket sender;
            sender.connectToHost(QHostAddress::LocalHostIPv6, port);
            QVERIFY(sender.waitForConnected(2000));
            // 日期：2026-11-04；实际接收两个空文件，批次历史必须打开完整两项明细。
            const auto number = [](qint64 value) {
                QByteArray bytes(8, '\0');
                qToLittleEndian(value, reinterpret_cast<uchar *>(bytes.data()));
                return bytes;
            };
            sender.write(number(2) + number(0) + "first" + '\0' + number(0) + "second" + '\0' +
                         number(0));
            sender.flush();
            QTRY_COMPARE(controller.history().size(), 2);
            QCOMPARE(controller.history()[0].toMap()["peer"].toString(), QString("::1"));
            controller.openHistory(controller.history()[0].toMap()["id"].toString());
            QCOMPARE(batches.count(), 1);
            QCOMPARE(controller.batchFiles().size(), 2);
            QCOMPARE(controller.batchFiles()[0].toMap()["source"].toString(), QString("first"));
            QCOMPARE(controller.batchFiles()[1].toMap()["source"].toString(), QString("second"));
            QVERIFY(!controller.batchHasNext());
            QVERIFY(QFileInfo::exists(controller.batchFiles()[0].toMap()["path"].toString()));
        }
    }
};

QTEST_MAIN(ControllerTests)
#include "controller_tests.moc"
