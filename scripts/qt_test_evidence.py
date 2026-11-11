"""日期：2026-11-09；交叉核对Qt文本行计数与新旧JUnit，保留数据行折叠和注释内跳过。"""

from pathlib import Path
import re
import xml.etree.ElementTree as ET


# 日期：2026-11-09；旧Qt把跳过写为注释，甚至放在result=pass的数据函数内，不能忽略。
def inspect_qt_report(xml_bytes, log_bytes):
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    suite = ET.fromstring(xml_bytes, parser=parser)
    if suite.tag != 'testsuite':
        raise ValueError('Qt report is not a testsuite')
    cases = suite.findall('testcase')
    if int(suite.get('tests', '-1')) != len(cases):
        raise ValueError('Qt JUnit case count mismatch')
    failures = []
    skips = []
    for case in cases:
        name = case.get('name', '')
        if case.find('failure') is not None or case.find('error') is not None:
            failures.append(name)
        for item in case.iter():
            if item.tag == 'skipped':
                skips.append(name)
            elif item.tag is ET.Comment and re.search(r'\btype\s*=\s*["\']skip["\']', item.text or ''):
                skips.append(name)
    log = log_bytes.decode('utf-8-sig', errors='replace')
    totals = re.findall(r'^Totals:\s+(\d+) passed, (\d+) failed, (\d+) skipped, '
                        r'(\d+) blacklisted,', log, flags=re.MULTILINE)
    if len(totals) != 1:
        raise ValueError('Qt text report must contain one complete total')
    passed_rows, failed_rows, skipped_rows, blacklisted_rows = map(int, totals[0])
    if bool(failed_rows) != bool(failures) or skipped_rows != len(skips):
        raise ValueError('Qt text and JUnit outcomes disagree')
    return {'junitCases': len(cases), 'passedRows': passed_rows,
            'failedRows': failed_rows, 'skippedRows': skipped_rows,
            'blacklistedRows': blacklisted_rows, 'failures': failures, 'skips': skips,
            'passed': failed_rows == 0 and skipped_rows == 0 and blacklisted_rows == 0}


# 日期：2026-11-09；完整核心逐原件检查，缺失/不完整报告单独记录，不把旧JUnit条目数当作实际数据行数。
def collect_qt_reports(directory, expected_reports=35):
    directory = Path(directory)
    records = []
    errors = []
    for xml in sorted(directory.glob('*.xml')):
        try:
            item = inspect_qt_report(xml.read_bytes(), xml.with_suffix('.log').read_bytes())
            records.append({'report': xml.name, **item})
        except (ValueError, OSError, ET.ParseError) as error:
            errors.append({'report': xml.name, 'reason': str(error)})
    return {'reports': len(records), 'expectedReports': expected_reports,
            'junitCases': sum(item['junitCases'] for item in records),
            'passedRows': sum(item['passedRows'] for item in records),
            'failedRows': sum(item['failedRows'] for item in records),
            'skippedRows': sum(item['skippedRows'] for item in records),
            'blacklistedRows': sum(item['blacklistedRows'] for item in records),
            'records': records, 'errors': errors,
            'passed': len(records) == expected_reports and not errors
                      and all(item['passed'] for item in records)}
