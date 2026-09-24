"""Stage the part of the repository the packaged NCT Console runs from.

  python packaging/stage.py OUT

Writes OUT/tree (the files) and OUT/tree/.shipped.json (build id, file list and modification times, read by
packaging/launcher.py), plus OUT/imports.json: every module the shipped Python imports that is
not itself shipped, so PyInstaller bundles the standard-library and third-party modules the tree needs even
though it never sees the tree's own modules (they run from source, see launcher.py).

What ships: the source files Git knows about (tracked, or new and not ignored) under FOLDERS, minus tests and
documents, plus each firmware build's flashable images and manifest (build folders are ignored by Git).
Never: databases, passwords, flash runs and backups, logs, compiler caches.
"""
import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ['console', 'pairing_station', 'flashing_station', 'zones', 'rangetest', 'poolzone_test', 'shows', 'docs',
           'scripts']
SKIP_PARTS = {'tests', '__pycache__', '.venv', '.arduino', 'data', 'node_modules'}
SKIP_PREFIXES = ('console/docs/', 'console/tools/')
SKIP_SUFFIXES = {'.pdf', '.sqlite3', '.log', '.curl', '.p12', '.p8', '.zip'}
# Firmware outputs: folders ignored by Git, so listed here. Only the images the flashers read.
BUILDS = ['flashing_station/build', 'pairing_station/build', 'rangetest/build', 'poolzone_test/build',
          *[f'zones/build/{p.name}' for p in sorted((ROOT/'zones/build').iterdir())
                                         if p.is_dir()]]
IMAGE_SUFFIXES = ('.ino.bin', '.ino.bootloader.bin', '.ino.partitions.bin', '.ino.merged.bin')
BUILD_NAMES = {'boot_app0.bin', 'manifest.json', 'pool_build_opt.h'}


def source_files():
    listed = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', *FOLDERS],
                            cwd=ROOT, check=True, capture_output=True).stdout.decode('utf-8').split('\0')
    for relative in filter(None, listed):
        path = Path(relative)
        if SKIP_PARTS & set(path.parts[:-1]) or relative.startswith(SKIP_PREFIXES) or path.suffix in SKIP_SUFFIXES:
            continue
        if (ROOT/relative).is_file():
            yield relative


def build_files():
    for folder in BUILDS:
        for path in sorted((ROOT/folder).glob('*')) if (ROOT/folder).is_dir() else ():
            if path.is_file() and (path.name in BUILD_NAMES or path.name.endswith(IMAGE_SUFFIXES)):
                yield path.relative_to(ROOT).as_posix()


def imports(tree, files):
    """Top-level module names imported anywhere in the shipped Python (absolute imports only)."""
    names = set()
    for relative in files:
        if not relative.endswith('.py'):
            continue
        try:
            module = ast.parse((tree/relative).read_bytes(), relative)
        except SyntaxError as exc:
            raise SystemExit(f'{relative}: {exc}')
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                # `from tkinter import messagebox` imports a submodule; nct_console.spec keeps only real ones.
                names.add(node.module)
                names.update(f'{node.module}.{alias.name}' for alias in node.names if alias.name != '*')
    shipped = {Path(f).stem for f in files if f.endswith('.py')} | {Path(f).parent.name for f in files}
    return sorted(n for n in names if n.split('.')[0] not in shipped)


def main(out):
    out = Path(out).resolve()
    tree = out/'tree'
    if tree.exists():
        shutil.rmtree(tree)
    files = sorted(set(source_files()) | set(build_files()))
    digest = hashlib.sha256()
    for relative in files:
        destination = tree/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/relative, destination)
        digest.update(f'{relative}\0{(ROOT/relative).stat().st_mtime}\0'.encode('utf-8') + (ROOT/relative).read_bytes())
    build = digest.hexdigest()[:16]
    # PyInstaller does not keep modification times when it copies the tree into the app; the launcher restores
    # these, because the console judges some firmware builds by comparing their times with their sources'.
    mtimes = {relative: (ROOT/relative).stat().st_mtime for relative in files}
    (tree/'.shipped.json').write_text(json.dumps(dict(build=build, files=files, mtimes=mtimes), indent=1),
                                      encoding='utf-8', newline='\n')
    (out/'imports.json').write_text(json.dumps(imports(tree, files), indent=1), encoding='utf-8', newline='\n')
    size = sum((tree/f).stat().st_size for f in files)
    print(f'Staged {len(files)} files ({size/1e6:.1f} MB), build {build}, into {tree}')
    return build


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
