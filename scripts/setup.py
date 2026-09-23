#!/usr/bin/env python3
"""Prepare the portable Python environment, the firmware toolchain and every firmware build.

Steps: Python venv and pinned packages, bundled cube firmware check, inventory sync, then (unless
--no-firmware) Arduino CLI, ESP32 core 3.3.11, the pinned Arduino libraries (docs/SETUP.md §6) and a
build of every firmware target that is missing or older than its source. Nothing is uploaded.
A toolchain or build failure is reported but does not fail setup: flashing the bundled cube
firmware needs none of it.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT/'pairing_station/.venv'
sys.path.insert(0, str(ROOT/'pairing_station'))
import hostos  # noqa: E402  (stdlib only)

CORE = '3.3.11'
ESP32_INDEX = 'https://espressif.github.io/arduino-esp32/package_esp32_index.json'
# Arduino sketchbook ("user") directory → pinned libraries installed under its libraries/ folder.
# The build scripts pass these folders with --libraries; the global sketchbook is never changed.
LIBRARIES = {
    'live-libs.json': (ROOT/'live files',
                       ['Adafruit NeoPixel@1.15.5', 'Adafruit PN532@1.3.4', 'Adafruit BusIO@1.17.4', 'VL53L4CD@1.0.0']),
    'station-libs.json': (ROOT/'pairing_station/.arduino',
                          ['Adafruit PN532@1.3.4', 'Adafruit BusIO@1.17.4', 'ArduinoJson@7.4.3']),
}


def python_env():
    if sys.version_info < (3,11):
        raise SystemExit('Python 3.11 or newer is required.')
    try:
        import tkinter  # noqa: F401
    except ImportError:
        raise SystemExit('Tk is missing. macOS Homebrew: install matching python-tk; Ubuntu: apt install python3-tk; Windows: select Tcl/Tk in the Python installer.')
    python = hostos.venv_python(ENV)
    if not python.exists():venv.EnvBuilder(with_pip=True).create(ENV)
    subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'flashing_station/requirements.txt')],check=True)
    subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'console/requirements.txt')],check=True)
    subprocess.run([str(python),'-c',"import sys; sys.path.insert(0, 'flashing_station'); from core import load_manifest; m=load_manifest(); print('Firmware ready:',m['version'],m['build_hash'][:12])"],cwd=ROOT,check=True)
    subprocess.run([str(python), str(ROOT/'scripts/sync_inventory.py')], check=True)
    return python


def install_cli():
    """arduino-cli from the platform package manager when neither it nor Arduino IDE 2 is present."""
    cli = hostos.arduino_cli()
    if cli:
        return cli
    if hostos.WINDOWS and shutil.which('winget'):
        print('Installing Arduino CLI (winget)...', flush=True)
        subprocess.run(['winget', 'install', '--id', 'ArduinoSA.CLI', '-e', '--accept-source-agreements',
                        '--accept-package-agreements', '--disable-interactivity'], check=False)
    elif hostos.MAC and shutil.which('brew'):
        print('Installing Arduino CLI (Homebrew)...', flush=True)
        subprocess.run(['brew', 'install', 'arduino-cli'], check=False)
    cli = hostos.arduino_cli()
    if not cli:
        raise RuntimeError('arduino-cli not found and could not be installed; install Arduino IDE 2 or arduino-cli (docs/SETUP.md §6)')
    return cli


def install_core(cli):
    if hostos.esp32_core(CORE).is_dir():
        print(f'ESP32 core {CORE}: installed', flush=True)
        return
    print(f'Installing ESP32 core {CORE} (large download)...', flush=True)
    subprocess.run([cli, 'core', 'update-index', '--additional-urls', ESP32_INDEX], check=True)
    subprocess.run([cli, 'core', 'install', f'esp32:esp32@{CORE}', '--additional-urls', ESP32_INDEX], check=True)
    if not hostos.esp32_core(CORE).is_dir():
        raise RuntimeError(f'ESP32 core {CORE} did not appear at {hostos.esp32_core(CORE)}')


def installed_version(user, library):
    properties = user/'libraries'/library.replace(' ', '_')/'library.properties'
    try:
        text = properties.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    return next((line.split('=', 1)[1].strip() for line in text.splitlines() if line.startswith('version=')), None)


def install_libraries(cli):
    config_dir = ROOT/'pairing_station/.arduino'
    config_dir.mkdir(parents=True, exist_ok=True)
    indexed = False
    for filename, (user, pinned) in LIBRARIES.items():
        # Machine-local (gitignored): rewritten so a copied checkout never points at another computer.
        config = config_dir/filename
        config.write_text(json.dumps({'directories': {'user': str(user)}}), encoding='utf-8')
        missing = [spec for spec in pinned if installed_version(user, spec.split('@')[0]) != spec.split('@')[1]]
        if not missing:
            print(f'Arduino libraries in {user.relative_to(ROOT)}: current', flush=True)
            continue
        if not indexed:
            subprocess.run([cli, '--config-file', str(config), 'lib', 'update-index'], check=True)
            indexed = True
        print(f'Installing {", ".join(missing)} into {user.relative_to(ROOT)}...', flush=True)
        subprocess.run([cli, '--config-file', str(config), 'lib', 'install', *missing], check=True)


def firmware(python):
    if hostos.WINDOWS:
        # ESP32 builds create very long object paths (docs/SETUP.md §2b).
        subprocess.run(['git', 'config', 'core.longpaths', 'true'], cwd=ROOT, check=False)
    cli = install_cli()
    print(f'Arduino CLI: {cli}', flush=True)
    install_core(cli)
    install_libraries(cli)
    result = subprocess.run([str(python), str(ROOT/'scripts/build_all_firmware.py'), '--stale'], cwd=ROOT)
    if result.returncode:
        raise RuntimeError('some firmware targets failed to build (see FAIL lines above)')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--no-firmware', action='store_true',
                        help='Skip the Arduino toolchain and firmware builds (flashing the bundled cube firmware still works)')
    options = parser.parse_args()
    python = python_env()
    if not options.no_firmware:
        try:
            firmware(python)
        except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
            print(f'\nWARNING: firmware toolchain/builds incomplete: {exc}\n'
                  'Apps and bundled cube flashing work; rerun setup to retry. See docs/SETUP.md §6.', file=sys.stderr)
    print('Ready. Run: '+str(python)+' '+str(ROOT/'flashing_station/app.py'))

if __name__=='__main__':main()
