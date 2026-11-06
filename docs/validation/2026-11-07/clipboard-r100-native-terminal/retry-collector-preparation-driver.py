"""日期：2026-11-07；派生保留全部原门槛的补跑收验器，显式绑定首轮三平台原件和新Intel附件。"""
import ast
from pathlib import Path


# 日期：2026-11-07；精确替换已知锚点，失败则不写出，防止误删完整业务验收条件。
def main():
    source = Path('.cache/collect-r100-native-terminal.py').read_bytes()
    newline = '\r\n' if b'\r\n' in source else '\n'
    text = source.decode('utf-8').replace('\r\n', '\n')
    replacements = {
        'clipboard-r100-native-terminal': 'clipboard-r100-native-retry-terminal',
        "    assert run['head_sha'] == COMMIT and run['status'] == 'completed'":
        "    assert run['head_sha'] == COMMIT and run['status'] == 'completed' and run['run_attempt'] == 2",
        "    records = []\n    for item in artifacts:": """    original_output = root / 'docs/validation/2026-11-07/clipboard-r100-native-terminal'
    original_path = original_output / 'first-attempt-qualified-subset.json'
    original = json.loads(original_path.read_text('utf-8'))
    initial = json.loads((original_output / 'terminal-artifact-observation.json').read_text('utf-8'))
    retry_path = root / '.cache/r100-intel-upload-retry.json'
    retry = json.loads(retry_path.read_text('utf-8'))
    assert original['verifiedProtocolReports'] == 142 and not original['fullNativeRegressionQualified']
    assert retry['responseReceived'] and retry['originalAttempt'] == 1
    assert retry['firstAttemptPreservedSha256'] == hashlib.sha256(original_path.read_bytes()).hexdigest()
    inherited = []
    for job in jobs:
        first, = [row for row in initial['jobs'] if row['name'] == job['name']]
        if job['name'].startswith('native (macos-15-intel,'):
            assert job['id'] != first['id'] and job['steps'] != first['steps']
            assert all(step.get('started_at', '') >= retry['observedUtc'][:19] + 'Z'
                       for step in job['steps'] if step.get('started_at'))
        else:
            assert first['conclusion'] == 'success' and job['steps'] == first['steps']
            inherited.append({'runnerJobName': job['name'], 'firstAttemptJobId': first['id'],
                              'secondAttemptInheritedJobId': job['id'], 'originalStepTimestampsUnchanged': True})
    assert len(inherited) == 3
    selected = []
    for prefix in ('core-validation-', 'validation-'):
        for runner in ('windows-2022', 'ubuntu-22.04', 'macos-15', 'macos-15-intel'):
            name = prefix + runner
            if runner == 'macos-15-intel':
                candidates = [row for row in artifacts if row['name'] == name
                              and row['created_at'] >= retry['observedUtc'][:19] + 'Z']
            else:
                prior, = [row for row in initial['artifacts'] if row['name'] == name]
                candidates = [row for row in artifacts if row['id'] == prior['id'] and row['name'] == name]
            item, = candidates
            selected.append(item)
    artifacts = selected
    records = []
    for item in artifacts:""",
        "        raw = archive.read_bytes() if archive.exists() else request(\n            base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)":
        """        prior_archive = original_output / archive.name
        prior_ids = {row['id'] for row in initial['artifacts']}
        if archive.exists():
            raw = archive.read_bytes()
        elif item['id'] in prior_ids:
            raw = prior_archive.read_bytes()
        else:
            raw = request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)""",
        "    receipt = dict(observation, qualificationPending=False, cores=cores, protocolSuites=suites,":
        """    receipt = dict(observation, qualificationPending=False, cores=cores, protocolSuites=suites,
                   firstAttemptEvidence=helper['proof'](original_path.relative_to(root)),
                   onlyIntelJobRerun=True, originalSuccessfulJobsInherited=inherited,
                   originalFailureRetained=True,""",
    }
    for old, new in replacements.items():
        assert text.count(old) >= 1, old
        if old != 'clipboard-r100-native-terminal':
            assert text.count(old) == 1, old
        text = text.replace(old, new)
    ast.parse(text)
    output = Path('.cache/collect-r100-native-retry-terminal.py')
    assert not output.exists()
    output.write_bytes(text.replace('\n', newline).encode('utf-8'))
    print('Prepared attempt-2 collector with all original four-platform/188-protocol gates intact')


if __name__ == '__main__':
    main()
