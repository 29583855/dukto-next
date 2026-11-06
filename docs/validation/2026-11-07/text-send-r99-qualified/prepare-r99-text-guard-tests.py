"""日期：2026-11-07；先建立拒绝发送后草稿丢失的生产QML回归，保持全部原文件编码与换行。"""
from pathlib import Path
import hashlib
import json


# 日期：2026-11-07；保存修改前字节，精确替换唯一锚点，拒绝重复执行或隐式转码。
def main():
    root = Path.cwd()
    backup = root / '.cache/text-send-r99-originals'
    backup.mkdir(exist_ok=False)
    names = ['src/app/controller.cpp', 'src/app/controller.h', 'ui/Main.qml',
             'tests/controller_tests.cpp', 'tests/ui_tests.cpp']
    records = []
    for name in names:
        raw = (root / name).read_bytes()
        raw.decode('utf-8')
        target = backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        records.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                        'bom': raw.startswith(b'\xef\xbb\xbf'), 'crlf': raw.count(b'\r\n'),
                        'lf': raw.count(b'\n')})
    (backup / 'manifest.json').write_text(json.dumps(records, indent=2) + '\n', 'utf-8')
    path = root / 'ui/Main.qml'
    raw = path.read_bytes()
    old = b'                Button {\r\n                    text: "' + '发送'.encode() + b'"\r\n'
    assert raw.count(old) == 1
    path.write_bytes(raw.replace(old, b'                Button {\r\n                    objectName: "sendTextSubmitButton"\r\n                    text: "' + '发送'.encode() + b'"\r\n'))
    path = root / 'tests/ui_tests.cpp'
    raw = path.read_bytes()
    anchor = b'  private slots:\n'
    assert raw.count(anchor) == 1
    test = r'''
    // 日期：2026-11-07；真实点击发送时授信不足必须保留草稿及窗口，解除占用后同一草稿可重试成功。
    void rejectedTextKeepsDraftThroughQml() {
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", temporary.path());
        settings.setValue("terms", true);
        settings.sync();
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        Controller controller(port, nullptr, temporary.filePath("state"));
        dukto::LegacyListener receiver(temporary.path(), 3000);
        QVERIFY(receiver.listen(QHostAddress::LocalHost, 0));
        QSignalSpy result(&receiver, &dukto::LegacyListener::result);
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        view.setSource(QUrl("qrc:/ui/Main.qml"));
        QCOMPARE(view.status(), QQuickWidget::Ready);
        view.show();
        auto root = view.rootObject();
        QVERIFY(root);
        click(view, root->findChild<QQuickItem *>("manualSendButton"));
        auto sendDialog = root->findChild<QObject *>("sendDialog");
        QVERIFY(sendDialog);
        QTRY_VERIFY(sendDialog->property("opened").toBool());
        auto host = root->findChild<QQuickItem *>("hostInput");
        click(view, host);
        QTest::keyClicks(&view, QString("127.0.0.1:%1").arg(receiver.serverPort()));
        auto action = findItem(view.quickWindow()->contentItem(), "sendAction0");
        click(view, action);
        auto dialog = root->findChild<QObject *>("textDialog");
        QVERIFY(dialog);
        QTRY_VERIFY(dialog->property("opened").toBool());
        auto editor = root->findChild<QQuickItem *>("textEditor");
        QVERIFY(editor);
        const auto draft = QStringLiteral("保存我的草稿\nUnicode café 🚀");
        editor->setProperty("text", draft);
        const auto before = dukto::BufferCredit::usage()["dataUsed"].toString().toLongLong();
        {
            dukto::BufferCredit saturated(120 * 1024 * 1024 - before, true);
            click(view, root->findChild<QQuickItem *>("sendTextSubmitButton"));
            QTest::qWait(300);
            QVERIFY(!controller.busy());
            QCOMPARE(result.count(), 0);
            QVERIFY2(dialog->property("visible").toBool(), "Rejected send closed the text editor");
            QCOMPARE(editor->property("text").toString(), draft);
            QVERIFY(dialog->property("sendError").toString().contains(QStringLiteral("授信")));
            auto error = root->findChild<QQuickItem *>("sendTextError");
            QVERIFY(error && error->isVisible());
        }
        QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString().toLongLong(), before);
        click(view, root->findChild<QQuickItem *>("sendTextSubmitButton"));
        QTRY_COMPARE_WITH_TIMEOUT(result.count(), 1, 5000);
        QCOMPARE(result[0][0].toInt(), 0);
        QCOMPARE(qvariant_cast<dukto::LegacyResult>(result[0][1]).json()["text"].toString(), draft);
        QTRY_VERIFY(!dialog->property("visible").toBool());
        QTRY_VERIFY(!sendDialog->property("visible").toBool());
        QTRY_VERIFY(!controller.busy());
    }
'''
    path.write_bytes(raw.replace(anchor, anchor + test.encode('utf-8')))
    print(json.dumps({'backedUpFiles': len(names), 'baselineTestPrepared': True}))


if __name__ == '__main__':
    main()
