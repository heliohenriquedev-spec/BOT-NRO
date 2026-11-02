@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" call instalar.bat
".venv\Scripts\python.exe" -m nrobot.packet_panel
if errorlevel 1 pause
