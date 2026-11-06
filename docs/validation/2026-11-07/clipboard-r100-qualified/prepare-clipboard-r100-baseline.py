"""日期：2026-11-07；先保存原源字节，再建立实际QML进度刷新读取剪贴板的独立回归。"""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-07；仅在隔离offscreen剪贴板中计数正文读取，真实点击仍发送替换后的最新正文。
def main():
    root = Path.cwd()
    output = root / '.cache/clipboard-r100-before'
    output.mkdir(exist_ok=False)
    names = ('src/app/controller.cpp', 'src/app/controller.h', 'tests/ui_tests.cpp')
    records = []
    for name in names:
        raw = (root / name).read_bytes()
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        records.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                        'utf8Bom': raw.startswith(b'\xef\xbb\xbf'), 'crlf': b'\r\n' in raw})
    (output / 'source-before.json').write_text(json.dumps(records, indent=2) + '\n', 'utf-8')
    fixture = '''// 日期：2026-11-07；只在隔离Qt剪贴板中记录正文请求次数，保持QMimeData真实文本转换路径。
class CountingClipboardData final : public QMimeData {
  public:
    // 日期：2026-11-07；计数器独立于Qt接管的MIME对象存活，不复制或保存系统剪贴板内容。
    CountingClipboardData(std::shared_ptr<int> reads, const QString &text)
        : reads_(std::move(reads)) {
        setText(text);
    }

  protected:
    // 日期：2026-11-07；只有实际取正文才计数，格式查询与界面刷新本身不应读取正文。
    QVariant retrieveData(const QString &mimeType, QVariant::Type type) const override {
        if (mimeType == QStringLiteral("text/plain"))
            ++*reads_;
        return QMimeData::retrieveData(mimeType, type);
    }

  private:
    std::shared_ptr<int> reads_;
};

'''
    test = '''    // 日期：2026-11-07；生产QML的一百次进度通知不得重读剪贴板，空值禁用且点击发送必须读取最新正文。
    void clipboardAvailabilityDoesNotReadOnProgress() {
        QCOMPARE(QGuiApplication::platformName(), QString("offscreen"));
        auto clipboard = QApplication::clipboard();
        struct ClipboardReset final {
            // 日期：2026-11-07；包括断言提前返回在内，始终清空本测试的隔离Qt剪贴板。
            ~ClipboardReset() {
                QApplication::clipboard()->clear();
            }
        } reset;
        auto reads = std::make_shared<int>(0);
        clipboard->setMimeData(new CountingClipboardData(reads, QString(32768, QChar(0x6c49))));
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
        view.activateWindow();
        view.setFocus();
        auto root = view.rootObject();
        QVERIFY(root);
        click(view, root->findChild<QQuickItem *>("manualSendButton"));
        auto dialog = root->findChild<QObject *>("sendDialog");
        QVERIFY(dialog);
        QTRY_VERIFY(dialog->property("opened").toBool());
        auto host = root->findChild<QQuickItem *>("hostInput");
        click(view, host);
        QTRY_VERIFY(host->hasActiveFocus());
        QTest::keyClicks(&view, QString("127.0.0.1:%1").arg(receiver.serverPort()));
        QTRY_COMPARE(host->property("text").toString(),
                     QString("127.0.0.1:%1").arg(receiver.serverPort()));
        auto action = findItem(view.quickWindow()->contentItem(), "sendAction1");
        QVERIFY(action);
        QTRY_VERIFY(action->isVisible() && action->isEnabled());
        const int before = *reads;
        QVERIFY(before > 0);
        for (int index = 0; index < 100; ++index)
            QVERIFY(QMetaObject::invokeMethod(&controller, "stateChanged", Qt::DirectConnection));
        QCoreApplication::processEvents();
        QCOMPARE(*reads, before);
        clipboard->clear();
        QTRY_VERIFY(!action->isEnabled());
        const auto text = QStringLiteral("最新正文\\ncafé 🚀");
        auto replacementReads = std::make_shared<int>(0);
        clipboard->setMimeData(new CountingClipboardData(replacementReads, text));
        QTRY_VERIFY(action->isEnabled());
        const int beforeSend = *replacementReads;
        click(view, action);
        QTRY_COMPARE_WITH_TIMEOUT(result.count(), 1, 5000);
        QCOMPARE(result[0][0].toInt(), 0);
        QCOMPARE(result[0][1].value<dukto::LegacyResult>().json()["text"].toString(), text);
        QTRY_VERIFY(!controller.busy());
        QCOMPARE(*replacementReads, beforeSend + 1);
    }

'''
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    path = root / 'tests/ui_tests.cpp'
    # 日期：2026-11-07；插入前验证唯一锚点，文本保存沿用原BOM与换行。
    def transform(text):
        assert text.count('class UiTests final') == 1 and text.count('  private slots:\n\n') == 1
        return text.replace('#include <QtTest>\n', '#include <QtTest>\n#include <memory>\n', 1).replace(
            'class UiTests final', fixture + 'class UiTests final', 1).replace(
            '  private slots:\n\n', '  private slots:\n\n' + test, 1)
    helper['update'](path, transform)
    subprocess.run([str(root / '.tools/python/Scripts/clang-format.exe'), '-i', str(path)], check=True)
    raw = path.read_bytes()
    previous = records[-1]
    assert raw.startswith(b'\xef\xbb\xbf') == previous['utf8Bom'] and (b'\r\n' in raw) == previous['crlf']
    print(json.dumps({'baselineSourcesSaved': len(names), 'newRegressionAdded': True}), flush=True)


if __name__ == '__main__':
    main()
