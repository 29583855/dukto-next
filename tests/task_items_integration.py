"""日期：2026-11-05；真实CLI/TLS验证双向逐项记录、分页、部分完成、身份和跨重启查询。"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import uuid

from conflict_fail_integration import start
from service_integration import free_port, run
from transfer_integration import digest, transfer


# 日期：2026-11-05；逐行消费命令行全部页，测试只保存有界201项样本，产品不累积页。
def pages(executable, client, task, after=0, all_pages=False, expected=0):
    command = [executable, 'task-items', '--task', task, '--after', str(after),
               '--state-directory', str(client), '--json']
    if all_pages:
        command.append('--all')
    process = subprocess.run(command, capture_output=True, encoding='utf-8', timeout=60)
    assert process.returncode == expected and not process.stderr, (process.returncode, process.stdout, process.stderr)
    values = [json.loads(line) for line in process.stdout.splitlines()]
    if not expected:
        cursor = after
        for page in values:
            assert page['event'] == 'task-items' and page['taskId'] == task
            assert page['currentContentVerified'] is False
            assert len(page['entries']) <= 100
            assert len(json.dumps(page, ensure_ascii=False).encode()) < 65536
            for item in page['entries']:
                assert int(item['id']) == cursor + 1
                cursor += 1
                assert not Path(item['path']).is_absolute()
                assert not item['target'] or not Path(item['target']).is_absolute()
            assert int(page['after']) == cursor
            assert not page['more'] or page['entries']
    return values


# 日期：2026-11-05；仅散列应用任务库数据而不包含SQLite连接短期锁，证明翻页不改变任务修订。
def task_record(server, task):
    with closing(sqlite3.connect(server / 'service/tasks.sqlite')) as database:
        return database.execute('SELECT * FROM tasks WHERE id=?', (task,)).fetchone()


# 日期：2026-11-05；同一真实接收根重复传输产生重命名，逐项名称必须能打开并匹配外部摘要。
def completed_case(executable, root, server, client, shared, channels, direction):
    source = root / f'source-{direction}-{channels}'
    (source / '资料/empty').mkdir(parents=True)
    for index in range(201):
        (source / '资料' / f'{index:04}.bin').write_bytes(bytes(range(251)) * 2 + str(index).encode())
    if direction == 'download':
        shutil.copytree(source, shared / source.name)
    destination = shared / f'upload-{channels}' if direction == 'upload' else root / f'download-{channels}'
    destination.mkdir()
    base = (['upload', '--share', 'data', '--path', str(source), '--remote-path', destination.name]
            if direction == 'upload' else
            ['download', '--share', 'data', '--remote-path', source.name, '--output', str(destination)])
    transfer(executable, client, [*base, '--threads', str(channels)])
    final = transfer(executable, client, [*base, '--threads', str(channels)])
    task = final['taskId']
    before = task_record(server, task)
    assert before is not None
    values = pages(executable, client, task, all_pages=True)
    assert all(page['available'] for page in values) and len(values) == 3
    entries = [item for page in values for item in page['entries']]
    assert len(entries) == int(final['entries']) == 204
    assert all(item['disposition'] == 'copied' for item in entries)
    for item in entries:
        path = destination / item['target']
        assert path.exists() and item['target'] != item['path']
        if item['type'] == 'file':
            assert digest(path) == item['sha256']
            assert path.stat().st_size == int(item['confirmedBytes']) == int(item['bytes'])
    # 日期：2026-11-05；同游标重复结果稳定，末页不循环，非法游标必须失败。
    assert pages(executable, client, task)[0]['entries'] == values[0]['entries']
    assert not pages(executable, client, task, len(entries))[0]['entries']
    pages(executable, client, task, len(entries) + 1, expected=2)
    pages(executable, client, task, -1, expected=2)
    assert task_record(server, task) == before
    # 日期：2026-11-05；删改落盘文件后历史记录仍明确不做当前校验，查询不恢复或重写文件。
    leaf = next(item for item in entries if item['type'] == 'file')
    target = destination / leaf['target']
    target.write_bytes(b'external-change')
    assert pages(executable, client, task)[0]['currentContentVerified'] is False
    assert target.read_bytes() == b'external-change'
    return {'taskId': task, 'direction': direction, 'channels': channels,
            'entries': len(entries), 'pages': len(values), 'renamedTargetsVerified': True,
            'readOnlyTaskRevision': True, 'contentReverificationNotClaimed': True}


# 日期：2026-11-05；前项真实提交、后项冲突失败时保留逐项事实，不把整批失败解释为全部未复制。
def partial_case(executable, root, server, client, shared, direction):
    first, second = root / 'a-first.bin', root / 'z-conflict.bin'
    first.write_bytes(b'first')
    second.write_bytes(b'second')
    destination = shared / 'partial-upload' if direction == 'upload' else root / 'partial-download'
    destination.mkdir()
    if direction == 'upload':
        (destination / second.name).write_bytes(b'original')
        operation = ['upload', '--share', 'data', '--remote-path', destination.name,
                     '--path', str(first), '--path', str(second)]
    else:
        source = shared / 'partial-source'
        source.mkdir()
        shutil.copy(first, source)
        shutil.copy(second, source)
        (destination / source.name).mkdir()
        # 日期：2026-11-05；下载fail目录本身冲突会先失败，用独立文件验证其未执行证据。
        operation = ['download', '--share', 'data', '--remote-path', 'partial-source/z-conflict.bin',
                     '--output', str(destination)]
        (destination / second.name).write_bytes(b'original')
    request = str(uuid.uuid4())
    failure = transfer(executable, client, [*operation, '--on-conflict', 'fail', '--request-id', request], 4)
    assert failure['stage'] == 'conflict'
    tasks, _ = run(executable, client, ['tasks'])
    matching = [task for task in tasks['tasks'] if task['requestId'] == request]
    assert len(matching) == 1
    task = matching[0]['taskId']
    values = pages(executable, client, task, all_pages=True)
    entries = [item for page in values for item in page['entries']]
    # 日期：2026-11-05；服务端上传冲突为失败，下载端本地拒绝后远端发送任务可呈现中断。
    if direction == 'upload':
        assert values[0]['taskState'] == 'failed', values[0]
    assert entries[-1]['disposition'] == 'not-executed'
    if direction == 'upload':
        assert entries[0]['disposition'] == 'copied' and (destination / first.name).read_bytes() == b'first'
    assert (destination / second.name).read_bytes() == b'original'
    return {'taskId': task, 'direction': direction, 'serverTaskState': values[0]['taskState'],
            'dispositions': [item['disposition'] for item in entries]}


# 日期：2026-11-05；服务在测试内重启、主体另行配对；查询必须保留权限隔离和本机证据边界。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    report = Path(args.report)
    assert not report.exists()
    results = []
    with tempfile.TemporaryDirectory(prefix='dukto-task-items-') as temporary:
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
            paired, _ = run(executable, client, ['pair', '--to', f'127.0.0.1:{port}', '--fingerprint', info['fingerprint'],
                                                '--credential-file', offer['credentialFile']])
            for channels in (4, 16):
                for direction in ('upload', 'download'):
                    results.append(completed_case(executable, root, server, client, shared, channels, direction))
            partial = [partial_case(executable, root, server, client, shared, direction) for direction in ('upload', 'download')]
            # 日期：2026-11-05；仅移动本测试的接收状态模拟缺失记录，保持原身份文件的原生保护权限。
            original, saved = client / 'transfers', root / 'saved-transfers'
            assert original.resolve().is_relative_to(root.resolve()) and saved.resolve().is_relative_to(root.resolve())
            original.rename(saved)
            try:
                missing = pages(executable, client, results[1]['taskId'])[0]
                assert not missing['available'] and missing['reason'] == 'local-receipt-unavailable'
            finally:
                original.rmdir()  # 仅删除本次CLI安全创建的空目录，非空即失败。
                saved.rename(original)
            offer2, _ = run(executable, server, ['serve', 'pairing', *rights])
            stranger = root / 'stranger'
            run(executable, stranger, ['pair', '--to', f'127.0.0.1:{port}', '--fingerprint', info['fingerprint'],
                                       '--credential-file', offer2['credentialFile']])
            pages(executable, stranger, results[0]['taskId'], expected=4)
            before_restart = pages(executable, client, results[0]['taskId'])
        finally:
            process.kill()
            process.wait(timeout=10)
            process.output_drain.finish()
            assert not process.stderr.read()
        process = start(executable, server, port)
        try:
            assert pages(executable, client, results[0]['taskId']) == before_restart
            # 日期：2026-11-05；已有主体撤权后不再能查询历史路径。
            run(executable, server, ['serve', 'revoke', '--client', paired['client']])
            pages(executable, client, results[0]['taskId'], expected=4)
        finally:
            process.kill()
            process.wait(timeout=10)
            process.output_drain.finish()
            assert not process.stderr.read()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'date': '2026-11-05', 'passed': True, 'cases': results,
                                 'partial': partial, 'foreignOwnerRefused': True, 'revokedRefused': True,
                                 'restartStable': True, 'missingLocalReceiptExplicit': True,
                                 'executableSha256': digest(Path(executable)), 'scriptSha256': digest(Path(__file__)),
                                 'scope': 'loopback CLI/TLS receive evidence pagination; skip/overwrite/full release remain incomplete'},
                                ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
