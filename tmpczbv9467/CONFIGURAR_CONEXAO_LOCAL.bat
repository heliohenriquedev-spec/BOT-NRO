@echo off
cd /d "%~dp0"
echo Adiciona ao jogo a entrada de servidor "NRO - BOT LOCAL" que passa pelo bot.
echo Os arquivos originais ficam guardados em backups\ e RESTAURAR_CONEXAO_ORIGINAL.bat desfaz.
".venv\Scripts\python.exe" -m nrobot.relay_profile install
pause
