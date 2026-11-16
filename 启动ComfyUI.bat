@echo off
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
title 二次元手办AI流水线 - ComfyUI 服务
echo ================================================================
echo   启动 ComfyUI (%ROOT%\ComfyUI)
echo ================================================================
echo.
cd /d "%ROOT%\ComfyUI"
echo [*] 使用 venv: %ROOT%\ComfyUI\venv
echo [*] 端口: 8188
echo [*] 启动中... 首次加载模型约需 30-60 秒
echo.
"venv\Scripts\python.exe" main.py --port 8188
pause
