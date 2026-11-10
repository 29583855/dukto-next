#include "app/boundedfiledialog.h"
#include "app/controller.h"
#include "core/buffercredit.h"
#include "core/catalog.h"
#include "core/error.h"
#include "core/files.h"
#include "core/sqliteruntime.h"
#include <QApplication>
#include <QDir>
#include <QItemSelectionModel>
#include <QNetworkDatagram>
#include <QNetworkInterface>
#include <QSignalSpy>
#include <QSqlQuery>
#include <QStandardItemModel>
#include <QStandardPaths>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QtEndian>
#include <QtTest>
#include <memory>

class ControllerTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-10；原版占据4644和相邻备用端口时仍可公告真实端口并接收文本，不抢原连接。
    void defaultPortConflictKeepsDiscoveryAndReceivesText() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, root.path());
        dukto::TcpListener original;
        dukto::TcpListener occupiedBackup;
        QVERIFY2(original.listen(QHostAddress::Any, 4644), qPrintable(original.errorString()));
        QVERIFY(occupiedBackup.listen(QHostAddress::Any, 4648));
        QUdpSocket legacy;
        // 日期：2026-11-10；原版initialize使用Any和平台默认绑定，不能用Next共享选项替代原版行为。
        QVERIFY(legacy.bind(QHostAddress(QHostAddress::Any), 4644));
        Controller controller(4644, nullptr, root.filePath("next"));
        auto receiver = controller.findChild<dukto::LegacyListener *>();
        QVERIFY2(receiver && receiver->isListening(), qPrintable(controller.status()));
        QCOMPARE(receiver->serverPort(), quint16(4650));
        QVERIFY(controller.status().contains("4650"));
        QVERIFY(controller.status().contains(QStringLiteral("自动发现已启用")));
        quint16 advertised = 0;
        const auto readAnnouncement = [&]() {
            // 日期：2026-11-10；从真实标准广播中读取端口，不能使用控制器内部预期值代替线路数据。
            while (legacy.hasPendingDatagrams()) {
                const auto data = legacy.receiveDatagram(1024).data();
                if (data.size() > 3 && data[0] == '\x04') {
                    const auto port = qFromLittleEndian<quint16>(
                        reinterpret_cast<const uchar *>(data.constData() + 1));
                    if (port == receiver->serverPort())
                        advertised = port;
                }
            }
            return advertised;
        };
        QTRY_COMPARE_WITH_TIMEOUT(readAnnouncement(), quint16(4650), 5000);
        const auto payload = QStringLiteral("从发现端口收到的中文文本 café").toUtf8();
        QTcpSocket sender;
        sender.connectToHost(QHostAddress::LocalHost, advertised);
        QVERIFY(sender.waitForConnected(3000));
        QByteArray frame(16, '\0');
        qToLittleEndian<qint64>(1, reinterpret_cast<uchar *>(frame.data()));
        qToLittleEndian<qint64>(payload.size(), reinterpret_cast<uchar *>(frame.data() + 8));
        frame.append("___DUKTO___TEXT___\0", 19);
        QByteArray length(8, '\0');
        qToLittleEndian<qint64>(payload.size(), reinterpret_cast<uchar *>(length.data()));
        frame += length + payload;
        QCOMPARE(sender.write(frame), qint64(frame.size()));
        sender.flush();
        QTRY_COMPARE_WITH_TIMEOUT(controller.receivedTextPage(), QString::fromUtf8(payload), 10000);
        QVERIFY(original.isListening());
        QVERIFY(!original.hasPendingConnections());
        QVERIFY(occupiedBackup.isListening());
    }

    // 日期：2026-11-10；两个自定义端口实例必须接收标准4644广播、相互发现并保留原版设备的真实端口。
    void customPortsHearStandardBroadcastAndEachOther() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, root.path());
        // 日期：2026-11-10；GUI拒绝端口0，此处使用两个真实固定自定义端口，避免Darwin临时端口复用。
        Controller first(47620, nullptr, root.filePath("first"), false);
        Controller second(47624, nullptr, root.filePath("second"), false);
        const auto firstListener = first.findChild<dukto::LegacyListener *>();
        const auto secondListener = second.findChild<dukto::LegacyListener *>();
        QVERIFY2(firstListener->isListening(), qPrintable(first.status()));
        QVERIFY2(secondListener->isListening(), qPrintable(second.status()));
        const auto firstPort = firstListener->serverPort();
        const auto secondPort = secondListener->serverPort();
        QCOMPARE(firstPort, quint16(47620));
        QCOMPARE(secondPort, quint16(47624));
        const auto contains = [](const Controller &controller, quint16 port, const QString &name) {
            // 日期：2026-11-10；只匹配本轮端口和唯一远端身份，不依赖真实局域网设备数量。
            for (const auto &value : controller.peers()) {
                const auto peer = value.toMap();
                if (peer["port"].toInt() == port &&
                    (name.isEmpty() || peer["name"].toString() == name))
                    return true;
            }
            return false;
        };
        first.refresh();
        second.refresh();
        QTRY_VERIFY_WITH_TIMEOUT(contains(first, secondPort, {}), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(contains(second, firstPort, {}), 5000);
        QUdpSocket legacy;
        QVERIFY(legacy.bind(QHostAddress::AnyIPv4, 4644,
                            QUdpSocket::ShareAddress | QUdpSocket::ReuseAddressHint));
        const auto name = "coexist-legacy-" + QUuid::createUuid().toString(QUuid::WithoutBraces);
        const auto hello = QByteArray(1, '\x01') + name.toUtf8() + " at old-device (Macintosh)";
        int broadcasts = 0;
        for (const auto &interface : QNetworkInterface::allInterfaces()) {
            if (!(interface.flags() & QNetworkInterface::IsUp) ||
                !(interface.flags() & QNetworkInterface::CanBroadcast))
                continue;
            for (const auto &address : interface.addressEntries())
                if (address.ip().protocol() == QAbstractSocket::IPv4Protocol &&
                    !address.broadcast().isNull() &&
                    legacy.writeDatagram(hello, address.broadcast(), 4644) == hello.size())
                    ++broadcasts;
        }
        QVERIFY2(broadcasts > 0, "No active IPv4 broadcast interface available for native test");
        QTRY_VERIFY_WITH_TIMEOUT(contains(first, 4644, name), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(contains(second, 4644, name), 5000);
        QCOMPARE(first.findChild<dukto::LegacyListener *>()->serverPort(), firstPort);
        QCOMPARE(second.findChild<dukto::LegacyListener *>()->serverPort(), secondPort);
    }

    // 日期：2026-11-10；两端Next均退让到不同备用端口时，即使标准UDP由原版独占也须直接相互发现。
    void twoDefaultInstancesDiscoverWithOriginalUDP() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, root.path());
        dukto::TcpListener original;
        QVERIFY(original.listen(QHostAddress::Any, 4644));
        QUdpSocket legacy;
        QVERIFY(legacy.bind(QHostAddress(QHostAddress::Any), 4644));
        Controller first(4644, nullptr, root.filePath("first"));
        Controller second(4644, nullptr, root.filePath("second"));
        const auto firstListener = first.findChild<dukto::LegacyListener *>();
        const auto secondListener = second.findChild<dukto::LegacyListener *>();
        QVERIFY2(firstListener->isListening(), qPrintable(first.status()));
        QVERIFY2(secondListener->isListening(), qPrintable(second.status()));
        const auto contains = [](const Controller &controller, quint16 port) {
            // 日期：2026-11-10；按真实监听端口匹配，不能把原版4644身份当成另一Next通过。
            for (const auto &value : controller.peers())
                if (value.toMap()["port"].toInt() == port)
                    return true;
            return false;
        };
        QVERIFY(firstListener->serverPort() != secondListener->serverPort());
        QTRY_VERIFY_WITH_TIMEOUT(contains(first, secondListener->serverPort()), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(contains(second, firstListener->serverPort()), 5000);
        QVERIFY(original.isListening());
    }

    // 日期：2026-11-10；显式--port冲突不悄悄更换端口，也不能公告无法接收的端点。
    void explicitPortConflictDoesNotAdvertise() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        dukto::TcpListener original;
        QVERIFY(original.listen(QHostAddress::Any, 4644));
        Controller controller(4644, nullptr, root.path(), false);
        QVERIFY(!controller.findChild<dukto::LegacyListener *>()->isListening());
        QVERIFY(controller.status().contains(QStringLiteral("接收端口不可用")));
        QVERIFY(controller.peers().isEmpty());
        QVERIFY(original.isListening());
    }

    // 日期：2026-11-09；真实生产控制器读取迁移前文本与旧接收明细路径，跨两次重启保持内容和原库摘要。
    void protectedHistoryRetainsTextAndLegacyReceiptLinks() {
        QTemporaryDir root;
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, root.path());
        QString task;
        {
            dukto::Catalog old(root.filePath("fixture.sqlite"));
            task = old.begin(2, 2, "127.0.0.1");
            old.append(task, 1, "first.txt", root.filePath("first.txt"), 1, QByteArray(32, 'a'));
            old.append(task, 2, "second.txt", root.filePath("second.txt"), 1, QByteArray(32, 'b'));
            old.finish(task, "completed", 2);
        }
        QVERIFY(QFile::rename(root.filePath("fixture.sqlite"), root.filePath("receipts.sqlite")));
        const auto text = QString::fromUtf8("迁移前的文本 café 😀\n第二行");
        const auto connection = QUuid::createUuid().toString();
        {
            auto database = dukto::addSqliteDatabase(connection);
            database.setDatabaseName(root.filePath("history.sqlite"));
            QVERIFY(database.open());
            {
                QSqlQuery query(database);
                QVERIFY(query.exec(
                    "CREATE TABLE history(time TEXT,path TEXT,bytes TEXT,message TEXT)"));
                QVERIFY(query.exec(
                    "CREATE TABLE text_history(record INTEGER PRIMARY KEY,content TEXT)"));
                QVERIFY(query.exec("CREATE TABLE history_receipts(record INTEGER PRIMARY "
                                   "KEY,catalog TEXT,task TEXT,entries INTEGER)"));
                QVERIFY(query.exec("INSERT INTO history VALUES('2026-11-01','','0','old text')"));
                QVERIFY(query.exec("INSERT INTO history VALUES('2026-11-02','','2','old batch')"));
                query.prepare("INSERT INTO text_history VALUES(1,?)");
                query.addBindValue(text);
                QVERIFY(query.exec());
                query.prepare("INSERT INTO history_receipts VALUES(2,?,?,2)");
                query.addBindValue(root.filePath("receipts.sqlite"));
                query.addBindValue(task);
                QVERIFY(query.exec());
            }
            database.close();
        }
        QSqlDatabase::removeDatabase(connection);
        const auto historyHash = dukto::hashFile(root.filePath("history.sqlite"));
        const auto receiptsHash = dukto::hashFile(root.filePath("receipts.sqlite"));
        for (int iteration = 0; iteration < 2; ++iteration) {
            Controller controller(0, nullptr, root.path());
            QCOMPARE(controller.history().size(), 2);
            controller.openHistory("1");
            QCOMPARE(controller.receivedTextPage(), text);
            controller.openHistory("2");
            QCOMPARE(controller.batchFiles().size(), 2);
            QCOMPARE(controller.batchFiles()[0].toMap()["source"].toString(), QString("first.txt"));
            QVERIFY(QFileInfo::exists(root.filePath("history/history.sqlite")));
            QVERIFY(QFileInfo::exists(root.filePath("history/receipts.sqlite")));
        }
        QCOMPARE(dukto::hashFile(root.filePath("history.sqlite")), historyHash);
        QCOMPARE(dukto::hashFile(root.filePath("receipts.sqlite")), receiptsHash);
    }

    // 日期：2026-11-09；真实历史连接共享页缓存额度，双实例使用不同Qt注册项，销毁其一不关闭另一项。
    void historyCacheReservationsAndIndependentConnections() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, root.path());
        const auto before = dukto::BufferCredit::usage();
        const auto baseline = QSqlDatabase::connectionNames();
        {
            Controller first(0, nullptr, root.filePath("first"));
            auto firstNames = QSqlDatabase::connectionNames();
            for (const auto &name : baseline)
                firstNames.removeAll(name);
            QCOMPARE(firstNames.size(), 1);
            const auto firstName = firstNames[0];
            QVERIFY(firstName.startsWith("gui-history-"));
            QCOMPARE(dukto::BufferCredit::usage()["controlUsed"].toString().toLongLong(),
                     before["controlUsed"].toString().toLongLong() + 2112 * 1024);
            {
                Controller second(0, nullptr, root.filePath("second"));
                auto names = QSqlDatabase::connectionNames();
                for (const auto &name : baseline)
                    names.removeAll(name);
                QCOMPARE(names.size(), 2);
                QCOMPARE(dukto::BufferCredit::usage()["controlUsed"].toString().toLongLong(),
                         before["controlUsed"].toString().toLongLong() + 4224 * 1024);
                QCOMPARE(dukto::BufferCredit::usage()["dataUsed"], before["dataUsed"]);
                for (const auto &name : names) {
                    QSqlQuery query(QSqlDatabase::database(name));
                    for (const auto &setting :
                         {qMakePair(QString("main.cache_size"), qint64(-2048)),
                          qMakePair(QString("temp.cache_size"), qint64(-64)),
                          qMakePair(QString("temp_store"), qint64(1)),
                          qMakePair(QString("mmap_size"), qint64(0))}) {
                        QVERIFY(query.exec("PRAGMA " + setting.first));
                        QVERIFY(query.next());
                        QCOMPARE(query.value(0).toLongLong(), setting.second);
                        QVERIFY(!query.next());
                    }
                }
            }
            QVERIFY(QSqlDatabase::contains(firstName));
            QSqlQuery query(QSqlDatabase::database(firstName));
            QVERIFY(query.exec("SELECT COUNT(*) FROM history"));
            QVERIFY(query.next());
            QCOMPARE(query.value(0).toInt(), 0);
        }
        QCOMPARE(QSqlDatabase::connectionNames(), baseline);
        // 日期：2026-11-09；只核对当前占用归还，历史峰值按定义不会在连接关闭后回退。
        for (const auto &key : {"used", "dataUsed", "controlUsed"})
            QCOMPARE(dukto::BufferCredit::usage()[key], before[key]);
    }

    // 日期：2026-11-09；坏历史文件导致初始化失败时，Qt连接/缓存额度均归还，坏库原字节保持。
    void historyCacheFailureAndBudgetRefusalRecover() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, root.path());
        QVERIFY(QDir().mkpath(root.filePath("broken")));
        QFile file(root.filePath("broken/history.sqlite"));
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write(QByteArray(4096, 'x')), qint64(4096));
        file.close();
        const auto hash = dukto::hashFile(file.fileName());
        const auto baseline = QSqlDatabase::connectionNames();
        const auto before = dukto::BufferCredit::usage();
        QVERIFY_EXCEPTION_THROWN(Controller(0, nullptr, root.filePath("broken")), dukto::Error);
        QCOMPARE(dukto::hashFile(file.fileName()), hash);
        QCOMPARE(QSqlDatabase::connectionNames(), baseline);
        // 日期：2026-11-09；只核对当前占用归还，历史峰值按定义不会在连接关闭后回退。
        for (const auto &key : {"used", "dataUsed", "controlUsed"})
            QCOMPARE(dukto::BufferCredit::usage()[key], before[key]);
        {
            dukto::BufferCredit full(128 * 1024 * 1024 - before["used"].toString().toLongLong());
            QVERIFY_EXCEPTION_THROWN(Controller(0, nullptr, root.filePath("retry")), dukto::Error);
            QVERIFY(!QFileInfo::exists(root.filePath("retry/history/history.sqlite")));
            QCOMPARE(QSqlDatabase::connectionNames(), baseline);
        }
        {
            Controller retry(0, nullptr, root.filePath("retry"));
            QVERIFY(QFileInfo::exists(root.filePath("retry/history/history.sqlite")));
            QCOMPARE(dukto::BufferCredit::usage()["controlUsed"].toString().toLongLong(),
                     before["controlUsed"].toString().toLongLong() + 2112 * 1024);
        }
        QCOMPARE(QSqlDatabase::connectionNames(), baseline);
        // 日期：2026-11-09；只核对当前占用归还，历史峰值按定义不会在连接关闭后回退。
        for (const auto &key : {"used", "dataUsed", "controlUsed"})
            QCOMPARE(dukto::BufferCredit::usage()[key], before[key]);
    }

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
