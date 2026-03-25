@echo off
chcp 65001 >nul
echo.
echo  正在停止全部服务...
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0dev-stop.ps1"
echo.
pause
