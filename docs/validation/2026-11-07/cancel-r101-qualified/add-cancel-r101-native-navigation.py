"""日期：2026-11-07；把真实兼容取消加入已有三平台原生导航回归，限制原生QtTest可执行槽位。"""
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess


# 日期：2026-11-07；首轮完整Qt报告不覆盖，JUnit收验错误与产品测试结果分开登记后才改下一批输入。
def main():
    root = Path.cwd()
    first = root / 'docs/validation/2026-11-07/cancel-r101-corrected-windows'
    assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 23$',
                     (first / 'ucrt/ctest.log').read_text('utf-8'), re.M)
    shutil.copyfile(root / '.cache/validate-cancel-r101-corrected-windows.py', first / 'initial-validation-driver.py')
    failure = {'date': '2026-11-07', 'outerDriverExitCode': 1,
               'stage': 'UCRT complete tests finished; local collector assumed Qt native XML instead of configured JUnit',
               'error': 'ValueError unpacking nonexistent TestFunction in testsuite XML',
               'ucrtCtestSummary': '23/23 passed', 'ucrtThreeCancellationRowsPassed': True,
               'numericChildExitCodeNotPersistedBeforeCollectorError': True,
               'msvcNotStartedByThisDriver': True, 'sourceInputsUnchangedDuringRun': True,
               'nextStep': 'Correct JUnit reader; add native cancellation/selector guard and rebuild both toolchains',
               'productFailureClaimed': False, 'releaseQualified': False, 'deliveryComplete': False}
    (first / 'collector-failure.json').write_text(json.dumps(failure, indent=2) + '\n', 'utf-8')
    backup = root / '.cache/cancel-r101-before'
    records = json.loads((backup / 'source-before.json').read_text('utf-8'))
    name = 'tests/main_window_navigation_integration.py'
    raw = (root / name).read_bytes()
    target = backup / name
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists()
    target.write_bytes(raw)
    records.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                    'utf8Bom': raw.startswith(b'\xef\xbb\xbf'), 'crlf': b'\r\n' in raw})
    (backup / 'source-before.json').write_text(json.dumps(records, indent=2) + '\n', 'utf-8')
    update = runpy.run_path('.cache/finalize-skip-items-r84.py')['update']

    # 日期：2026-11-07；只允许两项不写系统剪贴板的测试，不能靠附带服务器槽名执行其他原生槽。
    def cpp(text):
        assert '#include <QMetaMethod>' not in text
        text = text.replace('#include <QQuickItem>', '#include <QMetaMethod>\n#include <QQuickItem>', 1)
        old = '// 日期：2026-11-05；默认offscreen隔离剪贴板；显式原生模式只准执行不接触剪贴板的服务器入口测试。'
        assert text.count(old) == 1
        text = text.replace(old, '// 日期：2026-11-07；默认offscreen隔离剪贴板；原生只准运行服务器入口和兼容取消，拒绝混入其他槽。', 1)
        old = '''    if (!native.isEmpty() && (QGuiApplication::platformName().toLatin1() != native ||
                              !app.arguments().contains("serverEntryThroughMainQml") ||
                              app.arguments().contains("dragClipboardAndTextThroughQml")))
        return 2;'''
        new = '''    if (!native.isEmpty()) {
        if (QGuiApplication::platformName().toLatin1() != native)
            return 2;
        const QStringList allowed{"serverEntryThroughMainQml", "cancelThenTransferAgainThroughQml"};
        bool selected = false;
        for (const auto &argument : app.arguments().mid(1)) {
            for (int index = UiTests::staticMetaObject.methodOffset();
                 index < UiTests::staticMetaObject.methodCount(); ++index) {
                const auto name = QString::fromLatin1(UiTests::staticMetaObject.method(index).name());
                if (argument == name || argument.startsWith(name + ':')) {
                    if (!allowed.contains(name))
                        return 2;
                    selected = true;
                }
            }
        }
        if (!selected)
            return 2;
    }'''
        assert text.count(old) == 1
        return text.replace(old, new, 1)

    # 日期：2026-11-07；沿用原生窗口和150/200%场景，实际执行三取消行并验证白名单拒绝发生在测试前。
    def python(text):
        text = text.replace('日期：2026-11-05；固定QtTest程序身份，每个场景使用独立目录，原失败和截图不相互覆盖。',
                            '日期：2026-11-07；固定QtTest身份，原生导航/三取消及槽位白名单独立留存，失败和截图不覆盖。', 1)
        old = 'production Main.qml loaded by compiled application controller fixture; real native server-entry click, compact/default layout, tabs, back/reopen and resize; high-DPI scenes use isolated offscreen; packaged GUI/native choosers and complete R6 remain separate'
        assert text.count(old) == 1
        text = text.replace(old, 'production Main.qml native server entry and send/header/partial-body cancellation clicks; every cancellation checks cleanup, credit return and later same-instance bidirectional content; compact/default layout and isolated high-DPI scenes; native selector rejects clipboard test slots before execution; packaged GUI/native choosers and complete R6 remain separate', 1)
        old = '''                result = subprocess.run([str(executable), "serverEntryThroughMainQml",
                                         "-o", str(log) + ",txt", "-o", str(xml) + ",junitxml"],'''
        new = '''                if platform != "offscreen":
                    guard = subprocess.run([str(executable), "serverEntryThroughMainQml",
                                            "clipboardAvailabilityDoesNotReadOnProgress"],
                                           env=env, cwd=working, capture_output=True, timeout=30)
                    entry["nativeSelectorGuard"] = {"exitCode": guard.returncode,
                                                    "passed": guard.returncode == 2}
                    assert guard.returncode == 2, entry
                result = subprocess.run([str(executable), "serverEntryThroughMainQml",
                                         "cancelThenTransferAgainThroughQml",
                                         "-o", str(log) + ",txt", "-o", str(xml) + ",junitxml"],'''
        assert text.count(old) == 1
        text = text.replace(old, new, 1)
        old = '''                assert "serverEntryThroughMainQml(compact)" in text and "serverEntryThroughMainQml(default)" in text
                frames = []'''
        new = '''                assert "serverEntryThroughMainQml(compact)" in text and "serverEntryThroughMainQml(default)" in text
                cancellation = ["send", "receive-header", "receive-partial"]
                for tag in cancellation:
                    assert text.splitlines().count("PASS   : UiTests::cancelThenTransferAgainThroughQml(" + tag + ")") == 1
                matching = [case for case in suite.findall("testcase")
                            if case.get("name") == "cancelThenTransferAgainThroughQml"]
                assert len(matching) == 1 and matching[0].get("result") == "pass"
                entry["verifiedCancellationRows"] = cancellation
                frames = []'''
        assert text.count(old) == 1
        return text.replace(old, new, 1)

    update(root / 'tests/ui_tests.cpp', cpp)
    update(root / name, python)
    subprocess.run([str(root / '.tools/python/Scripts/clang-format.exe'), '-i',
                    str(root / 'tests/ui_tests.cpp')], check=True)
    compile((root / name).read_text('utf-8-sig'), name, 'exec')
    for row in records:
        data = (root / row['path']).read_bytes()
        data.decode('utf-8-sig')
        assert data.startswith(b'\xef\xbb\xbf') == row['utf8Bom'] and (b'\r\n' in data) == row['crlf']
    print(json.dumps({'existingNativeAndHighDpiScenesExtended': 3, 'cancellationRowsPerScene': 3,
                      'nativeClipboardSlotsRejectedBeforeTestExecution': True, 'encodingPreserved': True}))


if __name__ == '__main__':
    main()
