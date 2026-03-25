@echo off
chcp 65001 >nul
echo.
echo  正在停止应用服务（保留 Postgres + Redis）...
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0dev-stop.ps1" -KeepDocker
echo.
pause
