#!/usr/bin/env python3
"""Build, sign and notarize the standalone NCT Console for macOS (Apple Silicon).

  pairing_station/.venv/bin/python packaging/build_mac.py [--no-notarize] [--skip-firmware] [--resume ID]

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
import time
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


def notary(args, profile):
    """One notarytool call with JSON output; None on a network failure (the caller retries)."""
    result = subprocess.run(['xcrun', 'notarytool', *map(str, args), '--keychain-profile', profile,
                             '--output-format', 'json'], capture_output=True, text=True)
    for text in (result.stdout, result.stderr):   # a timed-out wait reports its JSON on stderr
        try:
            return json.loads(text)
        except ValueError:
            pass
    if 'NSURLErrorDomain' in result.stdout + result.stderr:
        return None
    raise SystemExit(f'notarytool failed: {result.stdout}{result.stderr}')


def notarize(path, profile, submission=None):
    """Submit `path` (unless `submission` is an id already submitted) and wait for Apple's answer. Apple can take
    hours on a team's first submissions; a dropped network connection only pauses the wait."""
    if not submission:
        for attempt in range(5):
            answer = notary(['submit', path], profile)
            if answer:
                break
            print('Network unavailable; retrying the upload in 60 s', flush=True)
            time.sleep(60)
        else:
            raise SystemExit(f'Could not upload {path.name} for notarization')
        submission = answer['id']
    print(f'Notarization of {path.name}: submitted as {submission}; waiting for Apple', flush=True)
    deadline = time.monotonic() + 6 * 3600
    while True:
        answer = notary(['wait', submission, '--timeout', '30m'], profile)
        status = (answer or {}).get('status')
        if status in ('Accepted', 'Invalid', 'Rejected'):
            break
        if time.monotonic() > deadline:
            raise SystemExit(f'Notarization still {status or "unreachable"} after 6 h; resume with --resume {submission}')
        if answer is None:
            print('Network unavailable; still waiting', flush=True)
            time.sleep(60)
    print(f'Notarization of {path.name}: {status}', flush=True)
    if status != 'Accepted':
        run(['xcrun', 'notarytool', 'log', submission, '--keychain-profile', profile])
        raise SystemExit(f'Notarization {status}: {path.name}')


def package(short, profile, resume=None):
    step('Notarize the app')
    archive = BUILD / 'NCT Console.zip'
    if not resume:
        archive.unlink(missing_ok=True)
        run(['ditto', '-c', '-k', '--keepParent', APP, archive])
    notarize(archive, profile, resume)
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
    parser.add_argument('--resume', metavar='ID', help='continue with the app already built in packaging/dist and submitted '
                        'for notarization as ID (after an interrupted run); no rebuild')
    options = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('macOS only')
    sign = not options.no_sign
    if sign and IDENTITY not in output(['security', 'find-identity', '-v', '-p', 'codesigning']):
        raise SystemExit(f'Signing identity not in the keychain: {IDENTITY}')
    short, count = version()
    if options.resume:
        verify(True)
        return package(short, options.profile, options.resume)
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
