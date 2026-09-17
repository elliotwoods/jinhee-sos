"""Launch pinned esptool from our project environment, independent of GUI launch context."""
from pathlib import Path
import site
import sys

packages = Path(__file__).resolve().parent.parent / 'pairing_station' / '.venv' / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
# macOS framework/GUI launchers need not preserve the virtualenv in child processes.
# Put the intended environment first and process its .pth files explicitly.
sys.path.insert(0, str(packages))
site.addsitedir(str(packages))

if __name__ == '__main__':
    try:
        import esptool
        if esptool.__version__ != '5.3.1':
            raise RuntimeError(f'Expected esptool 5.3.1; found {esptool.__version__}')
        esptool.main(sys.argv[1:])
    except Exception as exc:
        print(f'Flashing tool error: {exc}', file=sys.stderr, flush=True)
        raise SystemExit(1)
