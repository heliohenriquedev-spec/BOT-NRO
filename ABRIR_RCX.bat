@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Execute instalar.bat antes de abrir o RCX.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m nrobot.rcx_panel
if errorlevel 1 pause
