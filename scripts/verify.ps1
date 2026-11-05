param([string]$BuildDirectory = "$PSScriptRoot/../build/windows", [string]$Configuration = 'Release', [switch]$Ucrt)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path "$PSScriptRoot/..").Path
# 日期：2026-11-05；显式选择独立构建布局和运行依赖，避免现代 UCRT 验证误加载早期 MSVC DLL。
if ($Ucrt) {
    if (-not $PSBoundParameters.ContainsKey('BuildDirectory')) { $BuildDirectory = "$projectRoot/build/windows-ucrt" }
    $binaryDirectory = $BuildDirectory
    $runtimePath = "$projectRoot/.tools/msys64/ucrt64/bin"
    $opensslExe = "$runtimePath/openssl.exe"
}
else {
    $binaryDirectory = "$BuildDirectory/$Configuration"
    $runtimePath = "$projectRoot/.tools/Qt/5.15.2/msvc2019_64/bin;$projectRoot/.tools/openssl/Library/bin"
    $opensslExe = "$projectRoot/.tools/openssl/Library/bin/openssl.exe"
}
$env:PATH = "$runtimePath;$env:PATH"
$env:QT_QPA_FONTDIR = "$env:WINDIR/Fonts"
$pythonExe = "$projectRoot/.tools/python/Scripts/python.exe"
$ctestExe = "$projectRoot/.tools/python/Scripts/ctest.exe"
$reportDirectory = "$projectRoot/docs/validation/$(Get-Date -Format yyyy-MM-dd)"
if ($Ucrt) { $reportDirectory = "$reportDirectory/windows-ucrt" }
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
& $ctestExe --test-dir $BuildDirectory -C $Configuration --output-on-failure --output-log "$reportDirectory/core-ctest.log"
$testExitCode = $LASTEXITCODE
Copy-Item -LiteralPath "$BuildDirectory/Testing/Temporary/LastTest.log" -Destination "$reportDirectory/qt-test-details.log" -Force
# 日期：2026-11-04；失败时也保存逐测试日志，并从 UTF-8 XML 展示错误，避免空标准输出掩盖原因。
Get-ChildItem -LiteralPath "$BuildDirectory/Testing/QtTest" -File | Copy-Item -Destination $reportDirectory -Force
if ($testExitCode -ne 0) {
    foreach ($log in Get-ChildItem -LiteralPath "$BuildDirectory/Testing/QtTest" -Filter '*.xml') {
        [xml]$testReport = Get-Content -LiteralPath $log.FullName -Encoding UTF8 -Raw
        foreach ($failure in $testReport.SelectNodes('//failure')) {
            Write-Host "$($log.Name): $($failure.message) $($failure.InnerText)"
        }
    }
    exit $testExitCode
}
# 日期：2026-11-05；源码快照先按摘要校验再刷新构建输入时间，避免后续 Linux 增量混用旧对象。
& $pythonExe -X utf8 "$projectRoot/tests/source_snapshot_integration.py" --report "$reportDirectory/source-snapshot.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# 日期：2026-11-05；短命进程资源采样必须保留活动进程错误和内存上限。
& $pythonExe -X utf8 "$projectRoot/tests/process_sampling_integration.py" --report "$reportDirectory/process-sampling.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
foreach ($test in @('conflict_fail_integration', 'legacy_integration', 'cli_contracts', 'crash_integration', 'windows_path_integration', 'windows_signal_integration', 'service_integration', 'client_list_integration', 'credential_rotation_integration', 'session_expiry_integration', 'task_admission_integration', 'transfer_retry_integration', 'transfer_integration', 'transfer_recovery_integration', 'parallel_transfer_integration', 'parallel_isolation_integration', 'byte_progress_integration', 'transfer_faults_integration', 'final_ack_integration')) {
    & $pythonExe -X utf8 "$projectRoot/tests/$test.py" "$binaryDirectory/dukto-cli.exe" --report "$reportDirectory/$test.json"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $pythonExe -X utf8 "$projectRoot/tests/final_ack_integration.py" "$binaryDirectory/dukto-cli.exe" --auto-retries 3 --report "$reportDirectory/final-ack-auto-retry.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# 日期：2026-11-05；同一队列另验纯下载及上传/下载混合，避免仅上传覆盖而遗漏另一方向。
foreach ($admissionMode in @('download', 'mixed')) {
    & $pythonExe -X utf8 "$projectRoot/tests/task_admission_integration.py" "$binaryDirectory/dukto-cli.exe" --mode $admissionMode --report "$reportDirectory/task-admission-$admissionMode.json"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
# 日期：2026-11-05；独立 GUI 面板进程中途退出后，生产 QML 按钮必须找回同任务并复用已同步块。
& $pythonExe -X utf8 "$projectRoot/tests/gui_process_recovery_integration.py" "$binaryDirectory/dukto-cli.exe" "$binaryDirectory/server-panel-process-probe.exe" --report "$reportDirectory/gui-process-recovery.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# 日期：2026-11-05；多文件中途暂停后改变并发数，防止只测顺序传输而漏掉关闭阶段心跳回归。
& $pythonExe -X utf8 "$projectRoot/tests/transfer_recovery_integration.py" "$binaryDirectory/dukto-cli.exe" --threads 4 --resume-threads 8 --files 4 --payload-mib 8 --checkpoint-percent 50 --report "$reportDirectory/parallel-files-recovery.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# 日期：2026-11-05；显式失败策略跨暂停/进程退出/服务重启恢复时不得退回默认重命名。
& $pythonExe -X utf8 "$projectRoot/tests/transfer_recovery_integration.py" "$binaryDirectory/dukto-cli.exe" --on-conflict fail --threads 4 --resume-threads 8 --files 4 --payload-mib 8 --checkpoint-percent 50 --report "$reportDirectory/conflict-fail-recovery.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonExe -X utf8 "$projectRoot/tests/secure_channel_integration.py" "$binaryDirectory/secure-channel-probe.exe" --openssl $opensslExe --report "$reportDirectory/secure-channel.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonExe -X utf8 "$projectRoot/tests/task_store_integration.py" "$binaryDirectory/task-store-probe.exe" --report "$reportDirectory/task-store-processes.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonExe -X utf8 "$projectRoot/scripts/audit.py" --report "$reportDirectory/source-audit.json"
exit $LASTEXITCODE
