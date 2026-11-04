@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" goto preparar
".venv\Scripts\python.exe" -m nrobot.runtime_check >nul 2>nul
if errorlevel 1 goto preparar
goto iniciar

:preparar
echo Preparando ou reparando as dependencias do painel...
call instalar.bat --from-launcher
if errorlevel 1 goto falha

:iniciar
".venv\Scripts\python.exe" -m nrobot.packet_panel
if errorlevel 1 goto falha
exit /b 0

:falha
echo.
echo Nao foi possivel iniciar o bot. Consulte o erro acima e execute instalar.bat novamente.
pause
exit /b 1
