@echo off
chcp 65001 >nul
echo.
echo  正在启动应用服务（跳过 Docker）...
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0dev-start.ps1" -SkipDocker
echo.
echo  启动完成，按任意键打开前端页面...
pause >nul
start http://localhost:3000
