param(
    [string]$ToolchainRoot = "$PSScriptRoot/../.tools/msys64/ucrt64",
    [string]$BuildDirectory = "$PSScriptRoot/../build/windows-ucrt",
    [ValidateSet('Debug', 'Release')][string]$Configuration = 'Release',
    [switch]$CoreOnly
)

# 日期：2026-11-05；现代 Windows Qt5 使用独立 UCRT 工具链，显式固定编译器和 OpenSSL 以免混入 MSVC 库。
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path "$PSScriptRoot/..").Path
$toolchain = (Resolve-Path -LiteralPath $ToolchainRoot).Path
$previousPath = $env:PATH
$guiOption = if ($CoreOnly) { 'OFF' } else { 'ON' }
try {
    $env:PATH = "$toolchain/bin;$previousPath"
    & "$toolchain/bin/cmake.exe" -S $projectRoot -B $BuildDirectory -G Ninja `
        "-DCMAKE_BUILD_TYPE=$Configuration" "-DCMAKE_PREFIX_PATH=$toolchain" `
        "-DCMAKE_CXX_COMPILER=$toolchain/bin/g++.exe" "-DCMAKE_MAKE_PROGRAM=$toolchain/bin/ninja.exe" `
        "-DOPENSSL_ROOT_DIR=$toolchain" '-DOPENSSL_USE_STATIC_LIBS=OFF' "-DDUKTO_BUILD_GUI=$guiOption"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & "$toolchain/bin/cmake.exe" --build $BuildDirectory --parallel 4
    exit $LASTEXITCODE
}
finally {
    $env:PATH = $previousPath
}
