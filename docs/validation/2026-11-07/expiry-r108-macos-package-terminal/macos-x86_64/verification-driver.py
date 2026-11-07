"""日期：2026-11-07；核验R108 Intel Mac依赖部署包及真实搬迁业务，不把单job视作整轮完成。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

SOURCE = '641920f75b76149d49ee01f134bf70097857dc3d'
RUN = 42333318212
JOB = 128284513470
ARTIFACT = 13558991748


# 日期：2026-11-07；只在Intel原生job成功后下载和核验该架构原件，保留ARM及整轮未决状态。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/' + str(RUN))
    assert run['head_sha'] == SOURCE and run['run_attempt'] == 1
    jobs = request(base + '/actions/runs/' + str(RUN) + '/jobs?per_page=100')['jobs']
    job, = [item for item in jobs if item['id'] == JOB]
    assert job['status'] == 'completed' and job['conclusion'] == 'success'
    for name in ('Compile GUI and CLI', 'Validate Cocoa main window server navigation',
                 'Deploy native preview', 'Validate relocated native preview', 'Preserve package and deployment evidence'):
        step, = [item for item in job['steps'] if item['name'] == name]
        assert step['status'] == 'completed' and step['conclusion'] == 'success', (name, step['conclusion'])
    artifacts = request(base + '/actions/runs/' + str(RUN) + '/artifacts?per_page=100')['artifacts']
    artifact, = [item for item in artifacts if item['id'] == ARTIFACT]
    assert artifact['name'] == 'macos-preview-X64' and not artifact['expired']
    raw = request(base + '/actions/artifacts/' + str(ARTIFACT) + '/zip', binary=True)
    zip_sha = hashlib.sha256(raw).hexdigest()
    assert artifact['digest'] == 'sha256:' + zip_sha

    folder = root / 'docs/validation/2026-11-07/expiry-r108-macos-package-terminal/macos-x86_64'
    distribution = root / 'dist/macos-preview-20261107-r108-expiry'
    assert not folder.exists() and not distribution.exists()
    folder.mkdir(parents=True)
    distribution.mkdir(parents=True)
    package_zip = distribution / 'macos-preview-X64.zip'
    package_zip.write_bytes(raw)
    helper = runpy.run_path('.cache/verify-client-history-r80-packages.py')
    helper['payload_proof'].__globals__.update(COMMIT=SOURCE, CHECKOUT=checkout)
    files = helper['checked_zip'](raw)
    tar_name = 'package-output/DuktoNext-macos-x86_64-preview.tar.gz'
    payload = files[tar_name]
    package_sha = hashlib.sha256(payload).hexdigest()
    assert files[tar_name + '.sha256'].decode('ascii').split()[0] == package_sha
    package_tar = distribution / 'DuktoNext-macos-x86_64-preview.tar.gz'
    package_tar.write_bytes(payload)
    (distribution / (package_tar.name + '.sha256')).write_bytes(files[tar_name + '.sha256'])
    proof = helper['payload_proof'](payload, 'x86_64')
    runtime = json.loads(files['build/package-runtime.json'])
    assert runtime['passed'] and runtime['runtimeMigrationQualified']
    assert runtime['sourceCommit'] == SOURCE and runtime['architecture'] == 'x86_64'
    assert runtime['verifiedLinks'] == proof['verifiedLinks'] == 71
    assert len(runtime['cases']) == 5
    for case in runtime['cases']:
        name = 'build/package-runtime-' + case['name'] + '.json'
        assert case['passed'] and hashlib.sha256(files[name]).hexdigest() == case['reportSha256']
    navigation = json.loads(files['build/main-window-navigation.json'])
    assert navigation['passed'] and navigation['sourceCommit'] == SOURCE and navigation['nativePlatform'] == 'cocoa'
    for case in navigation['cases']:
        assert case['passed'] and case['exitCode'] == 0
        for frame in case['frames']:
            assert frame['chineseGlyphCoverage']['passed'] and frame['chineseGlyphCoverage']['missingGlyphs'] == 0
            image_name = ('build/main-window-navigation/' + case['name'] + '/Testing/QtTest/main-server-' +
                          'x'.join(str(size) for size in frame['requestedSize']) + '.png')
            assert hashlib.sha256(files[image_name]).hexdigest() == frame['pngSha256']
    runtime_proof = helper['runtime_proof'](files, 'x86_64', folder)
    for key in ('screenshot', 'navigationScreenshot'):
        runtime_proof[key] = Path(runtime_proof[key]).relative_to(root).as_posix()
    log = request(base + '/actions/jobs/' + str(JOB) + '/logs', binary=True)
    (folder / 'job.log').write_bytes(log)
    observation = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': SOURCE,
                   'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
                   'job': {key: job[key] for key in ('id', 'name', 'status', 'conclusion', 'steps')},
                   'artifact': {key: artifact[key] for key in ('id', 'name', 'digest', 'expired')},
                   'artifactSha256': zip_sha, 'packageSha256': package_sha,
                   'jobLogSha256': hashlib.sha256(log).hexdigest()}
    (folder / 'observation.json').write_text(json.dumps(observation, indent=2) + '\n', 'utf-8')
    receipt = dict(observation, package=proof, runtime=runtime_proof,
                   packageRuntimeCases=5, cocoaNavigationAndDpiCasesPassed=True,
                   thisArchitectureDeploymentVerified=True, otherArchitecturePending=True,
                   entireWorkflowQualified=False, releaseQualified=False, deliveryComplete=False)
    (folder / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), folder / 'verification-driver.py')
    print(json.dumps({'architecture': 'x86_64', 'sourceCommit': SOURCE, 'artifactSha256': zip_sha,
                      'packageSha256': package_sha, 'sourceFiles': proof['applicationSourceFiles'],
                      'payloadFiles': proof['verifiedPayloadFiles'], 'runtimeReports': 5,
                      'thisArchitectureDeploymentVerified': True, 'arm64Pending': True,
                      'entireWorkflowQualified': False}), flush=True)


if __name__ == '__main__':
    main()
