"""日期：2026-11-07；独立编译新退出夹具测试，链接未变的原生产核心，不覆盖原构建。"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；新目录独立生成Qt元对象再编译；原核心/原测试不变，核对四种状态和16组TLS。
def main():
    root = Path('/home/dukto/listener-r95-final')
    output = Path('/home/dukto/exit-state-r97-targeted-moc')
    output.mkdir(exist_ok=False)
    original = [root / 'build/file-exchange-tests', root / 'build/libdukto-core.a']
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in original}
    source_path = output / 'file_exchange_tests.cpp'
    source_path.write_text(TEST_SOURCE, 'utf-8')
    commands = subprocess.run(['ninja', '-t', 'commands', 'file-exchange-tests'],
                              cwd=root / 'build', capture_output=True, text=True, check=True)
    old_source = str(root / 'tests/file_exchange_tests.cpp')
    compile_line, = [line for line in commands.stdout.splitlines() if ' -c ' in line and old_source in line]
    old_object = 'CMakeFiles/file-exchange-tests.dir/tests/file_exchange_tests.cpp.o'
    replacements = {old_object: str(output / 'test.o'), old_object + '.d': str(output / 'test.o.d'),
                    old_source: str(source_path)}
    compile_args = [replacements.get(arg, arg) for arg in shlex.split(compile_line)]
    link_line, = [line for line in commands.stdout.splitlines()
                  if line.startswith(': && ') and ' -o file-exchange-tests ' in line]
    assert link_line.endswith(' && :')
    binary = output / 'file-exchange-tests'
    link_args = [str(output / 'test.o') if arg == old_object else
                 str(binary) if arg == 'file-exchange-tests' else arg
                 for arg in shlex.split(link_line[len(': && '):-len(' && :')])]
    with (output / 'build.log').open('xb') as log:
        subprocess.run(['/usr/lib/qt5/bin/moc', str(source_path), '-o', str(output / 'file_exchange_tests.moc')],
                       cwd=root / 'build', stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
        subprocess.run(compile_args, cwd=root / 'build', stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=300)
        subprocess.run(link_args, cwd=root / 'build', stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=120)
    environment = os.environ.copy()
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    with (output / 'stdout.log').open('xb') as log:
        result = subprocess.run([str(binary), 'childExitWait', 'parallelDispositions',
                                 '-o', str(output / 'qt.log') + ',txt',
                                 '-o', str(output / 'qt.xml') + ',junitxml'], cwd=root,
                                env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    assert result.returncode == 0
    tree = ET.parse(output / 'qt.xml')
    assert not tree.findall('.//failure') and not tree.findall('.//error')
    assert all(case.get('result') == 'pass' for case in tree.findall('.//testcase'))
    text = (output / 'qt.log').read_text('utf-8')
    assert text.count('PASS   : FileExchangeTests::childExitWait(') == 4
    assert text.count('PASS   : FileExchangeTests::parallelDispositions(') == 16
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == value for path, value in before.items())
    value = {'date': '2026-11-07', 'testSourceCommitPending': True,
             'testSourceSha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
             'productionCoreCommit': '5dd243fbad36da36568943513deed95ee124ba2d',
             'originalFiles': before, 'originalFilesUnchanged': True,
             'binarySha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
             'newStateDataRows': 4, 'originalParallelDataRows': 16,
             'originalWaitMs': 10000, 'passed': True,
             'scope': 'Recompiled changed tests linked to unchanged original production core; not a clean full build',
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'report.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)


if __name__ == '__main__':
    main()
