@echo off
chcp 65001 >nul 2>&1
title 二次元手办 AI 流水线

echo ================================================================
echo   手办 AI 一键启动
echo ================================================================
echo.

REM ★ 检查 ComfyUI 是否已在运行
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 3 -UseBasicParsing -Proxy $null; if ($r.StatusCode -eq 200) { exit 0 } } catch { exit 1 }" 2>nul
if %errorlevel%==0 (
    echo [*] ComfyUI 已在运行，跳过启动
    goto :open_launcher
)

REM ★ 后台启动 ComfyUI
echo [*] 启动 ComfyUI 服务（E:\AI\ComfyUI）...
echo [*] 端口: 8188  首次加载模型约需 30-60 秒
echo.
start "ComfyUI-Server" /MIN cmd /c "cd /d E:\AI\ComfyUI && venv\Scripts\python.exe main.py --port 8188"

REM ★ 等待服务就绪（最多等 90 秒）
echo [*] 等待服务就绪...
set /a wait_count=0
:wait_loop
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 3 -UseBasicParsing -Proxy $null; if ($r.StatusCode -eq 200) { exit 0 } } catch { exit 1 }" 2>nul
if %errorlevel%==0 goto :ready
set /a wait_count+=3
if %wait_count% geq 90 goto :timeout
echo     等待中... %wait_count%s
timeout /t 3 /nobreak >nul 2>&1
goto :wait_loop

:ready
echo.
echo [✓] ComfyUI 服务已就绪！

:open_launcher
REM ★ 打开可视化启动器
echo [*] 打开操作界面...
start "" "E:\AI\启动器.html"

echo.
echo ================================================================
echo   启动完成！
echo   · 操作界面已在浏览器中打开
echo   · ComfyUI 在后台运行（端口 8188）
echo   · 关闭此窗口不会影响服务
echo ================================================================
echo.
echo 按任意键关闭此窗口...
pause >nul 2>&1
exit /b 0

:timeout
echo.
echo [!] ComfyUI 启动超时（90秒）
echo     可能原因：首次加载模型较慢 / GPU 被占用
echo     请稍后在浏览器打开 E:\AI\启动器.html
echo.
echo 按任意键关闭...
pause >nul 2>&1
exit /b 1
