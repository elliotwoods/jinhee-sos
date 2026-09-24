#!/usr/bin/env python3
"""Build, sign and notarize the standalone NCT Console for macOS (Apple Silicon).

  pairing_station/.venv/bin/python packaging/build_mac.py [--no-notarize] [--skip-firmware]

Steps, each refusing to continue on failure:
  1. firmware   every maintained build current (scripts/build_all_firmware.py --stale compiles what is not;
                it never uploads). --skip-firmware only checks.
  2. stage      packaging/stage.py: the shipped tree and the modules it imports
  3. freeze     PyInstaller (packaging/nct_console.spec) in packaging/.venv, signing every binary with the
                Developer ID identity, hardened runtime and packaging/entitlements.plist
  4. verify     codesign --verify --deep --strict, esptool through the app, firmware checks from the app's tree
  5. notarize   app, then staple; disk image (app + Applications link), sign, notarize, staple
Output: packaging/dist/NCT Console.app and packaging/dist/NCT-Console-<version>.dmg

Needs, on this Mac only (never in git): the "Developer ID Application" identity in the login keychain and a
notarytool keychain profile (default name `notary`, created with `xcrun notarytool store-credentials`).
packaging/.venv is created on first run from Homebrew Python 3.14 with the pinned packages below.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = HERE / 'build'
DIST = HERE / 'dist'
VENV = HERE / '.venv'
APP = DIST / 'NCT Console.app'
PYTHON = '/opt/homebrew/opt/python@3.14/bin/python3.14'
PACKAGES = ['pywebview==6.2.1', 'pyserial==3.5', 'esptool==5.3.1', 'pyinstaller==6.22.3']
IDENTITY = 'Developer ID Application: Hyunjeong Son (439VPD8YRZ)'
# Built by build_all_firmware.py but not shipped (the console does not flash it).
NOT_SHIPPED = {'Registration console'}


def step(title):
    print(f'\n=== {title} ===', flush=True)


def run(args, **kwargs):
    print('$ ' + ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def output(args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, capture_output=True, text=True, encoding='utf-8',
                          **kwargs).stdout


def version():
    text = (ROOT / 'console/state.py').read_text(encoding='utf-8')
    short = re.search(r"CONSOLE_VERSION = '([^']+)'", text)[1]
    count = output(['git', 'rev-list', '--count', 'HEAD'], cwd=ROOT).strip()
    return short, count


def firmware_problems(root):
    """Names of build_all_firmware targets that are not current in `root` (a checkout or the shipped tree)."""
    text = output([sys.executable, root / 'scripts/build_all_firmware.py', '--stale', '--dry-run'], cwd=root)
    problems = {}
    for line in text.splitlines():
        name, _, state = line.partition(': ')
        if state and state != 'current' and not line.startswith(('===', ' ')) and name not in NOT_SHIPPED:
            problems[name] = state
    return problems


def firmware(skip):
    step('Firmware')
    problems = firmware_problems(ROOT)
    if problems and not skip:
        print('Out of date: ' + ', '.join(problems) + '. Compiling (no uploads).', flush=True)
        run([sys.executable, ROOT / 'scripts/build_all_firmware.py', '--stale'], cwd=ROOT)
        problems = firmware_problems(ROOT)
    if problems:
        raise SystemExit('Firmware not current: ' + '; '.join(f'{k}: {v}' for k, v in problems.items()))
    print('Every shipped firmware build is current.')


def venv():
    python = VENV / 'bin/python'
    if not python.exists():
        step('Packaging environment')
        run([PYTHON, '-m', 'venv', VENV])
        run([python, '-m', 'pip', 'install', '--quiet', '--upgrade', 'pip'])
    installed = output([python, '-m', 'pip', 'freeze']).lower().splitlines()
    missing = [p for p in PACKAGES if p.lower() not in installed]
    if missing:
        run([python, '-m', 'pip', 'install', '--quiet', *missing])
    return python


def freeze(python, short, count, sign):
    step('Stage')
    run([sys.executable, HERE / 'stage.py', BUILD])
    step('Freeze and sign')
    env = dict(os.environ, NCT_STAGE=str(BUILD), NCT_VERSION=short, NCT_BUILD=count,
               NCT_SIGN_IDENTITY=IDENTITY if sign else '', NCT_ENTITLEMENTS=str(HERE / 'entitlements.plist'))
    shutil.rmtree(APP, ignore_errors=True)
    run([python, '-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN', '--workpath', BUILD / 'pyi',
         '--distpath', DIST, HERE / 'nct_console.spec'], env=env)


def verify(sign):
    step('Verify')
    if sign:
        run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', APP])
        detail = subprocess.run(['codesign', '-dvv', APP], capture_output=True, text=True).stderr
        for needed in (f'Authority={IDENTITY}', 'flags=0x10000(runtime)', 'Timestamp='):
            if needed not in detail:
                raise SystemExit(f'App signature lacks {needed!r}:\n{detail}')
    binary = APP / 'Contents/MacOS/NCT Console'
    tree = APP / 'Contents/Resources/tree'
    text = output([binary, '-u', tree / 'flashing_station/esptool_entry.py', 'version'])
    if '5.3.1' not in text:
        raise SystemExit(f'esptool through the app answered: {text!r}')
    print('esptool 5.3.1 answers through the app.')
    # The launcher restores the repository's modification times; check the tree the way the console will.
    check = BUILD / 'verify-tree'
    shutil.rmtree(check, ignore_errors=True)
    sys.path.insert(0, str(HERE))
    import launcher
    launcher.install(tree, check)
    problems = firmware_problems(check)
    if problems:
        raise SystemExit('Firmware not current inside the app: ' + '; '.join(f'{k}: {v}' for k, v in problems.items()))
    shutil.rmtree(check)
    print('Every shipped firmware build is current inside the app.')


def notarize(path, profile):
    result = subprocess.run(['xcrun', 'notarytool', 'submit', path, '--keychain-profile', profile, '--wait',
                             '--timeout', '3h', '--output-format', 'json'], capture_output=True, text=True)
    try:
        submission = json.loads(result.stdout)
    except ValueError:
        raise SystemExit(f'notarytool failed: {result.stdout}{result.stderr}')
    print(f'Notarization of {path.name}: {submission.get("status")} ({submission.get("id")})', flush=True)
    if submission.get('status') != 'Accepted':
        if submission.get('id'):
            run(['xcrun', 'notarytool', 'log', submission['id'], '--keychain-profile', profile])
        raise SystemExit(f'Notarization {submission.get("status")}: {path.name}')


def package(short, profile):
    step('Notarize the app')
    archive = BUILD / 'NCT Console.zip'
    archive.unlink(missing_ok=True)
    run(['ditto', '-c', '-k', '--keepParent', APP, archive])
    notarize(archive, profile)
    run(['xcrun', 'stapler', 'staple', APP])
    step('Disk image')
    image = DIST / f'NCT-Console-{short}.dmg'
    folder = BUILD / 'dmg'
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    run(['ditto', APP, folder / APP.name])
    (folder / 'Applications').symlink_to('/Applications')
    image.unlink(missing_ok=True)
    run(['hdiutil', 'create', '-volname', f'NCT Console {short}', '-srcfolder', folder, '-fs', 'HFS+',
         '-format', 'UDZO', '-ov', image])
    run(['codesign', '--force', '--timestamp', '-s', IDENTITY, image])
    notarize(image, profile)
    run(['xcrun', 'stapler', 'staple', image])
    run(['spctl', '--assess', '--type', 'execute', '--verbose=2', APP])
    run(['spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature', '--verbose=2', image])
    print(f'\nReady: {image}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--skip-firmware', action='store_true', help='only check that firmware builds are current')
    parser.add_argument('--no-sign', action='store_true', help='unsigned test build (implies --no-notarize)')
    parser.add_argument('--no-notarize', action='store_true', help='sign but do not notarize or make the disk image')
    parser.add_argument('--profile', default='notary', help='notarytool keychain profile (default: notary)')
    options = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('macOS only')
    sign = not options.no_sign
    if sign and IDENTITY not in output(['security', 'find-identity', '-v', '-p', 'codesigning']):
        raise SystemExit(f'Signing identity not in the keychain: {IDENTITY}')
    short, count = version()
    firmware(options.skip_firmware)
    python = venv()
    freeze(python, short, count, sign)
    verify(sign)
    if sign and not options.no_notarize:
        package(short, options.profile)
    else:
        print(f'\nBuilt {APP} (not notarized).')


if __name__ == '__main__':
    main()
