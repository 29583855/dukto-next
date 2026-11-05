param(
    [string]$QtRoot = "$PSScriptRoot/../.tools/Qt/5.15.2/msvc2019_64",
    [string]$BuildDirectory = "$PSScriptRoot/../build/windows",
    [ValidateSet('Debug', 'Release')][string]$Configuration = 'Release',
    [switch]$CoreOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path "$PSScriptRoot/..").Path
$cmakeExe = "$projectRoot/.tools/python/Scripts/cmake.exe"
if (-not (Test-Path -LiteralPath $cmakeExe)) { $cmakeExe = 'cmake' }
$guiOption = if ($CoreOnly) { 'OFF' } else { 'ON' }
& $cmakeExe -S $projectRoot -B $BuildDirectory -G 'Visual Studio 16 2019' -A x64 "-DCMAKE_PREFIX_PATH=$QtRoot" "-DDUKTO_BUILD_GUI=$guiOption"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $cmakeExe --build $BuildDirectory --config $Configuration --parallel 4
exit $LASTEXITCODE
