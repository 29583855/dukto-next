"""日期：2026-11-07；逐个平台收验R116的27个CTest与26份Qt原件，保留诊断和精确跳过。"""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import runpy
import stat
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'


# 日期：2026-11-07；验证官方ZIP摘要后只提取普通有界文本，原件已存在时必须字节相同。
def extract(raw, folder):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names, total = set(), 0
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            assert not name.is_absolute() and '..' not in name.parts and ':' not in member.filename
            assert member.filename not in names and not stat.S_ISLNK(member.external_attr >> 16)
            names.add(member.filename)
            total += member.file_size
            assert member.file_size < 32 * 1024**2 and total < 128 * 1024**2
            if member.is_dir() or name.suffix not in ('.log', '.xml', '.json', '.txt', '.sha256'):
                continue
            target = folder / member.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            raw_file = archive.read(member)
            if target.exists():
                assert target.read_bytes() == raw_file, target
            else:
                target.write_bytes(raw_file)


# 日期：2026-11-07；按Qt原格式核对真实结果和诊断，不把errors属性里的XFAIL/skip混成业务失败。
def qt(path, runner):
    tree = ET.fromstring(path.read_bytes(), ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    assert tree.get('failures') == '0' and not tree.findall('.//failure') and not tree.findall('.//error')
    comments = [node.text for node in tree.iter() if node.tag is ET.Comment]
    kinds = {}
    for comment in comments:
        match = re.search(r'type="([^"]+)"', comment)
        assert match
        kind = match.group(1)
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == 'skip':
            assert runner == 'windows-2022' and path.name == 'upload-scan-cleanup-tests.xml'
            assert 'tag="symbolic&#x002D;link"' in comment or 'tag="symbolic-link"' in comment
            assert 'message="Windows account cannot create a native symbolic link"' in comment
        elif kind == 'qwarn':
            assert path.name == 'avatars-tests.xml' and 'QNetworkReplyImplPrivate::error: Internal problem, this method must only be called once.' in comment
        elif kind == 'qinfo':
            assert path.name == 'file-exchange-tests.xml' and 'terminal fixture ' in comment
        elif kind == 'info':
            assert runner.startswith('macos-') and path.name == 'core-tests.xml'
        else:
            raise AssertionError((path, comment))
    assert int(tree.get('errors', '0')) == len(comments), (path, tree.attrib, comments)
    cases = tree.findall('testcase')
    assert cases
    expected = []
    for case in cases:
        if case.get('result') == 'xfail':
            assert runner.startswith('macos-') and path.name == 'core-tests.xml' and case.get('name') == 'exclusiveTcpBinding'
            expected.append(case.get('name'))
        else:
            assert case.get('result') == 'pass'
    return {'xml': path.name, 'methods': len(cases), 'diagnostics': kinds, 'expectedDarwinFailures': expected}


# 日期：2026-11-07；只对完整成功的核心步骤授予资格，旧Darwin边界和Windows权限缺口继续列明。
def main():
    publication = json.loads((ROOT / '.cache/r116-source-publication.json').read_bytes())
    source = publication['sourceCommit']
    runs = json.loads((ROOT / '.cache/r116-ci-runs.json').read_bytes())
    run_id = runs['nativeRunId']
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    api = '/repos/29583855/dukto-next'
    path = api + '/actions/runs/' + str(run_id)
    run = request(path)
    assert run['head_sha'] == source and run['run_attempt'] == 1
    jobs = request(path + '/jobs?per_page=100')['jobs']
    artifacts = request(path + '/artifacts?per_page=100')['artifacts']
    output = REPO / 'docs/validation/2026-11-07/upload-scan-r116-native-core'
    cache = ROOT / '.cache/upload-scan-r116-native-artifacts'
    output.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    records = []
    for runner in ['ubuntu-22.04', 'macos-15', 'macos-15-intel', 'windows-2022']:
        job, = [job for job in jobs if job['name'].startswith('native (' + runner + ',')]
        items = [item for item in artifacts if item['name'] == 'core-validation-' + runner]
        if not items:
            records.append({'runner': runner, 'available': False, 'jobStatus': job['status'], 'qualified': False})
            continue
        item, = items
        assert not item['expired']
        archive = cache / (str(item['id']) + '.zip')
        raw = archive.read_bytes() if archive.exists() else request(api + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + digest
        if not archive.exists():
            archive.write_bytes(raw)
        folder = output / runner
        folder.mkdir(exist_ok=True)
        extract(raw, folder)
        ctest, = folder.rglob('ctest.log')
        text = ctest.read_text('utf-8-sig')
        step, = [step for step in job['steps'] if step['name'] == 'Core and GUI controller tests']
        record = {'runner': runner, 'available': True, 'jobId': job['id'], 'coreStep': step['conclusion'],
                  'artifactId': item['id'], 'artifactSha256': digest,
                  'ctestSha256': hashlib.sha256(ctest.read_bytes()).hexdigest(), 'qualified': False}
        if step['conclusion'] != 'success':
            record['originalFailureRetained'] = True
            if runner == 'windows-2022':
                # 日期：2026-11-07；完整保留真实热日志场景异常，其余26个CTest单独核验，绝不授予整套通过。
                assert '96% tests passed, 1 tests failed out of 27' in text
                assert '2 - upload-scan-cleanup-tests (Failed)' in text
                original = ctest.parent / 'Testing/QtTest/upload-scan-cleanup-tests.xml'
                failed_tree = ET.fromstring(original.read_bytes())
                failed = [case for case in failed_tree.findall('testcase') if case.get('result') == 'fail']
                assert len(failed) == 1 and failed[0].get('name') == 'retainedPreviewAndCleanup'
                failure, = failed[0].findall('failure')
                assert failure.get('message') == 'Caught unhandled exception'
                xmls = sorted((ctest.parent / 'Testing/QtTest').glob('*.xml'))
                assert len(xmls) == 26
                verified = [qt(xml, runner) for xml in xmls if xml != original]
                scan_log = ctest.parent / 'Testing/QtTest/upload-scan-cleanup-tests.log'
                assert 'PASS   : UploadScanCleanupTests::retainedPreviewAndCleanup(before-scan)' in scan_log.read_text('utf-8-sig')
                record.update(ctestTargetsPassed=26, ctestTargetsFailed=1,
                              failedMethod='retainedPreviewAndCleanup', failedDataRow='hot-journal',
                              failureMessage=failure.get('message'), completeScanSuiteQualified=False,
                              allOtherQtReportsVerified=verified)
        else:
            assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 27$', text, re.M), runner
            # 日期：2026-11-07；只计CTest原目录；主窗口导航另有三份独立XML，不能混入27项目录计数。
            xmls = sorted((ctest.parent / 'Testing/QtTest').glob('*.xml'))
            assert len(xmls) == 26, (runner, len(xmls))
            verified = [qt(xml, runner) for xml in xmls]
            expected = [method for row in verified for method in row['expectedDarwinFailures']]
            assert len(expected) == (1 if runner.startswith('macos-') else 0)
            scan_log, = folder.rglob('upload-scan-cleanup-tests.log')
            scan_text = scan_log.read_text('utf-8-sig')
            scan_xml, = folder.rglob('upload-scan-cleanup-tests.xml')
            assert len(ET.fromstring(scan_xml.read_bytes()).findall('testcase')) == 11
            skips = [line for line in scan_text.splitlines() if line.startswith('SKIP')]
            if skips:
                assert runner == 'windows-2022' and len(skips) == 1 and 'unsafeObjects(symbolic-link)' in skips[0]
                assert 'Totals: 24 passed, 0 failed, 1 skipped' in scan_text
            else:
                assert 'Totals: 25 passed, 0 failed, 0 skipped' in scan_text
                assert 'PASS   : UploadScanCleanupTests::unsafeObjects(symbolic-link)' in scan_text
            for method in ['retainedPreviewAndCleanup', 'interruptedCleanup', 'damagedEvidence', 'publishedAndLocks',
                           'unsafeObjects', 'cancelledCleanup', 'corruptDatabase', 'exhaustedCacheCredit', 'realCli']:
                assert 'PASS   : UploadScanCleanupTests::' + method + '(' in scan_text
            directory, = folder.rglob('directory-cleanup-tests.log')
            assert 'Totals: 59 passed, 0 failed, 0 skipped' in directory.read_text('utf-8-sig')
            record.update(qualified=True, ctestTargetsPassed=27, qtXmlReportsVerified=26,
                          scanRowsPassed=24 if skips else 25, scanRowsSkipped=len(skips),
                          scanNativeSymbolicLinkQualified=not skips, scanJUnitMethods=11,
                          scanLogSha256=hashlib.sha256(scan_log.read_bytes()).hexdigest(),
                          scanXmlSha256=hashlib.sha256(scan_xml.read_bytes()).hexdigest(),
                          directoryRowsPassed=59, verifiedQtReports=verified)
        (folder / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
        records.append(record)
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
               'run': {key: run[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']},
               'records': records, 'allFourNativeCoreJobsVerified': len(records) == 4 and all(row['qualified'] for row in records),
               'fullNativeProtocolQualified': False, 'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'runStatus': run['status'], 'records': [{key: row[key] for key in ['runner', 'qualified', 'available']} for row in records]}), flush=True)


if __name__ == '__main__':
    main()
