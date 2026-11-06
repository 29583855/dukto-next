"""日期：2026-11-07；在首轮双Windows实际退出后修正UI测试上下文并补齐终端诊断结果。"""
from pathlib import Path
import hashlib
import json
import runpy
import shutil
import subprocess


# 日期：2026-11-07；原始失败永久保留，输入与所有测试程序前后摘要供定向复验资格核对。
def main():
    root = Path.cwd()
    first = root / 'docs/validation/2026-11-07/diagnostics-r103-windows'
    driver = json.loads((first / 'driver-result.json').read_text('utf-8'))
    assert not driver['passed'] and driver['buildInputsUnchanged']
    assert len(driver['cases']) == 2 and all(row['ctestExitCode'] == 8 and row['doctorExitCode'] == row['cliContractsExitCode'] == row['buildExitCode'] == 0 for row in driver['cases'])
    output = root / 'docs/validation/2026-11-07/diagnostics-r103-correction'
    output.mkdir(exist_ok=False)
    update = runpy.run_path('.cache/finalize-skip-items-r84.py')['update']
    binaries = {}
    for label, folder in [('ucrt', 'windows-ucrt'), ('msvc', 'windows/Release')]:
        paths = root / 'build' / folder
        binaries[label] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.glob('*-tests.exe')}
        assert len(binaries[label]) == 22
    (output / 'previous-test-binaries.json').write_text(json.dumps(binaries, indent=2) + '\n', 'utf-8')
    # 日期：2026-11-07；提供与生产相同的版本上下文，打开设置对话框后再查找其实际视觉控件。
    def ui(t):
        marker = '''        view.rootContext()->setContextProperty("controller", &controller);
        view.setSource(QUrl("qrc:/ui/Main.qml"));'''
        assert marker in t
        t = t.replace(marker, '''        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        view.resize(430, 700);
        view.setSource(QUrl("qrc:/ui/Main.qml"));''', 1)
        marker = '''        QVERIFY(view.rootObject());
        QVERIFY(findItem(view.quickWindow()->contentItem(), "exportDiagnosticReportButton"));'''
        assert marker in t
        return t.replace(marker, '''        QVERIFY(view.rootObject());
        view.show();
        QTRY_VERIFY(!view.grabFramebuffer().isNull());
        auto settings = view.rootObject()->findChild<QObject *>("settingsDialog");
        QVERIFY(settings);
        QVERIFY(QMetaObject::invokeMethod(settings, "open"));
        QTRY_VERIFY(settings->property("opened").toBool());
        auto button = findItem(view.quickWindow()->contentItem(), "exportDiagnosticReportButton");
        QVERIFY(button);
        QCOMPARE(button->property("text").toString(), QStringLiteral("导出本地诊断"));''', 1)
    update(root / 'tests/ui_tests.cpp', ui)
    update(root / 'ui/Main.qml', lambda t: t.replace('        id: settingsDialog\n', '        id: settingsDialog\n        objectName: "settingsDialog"\n', 1))
    # 日期：2026-11-07；人类输出显示固定检查ID/状态/建议，peer失败不会被笼统通过消息遮盖。
    def cli(t):
        t = t.replace('// 日期：2026-11-06；JSON直接写已编码UTF-8', '// 日期：2026-11-07；JSON直接写已编码UTF-8', 1)
        t = t.replace('// 日期：2026-11-05；三平台控制台入口严格核对传输策略', '// 日期：2026-11-07；三平台控制台入口严格核对传输策略', 1)
        marker = '    } else if (event.contains("values")) {'
        assert t.count(marker) == 1
        return t.replace(marker, '''    } else if (event.value("event") == "doctor") {
        stream << event.value("message").toString() << '\\n';
        for (const auto &value : event.value("checks").toArray()) {
            const auto check = value.toObject();
            stream << check["id"].toString() << " [" << check["status"].toString() << "] "
                   << check["message"].toString() << '\\n';
        }
        const auto peer = event.value("peer").toObject();
        stream << "peer [" << peer["status"].toString() << "] " << peer["message"].toString() << '\\n';
        const auto capabilities = peer["capabilities"].toObject();
        for (auto item = capabilities.begin(); item != capabilities.end(); ++item)
            stream << item.key() << " = " << (item.value().toBool() ? "true" : "false") << '\\n';
    } else if (event.contains("values")) {''', 1)
    update(root / 'src/cli/main.cpp', cli)
    update(root / 'scripts/ci_protocol.py', lambda t: t.replace('# 日期：2026-11-06；集中声明跨平台真实专项及必需计量验证', '# 日期：2026-11-07；集中声明跨平台真实专项及必需计量验证', 1))
    formatter = str(root / '.tools/python/Scripts/clang-format.exe')
    for path in (root / 'tests/ui_tests.cpp', root / 'src/cli/main.cpp'):
        raw = path.read_bytes()
        text = subprocess.check_output([formatter, str(path)]).decode('utf-8-sig').replace('\r\n', '\n')
        path.write_bytes((b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') + text.replace('\n', '\r\n' if b'\r\n' in raw else '\n').encode('utf-8'))
    shutil.copyfile(Path(__file__), output / 'correction-driver.py')
    print('Original failure retained; only UI fixture and human doctor output adjusted')


if __name__ == '__main__':
    main()
