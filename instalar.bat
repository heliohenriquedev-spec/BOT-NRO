@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" goto dependencias

where py >nul 2>nul
if errorlevel 1 goto usar_python
py -3.12 -c "import sys" >nul 2>nul
if errorlevel 1 goto usar_python
py -3.12 -m venv .venv
if errorlevel 1 goto falha
goto dependencias

:usar_python
where python >nul 2>nul
if errorlevel 1 goto sem_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 goto sem_python
python -m venv .venv
if errorlevel 1 goto falha

:dependencias
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 goto ambiente_invalido
".venv\Scripts\python.exe" -m pip --version >nul 2>nul
if not errorlevel 1 goto instalar_pacotes
".venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 goto falha

:instalar_pacotes
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto falha
".venv\Scripts\python.exe" -m nrobot.runtime_check
if errorlevel 1 goto falha
if exist "perfis\relay\instalacao.json" goto concluido
call CONFIGURAR_CONEXAO_LOCAL.bat
if errorlevel 1 goto falha

:concluido
".venv\Scripts\python.exe" -m nrobot.runtime_check --game
if errorlevel 1 goto falha
echo Instalacao concluida. Abra INICIAR_BOT.bat.
exit /b 0

:sem_python
echo Python 3.12 ou superior nao encontrado. Instale pelo site https://www.python.org/downloads/
echo Marque Add python.exe to PATH e execute instalar.bat novamente.
if /i not "%~1"=="--from-launcher" pause
exit /b 1

:ambiente_invalido
echo O ambiente .venv esta invalido ou usa Python antigo. Instale Python 3.12 ou superior.
echo Renomeie a pasta .venv para .venv-antigo e execute instalar.bat para criar um ambiente novo.
if /i not "%~1"=="--from-launcher" pause
exit /b 1

:falha
echo.
echo Instalacao incompleta. O painel nao sera iniciado sem as dependencias.
echo Copie o erro acima. Se o download falhou, confira a conexao e execute instalar.bat novamente.
if /i not "%~1"=="--from-launcher" pause
exit /b 1
