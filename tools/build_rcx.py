"""Build the isolated x86 renderer; end users need only the bundled DLL and manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--zig', required=True)
    args = parser.parse_args()
    source = ROOT/'nrobot/native/rcx.c'
    tag = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    destination = ROOT/'data/recursos/rcx'
    destination.mkdir(parents=True, exist_ok=True)
    dll = destination/f'nro_rcx_{tag}.dll'
    subprocess.run([args.zig, 'cc', '-target', 'x86-windows-gnu', '-shared', '-O2', '-std=c11',
                    '-DRCX_BUILD_TAG='+tag, str(source), '-o', str(dll), '-luser32', '-lkernel32'], check=True)
    manifest = dict(version=1, build=tag, dll=dll.name, sha256=hashlib.sha256(dll.read_bytes()).hexdigest(),
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), architecture='x86', entry='Run@16')
    (destination/'renderer.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    (destination/'.gitignore').write_text('*.pdb\n*.lib\n*.dll\n!'+dll.name+'\n', encoding='utf-8')
    print(dll)


if __name__ == '__main__':
    main()
