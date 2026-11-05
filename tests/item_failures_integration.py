"""日期：2026-11-05；真实双向1/4/16通道核验接收失败定位、部分完成、重启和旧日志边界。"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import uuid

from conflict_fail_integration import start
from service_integration import free_port, run
from task_items_integration import pages, task_record
from transfer_integration import digest, transfer


# 日期：2026-11-05；任务按原请求精确查找，不把其他已完成任务误当作冲突样本。
def task_for(executable, client, request):
    result, _ = run(executable, client, ['tasks'])
    matching = [item for item in result['tasks'] if item['requestId'] == request]
    assert len(matching) == 1, matching
    return matching[0]['taskId']


# 日期：2026-11-05；查询只读并离线检查原目标；文件和目录准备失败都必须定位到唯一条目。
def conflict_case(executable, root, server, client, shared, channels, direction, directory):
    name = f'{direction}-{channels}-' + ('目录' if directory else '文件.bin')
    source = root / name
    if directory:
        source.mkdir()
        (source / 'child.bin').write_bytes(b'new-content')
    else:
        source.write_bytes(b'new-content')
    if direction == 'download':
        import shutil
        if directory:
            shutil.copytree(source, shared / name)
        else:
            shutil.copyfile(source, shared / name)
    destination = shared / ('target-' + name) if direction == 'upload' else root / ('target-' + name)
    destination.mkdir()
    original = destination / name
    if directory:
        original.mkdir()
        original = original / 'preserved.bin'
    original.write_bytes(b'original-content')
    expected = digest(original)
    request = str(uuid.uuid4())
    operation = (['upload', '--share', 'data', '--path', str(source), '--remote-path', destination.name]
                 if direction == 'upload' else
                 ['download', '--share', 'data', '--remote-path', name, '--output', str(destination)])
    failure = transfer(executable, client, [*operation, '--threads', str(channels), '--on-conflict', 'fail',
                                            '--request-id', request], 4)
    assert failure['stage'] == 'conflict'
    task = task_for(executable, client, request)
    before = task_record(server, task)
    values = pages(executable, client, task, all_pages=True)
    assert values[0].get('failureEvidenceAvailable') is True, values[0]
    assert values[0]['failureScope'] == 'receiver-local'
    entries = [item for page in values for item in page['entries']]
    recorded = [item for item in entries if item['lastFailure'] is not None]
    assert len(recorded) == 1 and recorded[0]['id'] == '1', entries
    assert recorded[0]['lastFailure'] == {'version': 1, 'phase': 'prepare' if directory else 'open',
                                           'code': 4, 'stage': 'conflict', 'resolved': False}
    assert all(item['confirmedBytes'] == '0' for item in entries)
    assert digest(original) == expected and list(destination.iterdir()) == [destination / name]
    assert task_record(server, task) == before
    # 日期：2026-11-05；普通非JSON命令行也展示原因，不能仅JSON消费者能看见。
    text = subprocess.run([executable, 'task-items', '--task', task, '--state-directory', str(client)],
                          capture_output=True, encoding='utf-8', timeout=60)
    assert text.returncode == 0 and 'lastFailure=' in text.stdout and not text.stderr, text.stdout
    return {'taskId': task, 'direction': direction, 'channels': channels, 'directory': directory,
            'failure': recorded[0]['lastFailure'], 'originalSha256': expected,
            'queryReadOnly': True, 'plainCliVisible': True}, values


# 日期：2026-11-05；跨16文件窗口先提交16项，后项冲突与随后未执行条目必须严格区分。
def partial_case(executable, root, server, client, shared, channels):
    destination = shared / f'partial-{channels}'
    destination.mkdir()
    source = root / f'partial-source-{channels}'
    source.mkdir()
    operation = ['upload', '--share', 'data', '--remote-path', destination.name]
    for index in range(18):
        path = source / f'{index:02}.bin'
        path.write_bytes(f'content-{index}'.encode())
        operation += ['--path', str(path)]
    (destination / '16.bin').write_bytes(b'original')
    request = str(uuid.uuid4())
    transfer(executable, client, [*operation, '--threads', str(channels), '--on-conflict', 'fail',
                                  '--request-id', request], 4)
    task = task_for(executable, client, request)
    values = pages(executable, client, task, all_pages=True)
    entries = [item for page in values for item in page['entries']]
    assert len(entries) == 18
    for item in entries[:16]:
        assert item['disposition'] == 'copied' and item['lastFailure'] is None
        assert digest(destination / item['target']) == item['sha256']
    assert entries[16]['lastFailure']['code'] == 4 and entries[16]['lastFailure']['resolved'] is False
    assert entries[17]['disposition'] == 'not-executed' and entries[17]['lastFailure'] is None
    assert (destination / '16.bin').read_bytes() == b'original' and not (destination / '17.bin').exists()
    return {'taskId': task, 'channels': channels, 'copied': 16, 'failed': 1, 'notExecuted': 1}


# 日期：2026-11-05；仅修改本次失败下载的私有日志；篡改枚举/清单必须报6，旧表缺失明确降级。
def corrupt_and_old_journal(executable, client, task):
    journal = client / 'transfers' / f'receive-{task}.sqlite'
    before = digest(journal)
    pages(executable, client, task)
    assert digest(journal) == before
    with closing(sqlite3.connect(journal)) as database:
        row = database.execute('SELECT * FROM item_failures WHERE id=1').fetchone()
        assert row is not None
        for column, bad in (('code', 9), ('phase', 'network'), ('stage', 'auth'), ('resolved', 2), ('resolved', 'bad'), ('code', 4.5), ('code', 4294967300), ('resolved', 4294967296), ('spec', b'{}')):
            with database:
                database.execute(f'UPDATE item_failures SET {column}=? WHERE id=1', (bad,))
            pages(executable, client, task, expected=6)
            with database:
                database.execute('INSERT OR REPLACE INTO item_failures VALUES(?,?,?,?,?,?)', row)
        with database:
            database.execute('DROP TABLE item_failures')
    before = digest(journal)
    value = pages(executable, client, task)[0]
    assert value['failureEvidenceAvailable'] is False and value['entries'][0]['lastFailure'] is None
    assert digest(journal) == before
    return {'invalidCauseRejected': True, 'wrongManifestRejected': True,
            'legacyJournalExplicit': True, 'queryDoesNotMigrate': True}


# 日期：2026-11-05；所有样本使用隔离回环服务，重启后再比对持久原因和身份隔离。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    executable, report = str(Path(args.executable).resolve()), Path(args.report)
    assert not report.exists()
    results, saved = [], []
    with tempfile.TemporaryDirectory(prefix='dukto-item-failures-') as temporary:
        root = Path(temporary)
        server, client, shared = root / 'server', root / 'client', root / 'shared'
        shared.mkdir()
        info, _ = run(executable, server, ['serve', 'init', '--server-name', '127.0.0.1'])
        rights = ['--share', 'data', '--allow-upload', '--allow-download', '--allow-browse']
        run(executable, server, ['serve', 'share', 'add', '--path', str(shared), *rights])
        offer, _ = run(executable, server, ['serve', 'pairing', *rights])
        port = free_port()
        process = start(executable, server, port)
        try:
            run(executable, client, ['pair', '--to', f'127.0.0.1:{port}', '--fingerprint', info['fingerprint'],
                                     '--credential-file', offer['credentialFile']])
            for channels in (1, 4, 16):
                for direction in ('upload', 'download'):
                    for directory in (False, True):
                        result, values = conflict_case(executable, root, server, client, shared, channels, direction, directory)
                        results.append(result)
                        saved.append((result['taskId'], values))
            partial = [partial_case(executable, root, server, client, shared, channels) for channels in (1, 4, 16)]
        finally:
            process.kill()
            process.wait(timeout=10)
            process.output_drain.finish()
            assert not process.stderr.read()
        process = start(executable, server, port)
        try:
            for task, values in saved:
                assert pages(executable, client, task, all_pages=True) == values
            download = next(item['taskId'] for item in results if item['direction'] == 'download' and not item['directory'])
            integrity = corrupt_and_old_journal(executable, client, download)
        finally:
            process.kill()
            process.wait(timeout=10)
            process.output_drain.finish()
            assert not process.stderr.read()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'date': '2026-11-05', 'passed': True, 'cases': results, 'partial': partial,
                                  'restartStable': True, **integrity, 'executableSha256': digest(Path(executable)),
                                  'scriptSha256': digest(Path(__file__)),
                                  'scope': 'receiver-local historical causes; network/cancellation/GC/skip/overwrite and full release tracked separately'},
                                 ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'conflicts': len(results), 'partial': len(partial), **integrity}), flush=True)


if __name__ == '__main__':
    main()
