#!/usr/bin/env python3
"""Build the standalone NCT Console for Windows (x64) from a macOS release's shipped tree.

  python packaging/build_win.py NCT-Console-<version>-tree.zip

The tree archive is written by packaging/build_mac.py and attached to the GitHub release, so the Windows app
ships exactly the files, firmware images and recorded modification times of the Mac app of the same version
(firmware builds are not reproducible byte for byte, and nothing on the Windows runner compiles firmware).
Only packaging/launcher.py and nct_console.spec come from this checkout.

Steps: unpack the tree; PyInstaller (packaging/nct_console.spec) with the Python running this script, which
must have the pinned packages (PACKAGES) installed; check the frozen app (esptool, the modules the console
imports, the firmware checks on the installed tree, a simulated start); zip the app folder to
packaging/dist/NCT-Console-<version>-windows-x64.zip. Unsigned: Windows SmartScreen warns on first start.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build'
DIST = HERE / 'dist'
APP = DIST / 'NCT Console'
EXE = APP / 'NCT Console.exe'
PACKAGES = ['pywebview==6.2.1', 'pythonnet==3.1.0', 'pyserial==3.5', 'esptool==5.3.1', 'pyinstaller==6.22.3']
# Run inside the frozen app (`NCT Console.exe check.py`): everything the console needs at run time imports.
CHECK = r'''
import sys, json
from pathlib import Path
result = {}
for name in ('webview', 'clr', 'tkinter', 'tkinter.messagebox', 'sqlite3', 'ssl', 'serial.tools.list_ports', 'esptool'):
    try:
        __import__(name)
        result[name] = 'ok'
    except Exception as exc:
        result[name] = f'{type(exc).__name__}: {exc}'
Path(sys.argv[1]).write_text(json.dumps(result, indent=1), encoding='utf-8')
'''


def step(title):
    print(f'\n=== {title} ===', flush=True)


def run(args, **kwargs):
    print('$ ' + ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def unpack(archive):
    step('Unpack the shipped tree')
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(BUILD)
    shipped = json.loads((BUILD / 'tree/.shipped.json').read_text(encoding='utf-8'))
    version = re.search(r"CONSOLE_VERSION = '([^']+)'", (BUILD / 'tree/console/state.py').read_text(encoding='utf-8'))[1]
    print(f'Tree build {shipped["build"]}, {len(shipped["files"])} files, console {version}')
    return version


def freeze(version):
    step('Freeze')
    missing = []
    for package in PACKAGES:
        name, _, wanted = package.partition('==')
        try:
            from importlib.metadata import version as installed
            if installed(name) != wanted:
                missing.append(package)
        except Exception:
            missing.append(package)
    if missing:
        raise SystemExit('Install first: pip install ' + ' '.join(missing))
    shutil.rmtree(APP, ignore_errors=True)
    env = dict(os.environ, NCT_STAGE=str(BUILD), NCT_VERSION=version)
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN', '--workpath',
         BUILD / 'pyi', '--distpath', DIST, HERE / 'nct_console.spec'], env=env)


def verify():
    step('Verify')
    tree = APP / '_internal/tree'
    text = subprocess.run([EXE, '-u', tree / 'flashing_station/esptool_entry.py', 'version'], capture_output=True,
                          text=True, timeout=120).stdout
    if '5.3.1' not in text:
        raise SystemExit(f'esptool through the app answered: {text!r}')
    print('esptool 5.3.1 answers through the app.')
    with tempfile.TemporaryDirectory() as folder:
        script, report = Path(folder) / 'check.py', Path(folder) / 'report.json'
        script.write_text(CHECK, encoding='utf-8')
        subprocess.run([EXE, script, report], timeout=120, check=True)
        imports = json.loads(report.read_text(encoding='utf-8'))
    bad = {k: v for k, v in imports.items() if v != 'ok'}
    if bad:
        raise SystemExit(f'Modules missing from the app: {bad}')
    print('The console\'s run-time modules import inside the app: ' + ', '.join(imports))
    # The launcher restores the recorded modification times; check the tree the way the console will.
    check = BUILD / 'verify-tree'
    shutil.rmtree(check, ignore_errors=True)
    sys.path.insert(0, str(HERE))
    import launcher
    launcher.install(tree, check)
    text = subprocess.run([sys.executable, check / 'scripts/build_all_firmware.py', '--stale', '--dry-run'],
                          capture_output=True, text=True, cwd=check).stdout
    stale = [line for line in text.splitlines() if ': ' in line and not line.endswith(': current')
             and not line.startswith(('===', ' ', 'Registration console'))]
    if stale:
        raise SystemExit('Firmware not current inside the app:\n' + '\n'.join(stale))
    print('Every shipped firmware build is current inside the app.')
    simulate()


def simulate():
    """Start the app on fake boards, serving the page on loopback; fetch it; stop."""
    process = subprocess.Popen([EXE, '--simulate', '--browser', '--no-open'], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    url, lines, deadline = None, [], time.monotonic() + 90
    try:
        while time.monotonic() < deadline and process.poll() is None:
            line = process.stdout.readline()
            lines.append(line.rstrip())
            match = re.search(r'NCT Console: (http://127\.0\.0\.1:\d+/)', line)
            if match:
                url = match[1]
                break
        if not url:
            raise SystemExit('Simulated start printed no address:\n' + '\n'.join(lines[-30:]))
        import urllib.request
        page = urllib.request.urlopen(url, timeout=20).read().decode('utf-8', 'replace')
        if '<html' not in page:
            raise SystemExit(f'Simulated console served: {page[:200]!r}')
        print(f'Simulated start serves the console page at {url}')
    finally:
        process.kill()
        process.wait()


def package(version):
    step('Package')
    archive = DIST / f'NCT-Console-{version}-windows-x64.zip'
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(APP.rglob('*')):
            if path.is_file():
                z.write(path, Path('NCT Console') / path.relative_to(APP))
    print(f'Ready: {archive} ({archive.stat().st_size / 1e6:.1f} MB)')


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    if os.name != 'nt':
        raise SystemExit('Windows only (packaging/build_mac.py builds the Mac app)')
    version = unpack(sys.argv[1])
    freeze(version)
    verify()
    package(version)


if __name__ == '__main__':
    main()
