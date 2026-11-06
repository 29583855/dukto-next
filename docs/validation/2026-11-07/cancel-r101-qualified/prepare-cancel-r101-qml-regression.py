"""日期：2026-11-07；新增真实QML取消及同实例双向后续传输回归，保留原源码格式。"""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-07；先保存原字节，再只在唯一锚点新增测试和按钮定位名，不改变取消实现。
def main():
    root = Path.cwd()
    backup = root / '.cache/cancel-r101-before'
    backup.mkdir(exist_ok=False)
    names = ('ui/Main.qml', 'tests/ui_tests.cpp')
    records = []
    for name in names:
        raw = (root / name).read_bytes()
        raw.decode('utf-8-sig')
        target = backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        records.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                        'utf8Bom': raw.startswith(b'\xef\xbb\xbf'), 'crlf': b'\r\n' in raw})
    (backup / 'source-before.json').write_text(json.dumps(records, indent=2) + '\n', 'utf-8')
    update = runpy.run_path('.cache/finalize-skip-items-r84.py')['update']

    # 日期：2026-11-07；只添加可测试定位名，按钮文本、可见状态和实际取消槽保持原行为。
    def qml(text):
        old = '                    Button {\n                        text: "取消"\n                        flat: true\n'
        assert text.count(old) == 1
        return text.replace(old, '                    Button {\n                        objectName: "legacyCancelButton"\n                        text: "取消"\n                        flat: true\n', 1)

    test = r'''    // 日期：2026-11-07；原版中止后下一批崩溃的对照场景，分别覆盖新版实际发送和接收取消。
    void cancelThenTransferAgainThroughQml_data() {
        QTest::addColumn<bool>("outgoing");
        QTest::newRow("send") << true;
        QTest::newRow("receive") << false;
    }

    // 日期：2026-11-07；实际点击生产取消按钮，部分数据后结束且释放临时额度，同一控制器随后双向成功。
    void cancelThenTransferAgainThroughQml() {
        QFETCH(bool, outgoing);
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output));
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", output);
        settings.setValue("terms", true);
        settings.sync();
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        Controller controller(port, nullptr, temporary.filePath("state"));
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        view.setSource(QUrl("qrc:/ui/Main.qml"));
        QCOMPARE(view.status(), QQuickWidget::Ready);
        view.show();
        view.activateWindow();
        view.setFocus();
        auto root = view.rootObject();
        QVERIFY(root);
        auto cancel = root->findChild<QQuickItem *>("legacyCancelButton");
        QVERIFY(cancel);
        QTRY_VERIFY(!cancel->isVisible());
        const auto before = dukto::BufferCredit::usage()["dataUsed"].toString();
        QTcpServer slow;
        QVERIFY(slow.listen(QHostAddress::LocalHost, 0));
        QTcpSocket incoming;
        std::unique_ptr<QTcpSocket> peer;
        const qint64 declared = 32 * 1024 * 1024;
        // 日期：2026-11-07；独立构造小端R6头，不借用被测收发编码器。
        const auto number = [](qint64 value) {
            QByteArray bytes(8, '\0');
            qToLittleEndian(value, reinterpret_cast<uchar *>(bytes.data()));
            return bytes;
        };
        qint64 observed = 0;
        if (outgoing) {
            QFile source(temporary.filePath("cancel.bin"));
            QVERIFY(source.open(QIODevice::WriteOnly));
            const QByteArray block(64 * 1024, 'x');
            for (int index = 0; index < declared / block.size(); ++index)
                QCOMPARE(source.write(block), qint64(block.size()));
            source.close();
            QVERIFY(controller.sendDropped("127.0.0.1", slow.serverPort(),
                                           {QUrl::fromLocalFile(source.fileName())}));
            QTRY_VERIFY(slow.hasPendingConnections());
            peer.reset(slow.nextPendingConnection());
            QVERIFY(peer);
            peer->setReadBufferSize(4096);
            QTRY_VERIFY(peer->bytesAvailable() >= 16);
            const auto header = peer->read(16);
            QCOMPARE(qFromLittleEndian<qint64>(reinterpret_cast<const uchar *>(header.constData())), qint64(1));
            QCOMPARE(qFromLittleEndian<qint64>(reinterpret_cast<const uchar *>(header.constData() + 8)), declared);
            QTRY_VERIFY(peer->bytesAvailable() > 32);
            observed = 16 + peer->bytesAvailable();
        } else {
            incoming.connectToHost(QHostAddress::LocalHost, port);
            QVERIFY(incoming.waitForConnected(2000));
            const auto frame = number(1) + number(declared) + QByteArray("cancel.bin\0", 11) +
                               number(declared) + QByteArray(64 * 1024, 'x');
            QCOMPARE(incoming.write(frame), qint64(frame.size()));
            incoming.flush();
            QTRY_VERIFY(!QDir(output).entryList({"*.part"}, QDir::Files | QDir::Hidden).isEmpty());
            QTRY_VERIFY(controller.progress() > 0);
        }
        QTRY_VERIFY(controller.busy() && cancel->isVisible());
        click(view, cancel);
        QTRY_VERIFY2_WITH_TIMEOUT(!controller.busy(), qPrintable(controller.status()), 5000);
        QVERIFY(controller.status().contains(QStringLiteral("取消")));
        QTRY_VERIFY(!cancel->isVisible());
        if (outgoing) {
            // 日期：2026-11-07；取消后有界排空独立对端，确认EOF与部分正文；不等待原文件完整发送。
            QObject::connect(peer.get(), &QTcpSocket::readyRead, peer.get(), [&]() {
                observed += peer->readAll().size();
            });
            observed += peer->readAll().size();
            QTRY_COMPARE_WITH_TIMEOUT(peer->state(), QAbstractSocket::UnconnectedState, 5000);
            observed += peer->readAll().size();
            QVERIFY(observed > 32 && observed < declared);
        } else {
            QTRY_VERIFY(QDir(output).entryList({"*.part"}, QDir::Files | QDir::Hidden).isEmpty());
            QVERIFY(!QFileInfo::exists(QDir(output).filePath("cancel.bin")));
            incoming.abort();
        }
        QTRY_COMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(), before);
        const auto nextOutput = temporary.filePath("next-output");
        QVERIFY(QDir().mkpath(nextOutput));
        dukto::LegacyListener receiver(nextOutput, 3000);
        QVERIFY(receiver.listen(QHostAddress::LocalHost, 0));
        QSignalSpy result(&receiver, &dukto::LegacyListener::result);
        QFile nextSource(temporary.filePath("next.bin"));
        const QByteArray payload = QStringLiteral("中止后同实例继续\ncafé 🚀\n").toUtf8();
        QVERIFY(nextSource.open(QIODevice::WriteOnly));
        QCOMPARE(nextSource.write(payload), qint64(payload.size()));
        nextSource.close();
        QVERIFY(controller.sendDropped("127.0.0.1", receiver.serverPort(),
                                       {QUrl::fromLocalFile(nextSource.fileName())}));
        QTRY_COMPARE_WITH_TIMEOUT(result.count(), 1, 5000);
        QCOMPARE(result[0][0].toInt(), 0);
        QTRY_VERIFY(!controller.busy());
        QCOMPARE(dukto::hashFile(nextSource.fileName()),
                 dukto::hashFile(QDir(nextOutput).filePath("next.bin")));
        QTcpSocket next;
        next.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(next.waitForConnected(2000));
        const auto frame = number(1) + number(payload.size()) + QByteArray("after.bin\0", 10) +
                           number(payload.size()) + payload;
        QCOMPARE(next.write(frame), qint64(frame.size()));
        next.flush();
        QFile received(QDir(output).filePath("after.bin"));
        QTRY_VERIFY2_WITH_TIMEOUT(received.exists(), qPrintable(controller.status()), 5000);
        QTRY_VERIFY(!controller.busy());
        QVERIFY(received.open(QIODevice::ReadOnly));
        QCOMPARE(received.readAll(), payload);
        QTRY_COMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(), before);
    }

'''

    # 日期：2026-11-07；测试独立插入，不修改已有Qt断言或既有测试方法。
    def cpp(text):
        anchor = '  private slots:\n\n'
        assert text.count(anchor) == 1
        return text.replace(anchor, anchor + test, 1)

    update(root / 'ui/Main.qml', qml)
    update(root / 'tests/ui_tests.cpp', cpp)
    subprocess.run([str(root / '.tools/python/Scripts/clang-format.exe'), '-i',
                    str(root / 'tests/ui_tests.cpp')], check=True)
    for row in records:
        raw = (root / row['path']).read_bytes()
        raw.decode('utf-8-sig')
        assert raw.startswith(b'\xef\xbb\xbf') == row['utf8Bom'] and (b'\r\n' in raw) == row['crlf']
        if row['crlf']:
            assert b'\n' not in raw.replace(b'\r\n', b'')
    print(json.dumps({'regressionRows': 2, 'productionChange': 'existing cancel button objectName only',
                      'existingEncodingAndNewlinesPreserved': True}))


if __name__ == '__main__':
    main()
