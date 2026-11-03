"""Check imports with the interpreter that will actually run the panel."""
import argparse
import importlib
import sys

MODULES = ('PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'numpy')


def check_runtime():
    for module in MODULES:
        try:
            importlib.import_module(module)
        except (ImportError, OSError) as error:
            raise RuntimeError(f'Dependencia indisponivel: {module}. Python: {sys.executable}. Detalhe: {error}') from error


def check_game():
    from .game_folder import find
    from .packet_reader import configure_client_game, client_lengths
    folder = find()
    if folder is None:
        raise RuntimeError('Pasta do jogo nao encontrada. Execute CONFIGURAR_CONEXAO_LOCAL.bat ou salve a pasta correta no painel.')
    configure_client_game(folder)
    try:
        sizes = client_lengths()
    except (OSError, ValueError) as error:
        raise RuntimeError(str(error)) from error
    if not sizes:
        raise RuntimeError('Tabela de pacotes ausente no pacote do bot. Baixe o pacote completo novamente.')
    print(f'Cliente e tabela de pacotes verificados em {folder}: {len(sizes)} mensagens.')


def main(argv=()):
    parser = argparse.ArgumentParser()
    parser.add_argument('--game', action='store_true')
    args = parser.parse_args(argv)
    try:
        check_runtime()
        if args.game:
            check_game()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f'Dependencias verificadas: {sys.executable}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
