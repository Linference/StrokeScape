@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "web-dist\index.html" (
  echo 尚未构建界面，请先运行 npm install 和 npm run build。
  pause
  exit /b 1
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launch.py --desktop
) else (
  python launch.py --desktop
)
if errorlevel 1 pause
