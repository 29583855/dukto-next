"""日期：2026-11-08；重复真实进程暂停/恢复与静默停顿，保留原五秒无进展期限和全部字节断言。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import traceback

from legacy_integration import frame
from legacy_timeout_integration import buffered, stalled


# 日期：2026-11-08；分块计算摘要，避免测试程序随执行文件体积增加峰值内存。
def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


# 日期：2026-11-08；逐文件读取固定测试输入，任一导入夹具换代均使整次执行身份无效。
def inputs():
    root = Path(__file__).resolve().parent
    names = [Path(__file__).name, 'legacy_integration.py', 'legacy_timeout_integration.py',
             'process_output.py']
    return {name: digest(root / name) for name in names}


# 日期：2026-11-08；冻结被构建的独立源码树，旧版对照和候选各自记录全部维护构建输入。
def sources(root):
    paths = [root / 'CMakeLists.txt']
    for folder in ['src', 'ui', 'resources', 'tests', 'scripts',
                   'third-party/sqlite-runtime', '.github/workflows']:
        paths.extend(path for path in (root / folder).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts)
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}


# 日期：2026-11-08；原夹具每轮四场景全部执行，失败也保存原结果，不提高期限、不把一次重试覆盖原失败。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    assert 1 <= args.rounds <= 10 and not args.report.exists()
    executable = args.executable.resolve()
    before = digest(executable)
    test_inputs = inputs()
    source_root = args.source_root.resolve()
    source_inputs = sources(source_root)
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source_root,
                              capture_output=True, text=True)
    report = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'passed': False,
              'sourceCommit': revision.stdout.strip() if revision.returncode == 0 else None,
              'system': platform.platform(), 'architecture': platform.machine(),
              'executableSha256': before, 'testInputs': test_inputs, 'roundsRequested': args.rounds,
              'sourceInputs': source_inputs,
              'receiverTimeoutSeconds': 5, 'pausedSeconds': 6, 'cases': [],
              'failureRootCauseProvenByThisReport': False}
    with tempfile.TemporaryDirectory(prefix='dukto-r6-ready-') as temporary:
        for index in range(args.rounds):
            root = Path(temporary) / str(index)
            root.mkdir()
            cases = [('buffered-valid', buffered, (str(executable), root, 'buffered-valid',
                      frame([('buffered.bin', b'arrived before resume')]), 0)),
                     ('buffered-invalid-text', buffered, (str(executable), root,
                      'buffered-invalid-text', frame([('___DUKTO___TEXT___', b'\xff\xfe')]), 6)),
                     ('silent-stall', stalled, (str(executable), root, False)),
                     ('partial-stall', stalled, (str(executable), root, True))]
            for name, fixture, arguments in cases:
                try:
                    case = fixture(*arguments)
                except Exception:
                    case = {'name': name, 'passed': False, 'fixtureError': traceback.format_exc()}
                case['round'] = index + 1
                report['cases'].append(case)
                print(json.dumps(case, ensure_ascii=False), flush=True)
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    report['executableAfterSha256'] = digest(executable)
    report['testInputsAfter'] = inputs()
    report['sourceInputsAfter'] = sources(source_root)
    report['passed'] = (len(report['cases']) == 4 * args.rounds
                        and all(case['passed'] for case in report['cases'])
                        and report['executableAfterSha256'] == before
                        and report['testInputsAfter'] == test_inputs
                        and report['sourceInputsAfter'] == source_inputs)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'passed': report['passed'], 'cases': len(report['cases'])}), flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
