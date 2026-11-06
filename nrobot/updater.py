"""Atualizações pelo GitHub: publicar (cópia git do desenvolvedor) e atualizar (quem baixou).

Atualizar não precisa de git nem de login: lê versao.json do repositório público, baixa o
zip do ramo principal e troca somente os arquivos do bot. Os arquivos do usuário nunca são
tocados (configurações, buffs aprendidos, conexão local, logs, ambiente Python).
Publicar só existe numa cópia git com permissão de envio: roda os testes, aumenta a
versão, registra a lista de arquivos e envia o commit.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT/'atualizacao.json'
VERSION_FILE = ROOT/'versao.json'
# Never replaced or removed by an update: belongs to the person using the bot.
PROTECTED = ('.git', '.venv', 'logs', 'backups', 'perfis', 'data/mapas', 'data/monstros', 'data/database', 'data/jogadores',
             'data/rede/comportamentos_mapas.json', 'data/rede/rcx_config.json', 'data/rede/invocacoes_aprendidas.json', 'data/rede/painel_config.json', 'data/rede/buffs_aprendidos.json',
             'data/rede/rotas_quests.json', 'data/rede/quadros_missoes.json',
             'data/rede/rotas_mapas.json', 'data/rede/missoes_concluidas.json',
             'data/rede/slots_missoes.json', 'data/rede/quest_extras.json',
             'data/rede/progresso_quests.json', 'data/rede/progresso_quests.json.bak', 'data/x1',
             'data/rede/compartilhado_importado.json',
             'data/rede/alvos_importados.json', 'data/rede/personagens')
# Kept in the repository for development, not needed to run the bot.
NOT_DISTRIBUTED = ('AGENTS.md', 'tests', 'tools', 'Arquivos_grf', '.gitignore', '.gitattributes')
TIMEOUT = 30


class UpdateError(Exception):
    pass


def config():
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise UpdateError(f'atualizacao.json ausente ou inválido: {exc}') from exc


def local_version():
    try:
        return json.loads(VERSION_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'version': '0', 'files': []}


def version_key(text):
    return tuple(int(part) if part.isdigit() else 0 for part in str(text).split('.'))


def raw_url(name):
    c = config()
    return f"https://raw.githubusercontent.com/{c['owner']}/{c['repo']}/refs/heads/{c.get('branch', 'main')}/{name}"


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'BOT-NRO-atualizador', 'Cache-Control': 'no-cache'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except OSError as exc:
        raise UpdateError(f'não foi possível acessar o GitHub: {exc}') from exc


def remote_version():
    c = config()
    # Branch-based raw links can lag behind the commit endpoint after a push.
    branch = c.get('branch', 'main')
    try:
        latest = json.loads(fetch(f"https://api.github.com/repos/{c['owner']}/{c['repo']}/commits/{branch}"))
        commit = latest['sha']
        if len(commit) == 40 and all(ch in '0123456789abcdef' for ch in commit):
            url = f"https://raw.githubusercontent.com/{c['owner']}/{c['repo']}/{commit}/versao.json"
            return json.loads(fetch(url))
    except (UpdateError, ValueError, TypeError, KeyError):
        pass
    api = (f"https://api.github.com/repos/{c['owner']}/{c['repo']}/contents/versao.json"
           f"?ref={c.get('branch', 'main')}")
    for url, accept in ((raw_url('versao.json'), '*/*'), (api, 'application/vnd.github.raw')):
        request = urllib.request.Request(url, headers={'User-Agent': 'BOT-NRO-atualizador', 'Accept': accept,
                                                       'Cache-Control': 'no-cache'})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read())
        except ValueError as exc:
            raise UpdateError('versao.json do GitHub é inválido') from exc
        except OSError as exc:
            error = exc
    raise UpdateError(f'não foi possível acessar o GitHub: {error}')


def check():
    """(local, remote, newer) without changing anything."""
    local, remote = local_version(), remote_version()
    return local, remote, version_key(remote['version']) > version_key(local['version'])


def is_protected(relative):
    path = PurePosixPath(relative)
    return any(path == PurePosixPath(p) or PurePosixPath(p) in path.parents for p in PROTECTED)


def distributed(relative):
    path = PurePosixPath(relative)
    if not path.parts or path.is_absolute() or '..' in path.parts or '\\' in relative or ':' in relative:
        return False
    excluded = {name.casefold() for name in NOT_DISTRIBUTED}
    return path.parts[0].casefold() not in excluded and not is_protected(relative)


def local_changes(root):
    """Tracked files changed and not committed, in a git copy (the developer's); [] elsewhere."""
    if not (Path(root)/'.git').exists() or shutil.which('git') is None:
        return []
    result = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        return []
    changed = [line[3:].strip().strip('"') for line in result.stdout.splitlines() if line.strip()]
    return [name for name in changed if distributed(name)]


def backup(root, relatives):
    """Zip of the files an update is about to replace or remove, in backups/ (never touched by updates)."""
    if not relatives:
        return None
    target = Path(root)/'backups'/f"antes-da-atualizacao-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for relative in relatives:
            bundle.write(Path(root)/relative, relative)
    return target


def apply(log=print, root=ROOT, archive=None):
    """Download the latest version and replace the bot files; returns the new version."""
    c = config() if archive is None else {}
    if archive is None:
        log('Baixando a versão nova do GitHub...')
        archive = fetch(f"https://codeload.github.com/{c['owner']}/{c['repo']}/zip/refs/heads/{c.get('branch', 'main')}")
    try:
        bundle = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise UpdateError('o pacote baixado está corrompido') from exc
    names = [n for n in bundle.namelist() if not n.endswith('/')]
    prefix = names[0].split('/', 1)[0]+'/' if names else ''
    files = {name[len(prefix):]: name for name in names if name.startswith(prefix)}
    if 'versao.json' not in files or 'nrobot/session_relay.py' not in files:
        raise UpdateError('o pacote baixado não contém o bot')
    new = json.loads(bundle.read(files['versao.json']))
    try:
        old = json.loads((root/'versao.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        old = {'files': []}
    unpublished = local_changes(root)
    if unpublished:
        raise UpdateError(f'esta cópia tem {len(unpublished)} arquivo(s) alterado(s) ainda não publicado(s) '
                          f'(ex.: {unpublished[0]}); publique primeiro, senão a atualização apagaria essas mudanças')
    requirements_before = (root/'requirements.txt').read_bytes() if (root/'requirements.txt').is_file() else b''
    removed = [relative for relative in old.get('files', [])
               if relative not in files and distributed(relative) and (root/relative).is_file()]
    wanted = [relative for relative in files if distributed(relative)]
    saved = backup(root, [r for r in wanted if (root/r).is_file() and (root/r).read_bytes() != bundle.read(files[r])]+removed)
    if saved:
        log(f'Cópia dos arquivos antigos: {saved.relative_to(root).as_posix()}')
    with tempfile.TemporaryDirectory(dir=root) as staging:
        staging = Path(staging)
        for relative in wanted:  # extract everything first: a failed download changes nothing
            target = staging/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(files[relative]))
        for relative in wanted:
            destination = root/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(staging/relative, destination)
    for relative in removed:  # files that the new version no longer has
        (root/relative).unlink()
    log(f"Arquivos atualizados: {len(wanted)}; removidos: {len(removed)}.")
    try:  # the new version's quests and routes, merged into the user's own
        # With the code just installed: the module loaded in memory is the old version's, which is
        # what refused every import until the panel was opened again.
        import importlib
        from . import shared_data
        importlib.reload(shared_data).merge(root, log)
    except (OSError, ValueError) as exc:
        log(f'Dados compartilhados nao aplicados: {exc}')
    requirements_after = (root/'requirements.txt').read_bytes() if (root/'requirements.txt').is_file() else b''
    if requirements_after != requirements_before and root == ROOT:
        log('Dependências mudaram; instalando...')
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(root/'requirements.txt')],
                                capture_output=True, text=True)
        if result.returncode:
            raise UpdateError('falha ao instalar dependências:\n'+result.stdout[-1500:]+result.stderr[-1500:])
    return new


# -- publishing (developer copy) ------------------------------------------------------
def git(*args, check=True):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and result.returncode:
        raise UpdateError(f"git {' '.join(args)} falhou:\n{(result.stderr or result.stdout).strip()[-1500:]}")
    return result.stdout.strip()


DEVELOPER = ROOT/'perfis'/'desenvolvedor'  # only on the developer's PC: perfis/ is never published


def can_publish():
    """Users get the whole bot on every update but never the means to publish one."""
    if not DEVELOPER.is_dir() or not (ROOT/'.git').is_dir() or shutil.which('git') is None:
        return False
    try:
        return bool(git('remote', 'get-url', 'origin'))
    except UpdateError:
        return False


def next_version(previous):
    today = datetime.now().strftime('%Y.%m.%d')
    parts = str(previous).split('.')
    if '.'.join(parts[:3]) == today and len(parts) == 4 and parts[3].isdigit():
        return f'{today}.{int(parts[3])+1}'
    return f'{today}.1'


def tracked_files():
    listed = git('ls-files', '--cached', '--others', '--exclude-standard', '-z')
    return sorted({name for name in listed.split('\0') if name and name != 'versao.json' and (ROOT/name).is_file()})


def publish(message, log=print, run_tests=True):
    """Test, bump the version, commit everything and push; returns the new version."""
    from . import changelog
    message = (message or '').strip()
    if not message and changelog.pending_items():
        message = 'changelog'
    if not message:
        raise UpdateError('escreva o que mudou nesta atualização (ou preencha a Próxima atualização do CHANGELOG.md)')
    if not can_publish():
        raise UpdateError('esta cópia não é a do desenvolvedor (sem git ou sem repositório de origem)')
    if git('ls-files', '--', 'Arquivos_grf'):
        raise UpdateError('Remova Arquivos_grf do índice Git antes de publicar; mantenha a pasta local.')
    from .monster_db import export_base
    from .release_assets import prepare
    try:
        prepare(log)
    except (OSError, ValueError) as exc:
        raise UpdateError(f'Falha ao preparar os recursos: {exc}') from exc
    export_base(log)  # custom monsters learned here reach every user with this version
    from .shared_data import export as export_shared
    try:
        export_shared(log)  # quests, boards, missions, map routes and portals too
        from .release_assets import validate_quest_maps
        count = validate_quest_maps(ROOT)
        log(f'Percursos de quests: {count} mapas conferidos no pacote portatil.')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UpdateError(f'Pacote de quests incompleto; nada publicado: {exc}') from exc
    if run_tests and (ROOT/'tests').is_dir():
        log('Rodando os testes antes de publicar...')
        result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests'],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            summary = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ''
            if ' passed' in summary and not any(word in summary for word in ('failed', 'error')):
                raise UpdateError(f'os testes passaram ({summary}), mas o processo de testes fechou com erro '
                                  f'(código {result.returncode & 0xffffffff:#x}); nada foi publicado. Tente de novo.\n'
                                  + result.stderr[-1000:])
            raise UpdateError('os testes falharam; nada foi publicado:\n'+result.stdout[-2000:]+result.stderr[-1000:])
        log(result.stdout.strip().splitlines()[-1])
    version = next_version(local_version().get('version'))
    files = [name for name in tracked_files() if distributed(name)]
    digest = hashlib.sha256('\n'.join(files).encode()).hexdigest()[:12]
    VERSION_FILE.write_text(json.dumps({'version': version, 'published_at': datetime.now().isoformat(timespec='seconds'),
                                        'notes': message, 'files': files, 'files_digest': digest},
                                       ensure_ascii=False, indent=1)+'\n', encoding='utf-8')
    previous_changelog = changelog.CHANGELOG.read_bytes() if changelog.CHANGELOG.is_file() else None
    notes = changelog.stamp(version)
    try:
        git('add', '-A')
        git('commit', '-m', f'{version}: {message}')
    except UpdateError:
        if previous_changelog is not None:
            changelog.CHANGELOG.write_bytes(previous_changelog)  # retry keeps the pending topics
        raise
    log('Enviando para o GitHub...')
    git('push', 'origin', 'HEAD')
    changelog.send(version, notes, log)
    return version


def restart_panel():
    """Start a fresh panel; the caller closes the current one."""
    subprocess.Popen([sys.executable, '-m', 'nrobot.packet_panel'], cwd=ROOT,
                     creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Atualizações do BOT NRO pelo GitHub')
    parser.add_argument('action', choices=('check', 'apply', 'publish'))
    parser.add_argument('--message', default='')
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    try:
        if args.action == 'check':
            local, remote, newer = check()
            print(json.dumps({'local': local.get('version'), 'remote': remote.get('version'),
                              'notes': remote.get('notes', ''), 'newer': newer}, ensure_ascii=False))
        elif args.action == 'apply':
            new = apply()
            print(f"Atualizado para a versão {new['version']}.")
        else:
            print(f'Versão {publish(args.message)} publicada no GitHub.')
    except UpdateError as exc:
        print(f'ERRO: {exc}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
