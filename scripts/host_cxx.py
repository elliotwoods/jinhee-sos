"""Host C++ toolchain for the firmware simulations (shared by the three run_*test*.py drivers).

macOS/Linux: the system `c++`. Windows: a MinGW-w64 or LLVM `g++`/`clang++` on PATH. Set CXX to override.
"""
import os
import shutil

WINDOWS = os.name == 'nt'
# AddressSanitizer/UBSan ship with clang and gcc on macOS/Linux but not with MinGW.
SANITIZE = [] if WINDOWS else ['-fsanitize=address,undefined']


def compiler():
    for name in filter(None, [os.environ.get('CXX'), 'c++', 'clang++', 'g++']):
        if shutil.which(name):
            return name
    raise SystemExit('No C++17 compiler found. macOS: xcode-select --install; Windows: install MinGW-w64 or LLVM and put g++/clang++ on PATH.')


def executable(path):
    """The output path of a compiled test: Windows only runs it with an .exe suffix."""
    return str(path) + ('.exe' if WINDOWS else '')
