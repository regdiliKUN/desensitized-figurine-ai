@echo off
start "" "%~dp0ComfyUI\venv\Scripts\pythonw.exe" "%~dp0control_server.py" --completion
exit /b
