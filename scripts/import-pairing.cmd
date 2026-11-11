@echo off
chcp 65001 >nul
rem 日期：2026-11-11；使用当前账户打开配对文件导入窗口，结束后保留结果供用户复制路径。
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0import-pairing-windows.ps1" -CredentialFile "%~1"
set "dukto_import_exit=%errorlevel%"
echo.
pause
exit /b %dukto_import_exit%
