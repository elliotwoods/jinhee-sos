"""Entry point of the packaged NCT Console (PyInstaller); not used from a checkout.

The console and the modules it reuses find their files and write their data relative to their own
source files (paths.ROOT and friends), exactly as in a checkout. The app therefore ships the needed
part of the repository as a read-only tree (Resources/tree, written by packaging/stage.py) and runs it
from a writable copy in the user's application-data folder:

  <data>/runtime/                  the copied tree; pairing_station/data etc. are created here
  <data>/runtime/.shipped.json     what the last copy wrote, so an update removes files it no longer ships

Files the app never ships (databases, passwords, flash runs, backups) are never touched by an update.

Second role: the console runs esptool as `[sys.executable, '-u', esptool_entry.py, ...]`. In the app
sys.executable is this launcher, so a first argument naming a .py file runs that script instead.
"""
import json
import os
import runpy
import shutil
import sys
from pathlib import Path

APP = 'NCT Console'


def resources():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'tree'


def data_dir():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / APP
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / APP
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / APP


def run_script(args):
    """esptool (and any other `python script.py` the console starts) inside the app."""
    script = Path(args[0])
    sys.argv = [str(script), *args[1:]]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name='__main__')


def install(source, target):
    """Make `target` hold the shipped tree. Cheap when the build id is unchanged."""
    shipped = json.loads((source / '.shipped.json').read_text(encoding='utf-8'))
    record = target / '.shipped.json'
    try:
        previous = json.loads(record.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = dict(build=None, files=[])
    if previous.get('build') == shipped['build'] and all((target / f).is_file() for f in shipped['files']):
        return False
    target.mkdir(parents=True, exist_ok=True)
    keep = set(shipped['files'])
    for relative in previous.get('files', []):
        if relative not in keep:
            (target / relative).unlink(missing_ok=True)
    for relative in shipped['files']:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
        # The repository's modification times (the bundle's are the packaging time): the console compares some
        # firmware builds with their sources by time.
        mtime = shipped['mtimes'][relative]
        os.utime(destination, (mtime, mtime))
    record.write_text(json.dumps(shipped, indent=1), encoding='utf-8', newline='\n')
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-psn_')]   # Finder's process serial number
    while args and args[0] in ('-u', '-B', '-E', '-s'):             # interpreter flags from subprocess callers
        args.pop(0)
    if args and args[0].endswith('.py'):
        return run_script(args)
    runtime = data_dir() / 'runtime'
    install(resources(), runtime)
    os.environ['NCT_PACKAGED'] = '1'
    console = runtime / 'console'
    os.chdir(console)
    sys.path.insert(0, str(console))
    sys.argv = [str(console / 'app.py'), *args]
    runpy.run_path(str(console / 'app.py'), run_name='__main__')


if __name__ == '__main__':
    main()
