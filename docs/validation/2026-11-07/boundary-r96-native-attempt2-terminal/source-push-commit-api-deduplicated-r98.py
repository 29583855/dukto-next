"""日期：2026-11-07；以有界小批次重试精确Git树发布，保留此前失败，不改变提交内容或强推分支。"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path.cwd()
CHECKOUT = ROOT / '.cache/github-29583855-dukto-next-r28'


# 日期：2026-11-07；只读取发布checkout对象，Git写操作仅限确认后的远端跟踪引用。
def git(*args):
    return subprocess.check_output(['git', *args], cwd=CHECKOUT)


# 日期：2026-11-07；缓存成功批次以便中断后继续，最终整树和提交哈希必须与本地完全一致。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--reuse-prior-binary-blobs', action='store_true')
    args = parser.parse_args()
    api = runpy.run_path('.cache/github-actions-r28.py')
    request = api['request']
    base = '/repos/' + api['REPOSITORY']
    commit = git('rev-parse', 'HEAD').decode().strip()
    parent = git('rev-parse', 'HEAD^').decode().strip()
    expected_tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
    remote = request(base + '/git/ref/heads/main')['object']['sha']
    if remote == commit:
        print(json.dumps({'alreadyPublished': True, 'commit': commit}), flush=True)
        return
    assert remote == parent, (remote, parent)
    ledger_path = ROOT / ('.cache/git-small-push-' + args.label + '.json')
    ledger = json.loads(ledger_path.read_text('utf-8')) if ledger_path.exists() else {
        'commit': commit, 'blobs': [], 'trees': []}
    assert ledger['commit'] == commit

    # 日期：2026-11-07；账目仅保存公开Git对象身份，不保存令牌、授权头或签名下载地址。
    def save():
        ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')

    metadata = {}
    for row in git('ls-tree', '-r', '-z', 'HEAD').split(b'\0'):
        if row:
            header, name = row.split(b'\t', 1)
            metadata[name.decode('utf-8')] = header.decode().split()
    # 日期：2026-11-07；远端父提交已逐SHA确认，父树中的同摘要对象可直接复用而不重复上传。
    parent_blobs = {row.split(b'\t', 1)[0].split()[2].decode()
                    for row in git('ls-tree', '-r', '-z', 'HEAD^').split(b'\0') if row}
    reused_parent_blobs = 0
    entries, records = [], []
    for encoded in git('diff-tree', '--no-commit-id', '--name-only', '-r', '-z', 'HEAD').split(b'\0'):
        if not encoded:
            continue
        name = encoded.decode('utf-8')
        mode, kind, blob = metadata[name]
        assert mode == '100644' and kind == 'blob'
        raw = git('cat-file', 'blob', blob)
        record = {'path': name, 'mode': mode, 'type': kind, 'sha': blob}
        records.append(record)
        if blob in parent_blobs:
            entries.append(record)
            reused_parent_blobs += 1
            continue
        binary = False
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError:
            binary = True
        if binary or len(raw) > 192 * 1024:
            if blob not in ledger['blobs']:
                if not (binary and args.reuse_prior_binary_blobs):
                    result = request(base + '/git/blobs', 'POST', {
                        'content': base64.b64encode(raw).decode('ascii'), 'encoding': 'base64'})
                    assert result['sha'] == blob, name
                ledger['blobs'].append(blob)
                save()
            entries.append(record)
        else:
            assert content.encode('utf-8') == raw
            entries.append({'path': name, 'mode': mode, 'type': kind, 'content': content})
    groups, group = [], []
    for entry in entries:
        candidate = group + [entry]
        if group and len(json.dumps({'tree': candidate}).encode('utf-8')) > 512 * 1024:
            groups.append(group)
            group = []
        group.append(entry)
    if group:
        groups.append(group)
    print(json.dumps({'preparedFiles': len(records), 'treeBatches': len(groups), 'reusedParentBlobs': reused_parent_blobs}), flush=True)
    tree = git('rev-parse', 'HEAD^^{tree}').decode().strip()
    for number, group in enumerate(groups):
        fingerprint = hashlib.sha256(json.dumps(group).encode('utf-8')).hexdigest()
        if number < len(ledger['trees']):
            cached = ledger['trees'][number]
            assert cached['inputTree'] == tree and cached['fingerprint'] == fingerprint
            tree = cached['outputTree']
        else:
            created = request(base + '/git/trees', 'POST', {'base_tree': tree, 'tree': group})['sha']
            ledger['trees'].append({'inputTree': tree, 'outputTree': created, 'fingerprint': fingerprint})
            tree = created
            save()
        print(json.dumps({'treeBatch': number + 1, 'batches': len(groups), 'files': len(group)}), flush=True)
    assert tree == expected_tree, (tree, expected_tree)
    author = git('show', '-s', '--format=%an%x00%ae%x00%aI', 'HEAD').decode().strip().split('\0')
    committer = git('show', '-s', '--format=%cn%x00%ce%x00%cI', 'HEAD').decode().strip().split('\0')
    message = git('cat-file', 'commit', commit).split(b'\n\n', 1)[1].decode('utf-8')
    result = request(base + '/git/commits', 'POST', {
        'message': message, 'tree': tree, 'parents': [parent],
        'author': dict(zip(('name', 'email', 'date'), author)),
        'committer': dict(zip(('name', 'email', 'date'), committer))})
    assert result['sha'] == commit, (result['sha'], commit)
    assert request(base + '/git/ref/heads/main')['object']['sha'] == parent
    result = request(base + '/git/refs/heads/main', 'PATCH', {'sha': commit, 'force': False})
    assert result['object']['sha'] == commit
    assert request(base + '/git/ref/heads/main')['object']['sha'] == commit
    subprocess.run(['git', 'update-ref', 'refs/remotes/origin/main', commit], cwd=CHECKOUT, check=True)
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'commit': commit,
               'parent': parent, 'tree': tree, 'files': records, 'treeBatches': len(groups),
               'reusedPriorBinaryBlobs': args.reuse_prior_binary_blobs,
               'maximumTreePayloadBytes': 512 * 1024, 'exactLocalCommitPreserved': True,
               'reusedParentBlobs': reused_parent_blobs, 'parentCommitVerifiedRemote': parent,
               'force': False, 'passed': True}
    output = ROOT / ('docs/validation/2026-11-06/github-api-push-' + args.label + '.json')
    assert not output.exists()
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'publishedCommit': commit, 'files': len(records), 'exactTreeVerified': True}), flush=True)


if __name__ == '__main__':
    main()
