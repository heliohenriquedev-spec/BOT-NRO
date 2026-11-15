"""Rebuild the numeric skill catalog from the configured NRO client, without executing Lua."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nrobot.grf import GrfSet
from nrobot.lua_tables import tables


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game_dir')
    args = parser.parse_args()
    grfs = GrfSet(args.game_dir)
    ids = tables(grfs.read(r'data\lua files\skillinfoz\skillid.lub'))['SKID']
    codes = {str(value): key for key, value in ids.items() if isinstance(value, int)}
    target = Path(__file__).resolve().parents[1]/'data/recursos/habilidades_ids.json'
    target.write_text(json.dumps(codes, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'{len(codes)} habilidades mapeadas.')
