"""Every difference between macOS, Windows and Linux hosts, in one place.

macOS is the bench-tested platform; its behaviour here is what the apps always did. The Windows
branches are exercised by tests/test_hostos.py (through a fake msvcrt) and by the Windows CI job.
"""
import functools
import getpass
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WINDOWS = os.name == 'nt'
MAC = sys.platform == 'darwin'

MONO_FONT = 'Menlo' if MAC else 'Consolas' if WINDOWS else 'DejaVu Sans Mono'


def lock_file(handle, blocking=False):
    """Exclusive lock on an open sidecar .lock file, held until the handle closes.

    Raises BlockingIOError when another process owns it (unless blocking). Only ever used on files
    nobody reads, so it does not matter that Windows locks are mandatory where flock is advisory.
    """
    if not WINDOWS:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    import msvcrt
    while True:
        try:
            handle.seek(0)  # the locked byte range starts at the file position
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if not blocking:
                raise BlockingIOError('lock is held by another process') from None
            time.sleep(.05)  # msvcrt's own blocking mode gives up after ten seconds


def lock_dir():
    return Path(tempfile.gettempdir())


def user_tag():
    return str(os.getuid()) if hasattr(os, 'getuid') else getpass.getuser()


def canonical_port(port):
    """One name per physical port: macOS lists each twice (cu./tty.), Windows ignores case."""
    if WINDOWS:
        return port.replace('\\\\.\\', '').upper()
    return port.replace('/tty.', '/cu.')


def private_file(target):
    """Owner-only (0600) for a path or descriptor. Windows has no mode bits: the file keeps the
    ACL of its folder, which is inside the user's own profile or checkout."""
    if WINDOWS:
        return
    if isinstance(target, int):
        os.fchmod(target, 0o600)
    else:
        os.chmod(target, 0o600)


def detached_kwargs():
    """Popen arguments for a sibling app that must outlive this one (and its console)."""
    if WINDOWS:
        return dict(creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    return dict(start_new_session=True)


def quiet_kwargs():
    """Popen arguments for a piped helper tool: no console window flashing up on Windows."""
    return dict(creationflags=subprocess.CREATE_NO_WINDOW) if WINDOWS else {}


def wheel_units(event):
    """Tk <MouseWheel> delta as scroll units: macOS reports lines, Windows multiples of 120."""
    return int(event.delta) if MAC else int(event.delta / 120)


def venv_python(env):
    return Path(env) / ('Scripts/python.exe' if WINDOWS else 'bin/python')


def venv_site_packages(env):
    if WINDOWS:
        return Path(env) / 'Lib' / 'site-packages'
    return Path(env) / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'


def arduino_data_dir():
    if MAC:
        return Path.home() / 'Library/Arduino15'
    if WINDOWS:
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'Arduino15'
    return Path.home() / '.arduino15'


def esp32_core(version='3.3.11'):
    return arduino_data_dir() / 'packages/esp32/hardware/esp32' / version


def arduino_cli():
    """The CLI bundled with Arduino IDE 2 when installed, else arduino-cli on PATH, else None."""
    bundled = 'resources/app/lib/backend/resources/arduino-cli'
    if MAC:
        candidates = [Path('/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli')]
    elif WINDOWS:
        roots = [Path(os.environ[name]) / folder for name, folder in
                 (('LOCALAPPDATA', 'Programs/Arduino IDE'), ('ProgramFiles', 'Arduino IDE')) if os.environ.get(name)]
        candidates = [root / (bundled + '.exe') for root in roots]
    else:
        candidates = []
    return next((str(path) for path in candidates if path.exists()), None) or shutil.which('arduino-cli')


# The esptool that ESP32 core 3.3.11 builds with (build manifests record it); setup pins the same
# version in pairing_station/.venv.
ESPTOOL_VERSION = '5.3.1'


def venv_esptool(env):
    return Path(env) / ('Scripts/esptool.exe' if WINDOWS else 'bin/esptool')


@functools.lru_cache(maxsize=None)
def _esptool_version(tool):
    try:
        done = subprocess.run([tool, 'version'], capture_output=True, text=True, encoding='utf-8', errors='replace',
                              timeout=60, **quiet_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None
    words = done.stdout.split()
    return words[-1] if done.returncode == 0 and words else None


def arduino_build_args(env=None, version=ESPTOOL_VERSION):
    """Extra `arduino-cli compile` arguments every firmware build passes (before the sketch path).

    The ESP32 core runs its esptool three times per build (bootloader image, app image, merged
    image), even when nothing needs compiling. The core's esptool is a one-file bundle that unpacks
    itself into a new temporary folder on every run, which the OS malware scanner then inspects:
    about 10 s per run on the bench Mac, so ~30 s of a 35 s no-change rebuild. The esptool already in
    pairing_station/.venv is the same release and writes byte-identical images, so point the core's
    build recipes at it when it reports exactly `version`; otherwise leave the core's own tool.
    The folder stays the same between builds, so it does not invalidate a build path's cache.
    """
    tool = venv_esptool(Path(env) if env else Path(__file__).resolve().parent / '.venv')
    if tool.is_file() and _esptool_version(str(tool)) == version:
        return ['--build-property', f'tools.esptool_py.path={tool.parent}']
    return []


def same_folder(a, b):
    """True when two paths name one existing folder, whatever their case or 8.3 spelling."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def webview2_available():
    """Can pywebview open a native window here? macOS ships WKWebView; Windows needs the WebView2
    runtime (Edge), detected from its registry `pv` version; Linux is out of scope (browser mode)."""
    if MAC:
        return True
    if not WINDOWS:
        return False
    try:
        import winreg
    except ImportError:
        return False
    client = 'Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\WOW6432Node\\' + client),
                      (winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\' + client),
                      (winreg.HKEY_CURRENT_USER, 'SOFTWARE\\' + client)):
        try:
            with winreg.OpenKey(hive, key) as handle:
                version, _ = winreg.QueryValueEx(handle, 'pv')
                if version and version != '0.0.0.0':
                    return True
        except OSError:
            continue
    return False
