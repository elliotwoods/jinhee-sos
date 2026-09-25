# PyInstaller recipe for the NCT Console app (macOS .app or Windows folder). Run through packaging/build_mac.py or
# packaging/build_win.py, which pass the staged tree's location in NCT_STAGE. The console's own modules are not frozen: they run from the shipped tree
# (see launcher.py), so only the interpreter, the standard library and third-party packages go in here.
import importlib.util
import json
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

stage = Path(os.environ['NCT_STAGE'])
version = os.environ.get('NCT_VERSION', '0.0.0')
build = os.environ.get('NCT_BUILD', '0')
identity = os.environ.get('NCT_SIGN_IDENTITY') or None   # PyInstaller signs each binary with the hardened runtime
entitlements = os.environ.get('NCT_ENTITLEMENTS') if identity else None
here = Path(SPECPATH)


def importable(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# Names from `from X import y` include attributes (pathlib.Path); only real modules are hidden imports.
hidden = [n for n in json.loads((stage / 'imports.json').read_text(encoding='utf-8')) if importable(n)]
hidden += collect_submodules('esptool') + collect_submodules('serial') + collect_submodules('webview')

MAC = sys.platform == 'darwin'

a = Analysis(
    [str(here / 'launcher.py')],
    hiddenimports=hidden,
    datas=[(str(stage / 'tree'), 'tree'), *collect_data_files('esptool'), *collect_data_files('webview')],
    # Each platform's modules only; pywebview's Windows backend needs pythonnet (clr).
    excludes=['msvcrt', 'winreg', 'winsound', 'pythonnet', 'clr'] if MAC else [],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NCT Console', console=False,
          target_arch='arm64' if MAC else None, codesign_identity=identity, entitlements_file=entitlements)
coll = COLLECT(exe, a.binaries, a.datas, name='NCT Console')
if MAC:
    app = BUNDLE(
        coll,
        name='NCT Console.app',
        icon=None,
        bundle_identifier='com.kimchiandchips.nctconsole',
        version=version,
        info_plist={
            'CFBundleName': 'NCT Console',
            'CFBundleDisplayName': 'NCT Console',
            'CFBundleShortVersionString': version,
            'CFBundleVersion': build,
            'LSMinimumSystemVersion': '13.0',
            'NSHighResolutionCapable': True,
            'LSApplicationCategoryType': 'public.app-category.utilities',
        },
    )
