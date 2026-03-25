@echo off
chcp 65001 >nul
echo.
echo  正在启动全部服务（Docker + 后端 + 前端）...
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0dev-start.ps1"
echo.
echo  启动完成，按任意键打开前端页面...
pause >nul
start http://localhost:3000
