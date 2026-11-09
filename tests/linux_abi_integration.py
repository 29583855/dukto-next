"""日期：2026-11-09；检查ELF需求与导出节区分、加载器能力及真实ELF的独立工具交叉核对。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from package_linux import glibc_abi, required_glibc, version_tuple


# 日期：2026-11-09；需求节与定义节交错，不能因包内库导出较新标签而抬高客户的最低版本。
def parser_cases():
    text = """Version definition section '.gnu.version_d' contains 1 entry:
  0x001c: Rev: 1 Flags: none Index: 2 Cnt: 1 Name: GLIBC_2.99
Version needs section '.gnu.version_r' contains 1 entry:
  0x0000: Version: 1 File: libc.so.6 Cnt: 4
  0x0010: Name: GLIBC_2.9 Flags: none Version: 3
  0x0020: Name: GLIBC_2.35 Flags: none Version: 4
  0x0030: Name: GLIBC_2.2.5 Flags: none Version: 5
  0x0040: Name: GLIBC_ABI_DT_RELR Flags: none Version: 6
Version definition section '.gnu.version_d' contains 1 entry:
  0x001c: Rev: 1 Flags: none Index: 2 Cnt: 1 Name: GLIBC_PRIVATE
"""
    value = required_glibc(text)
    assert value == {'versions': ['2.2.5', '2.9', '2.35'], 'features': {'GLIBC_ABI_DT_RELR': '2.36'}}, value
    assert version_tuple('2.9') < version_tuple('2.35')
    rejected = []
    for name in ['GLIBC_PRIVATE', 'GLIBC_ABI_FUTURE', 'GLIBC_2.bad']:
        try:
            required_glibc("Version needs section '.gnu.version_r' contains 1 entry:\n  Name: " + name)
        except RuntimeError:
            rejected.append(name)
        else:
            raise AssertionError('Unknown required glibc ABI accepted: ' + name)
    for name in ['2.35x', '-2.35', '2.35.1.1']:
        try:
            version_tuple(name)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid version accepted: ' + name)
    return {'definitionsExcluded': True, 'numericOrderingVerified': True, 'loaderFeatureMinimum': value['features'],
            'unsupportedRequirementsRejected': rejected, 'malformedVersionsRejected': True}


# 日期：2026-11-09；同一真实ELF分别用readelf需求节和objdump未定义符号交叉核对，不仅测试文本样本。
def native_case():
    assert sys.platform.startswith('linux'), 'Native ELF validation requires Linux; parser-only must be explicit'
    source = Path(shutil.which('true')).resolve(strict=True)
    assert source.read_bytes()[:4] == b'\x7fELF', source
    with tempfile.TemporaryDirectory(prefix='dukto-glibc-abi-') as temporary:
        stage = Path(temporary)
        shutil.copyfile(source, stage/'probe')
        value = glibc_abi(stage, {'probe'})
        result = subprocess.run(['env', 'LC_ALL=C', 'objdump', '-T', str(source)],
                                check=True, capture_output=True, text=True, timeout=30)
        versions = set()
        for line in result.stdout.splitlines():
            if '*UND*' in line:
                versions.update(re.findall(r'\(GLIBC_(\d+\.\d+(?:\.\d+)?)\)', line))
        assert versions and set(value['requiredVersions']) == versions, (versions, value)
        assert len(value['elfFiles']) == 1 and value['elfFiles'][0]['path'] == 'probe'
        host = subprocess.check_output(['getconf', 'GNU_LIBC_VERSION'], text=True).strip()
        assert version_tuple(value['minimumVersion']) <= version_tuple(host.split()[1])
        return {'binarySha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'hostGlibc': host,
                'objdumpUndefinedVersions': sorted(versions, key=version_tuple), 'observedAbi': value,
                'nativeElfVerified': True}


# 日期：2026-11-09；Windows可显式只验解析边界，原生资格仅在实际Linux工具与ELF均核对后取得。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    parser.add_argument('--parser-only', action='store_true')
    args = parser.parse_args()
    report = {'date': '2026-11-09', 'parserCases': parser_cases(), 'nativeElfVerified': False,
              'scope': 'parser boundary cases only' if args.parser_only else 'parser and native ELF ABI cross-check'}
    if not args.parser_only:
        report.update(native_case())
    report['passed'] = True
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
