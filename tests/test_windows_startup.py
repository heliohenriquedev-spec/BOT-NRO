"""Exercise the real Windows launch/install scripts without downloading packages."""
import os
from pathlib import Path
import subprocess
import sys
import venv

import pytest
from nrobot import runtime_check

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def sandbox(tmp_path):
    if os.name!='nt':pytest.skip('Windows batch scripts')
    folder=tmp_path/'pasta com espacos'
    folder.mkdir()
    venv.EnvBuilder(with_pip=False).create(folder/'.venv')
    (folder/'nrobot').mkdir()
    (folder/'nrobot/__init__.py').write_text('')
    (folder/'nrobot/runtime_check.py').write_text("from pathlib import Path\nraise SystemExit(0 if Path('ready').exists() else 1)\n")
    (folder/'nrobot/packet_panel.py').write_text("from pathlib import Path\nPath('panel_started').write_text('ok')\n")
    (folder/'INICIAR_BOT.bat').write_bytes((ROOT/'INICIAR_BOT.bat').read_bytes())
    return folder


def run(folder,command):
    return subprocess.run(['cmd.exe','/d','/c',command],cwd=folder,input='\n',capture_output=True,text=True,timeout=30)


def test_complete_environment_starts_without_running_installer(sandbox):
    (sandbox/'ready').touch()
    (sandbox/'instalar.bat').write_text('@echo off\necho called>installer_called\nexit /b 9\n')
    result=run(sandbox,'INICIAR_BOT.bat')
    assert result.returncode==0,result.stdout+result.stderr
    assert (sandbox/'panel_started').exists() and not (sandbox/'installer_called').exists()


def test_existing_incomplete_venv_is_repaired_before_starting(sandbox):
    (sandbox/'instalar.bat').write_text('@echo off\necho called>installer_called\necho ok>ready\nexit /b 0\n')
    result=run(sandbox,'INICIAR_BOT.bat')
    assert result.returncode==0,result.stdout+result.stderr
    assert (sandbox/'panel_started').exists() and (sandbox/'installer_called').exists()


def test_failed_installation_never_launches_panel(sandbox):
    (sandbox/'instalar.bat').write_text('@echo off\nexit /b 7\n')
    result=run(sandbox,'INICIAR_BOT.bat')
    assert result.returncode==1
    assert not (sandbox/'panel_started').exists()


def prepare_installer(folder,success):
    (folder/'instalar.bat').write_bytes((ROOT/'instalar.bat').read_bytes())
    (folder/'requirements.txt').write_text('example')
    (folder/'pip').mkdir()
    (folder/'pip/__init__.py').write_text('')
    (folder/'pip/__main__.py').write_text("import sys\nfrom pathlib import Path\n"
        "if '--version' in sys.argv: raise SystemExit(0)\n"
        +( "Path('ready').touch()\nraise SystemExit(0)\n" if success else "print('SIMULATED INSTALL FAILURE')\nraise SystemExit(7)\n"))
    (folder/'CONFIGURAR_CONEXAO_LOCAL.bat').write_text('@echo off\necho ok>game_configured\nexit /b 0\n')


def test_real_installer_aborts_before_game_configuration_when_pip_fails(sandbox):
    prepare_installer(sandbox,False)
    result=run(sandbox,'instalar.bat --from-launcher')
    assert result.returncode==1 and 'SIMULATED INSTALL FAILURE' in result.stdout
    assert not (sandbox/'game_configured').exists()


def test_real_installer_verifies_imports_then_configures_game(sandbox):
    prepare_installer(sandbox,True)
    result=run(sandbox,'instalar.bat --from-launcher')
    assert result.returncode==0,result.stdout+result.stderr
    assert (sandbox/'game_configured').exists() and (sandbox/'ready').exists()


def test_runtime_check_reports_missing_qt_with_actual_interpreter(monkeypatch,capsys):
    def missing(module):raise ModuleNotFoundError("No module named 'PySide6'")
    monkeypatch.setattr(runtime_check.importlib,'import_module',missing)
    assert runtime_check.main()==1
    err=capsys.readouterr().err
    assert 'PySide6.QtCore' in err and sys.executable in err


def test_runtime_check_handles_dll_import_error(monkeypatch,capsys):
    def missing(module):raise OSError('DLL load failed')
    monkeypatch.setattr(runtime_check.importlib,'import_module',missing)
    assert runtime_check.main()==1 and 'DLL load failed' in capsys.readouterr().err
