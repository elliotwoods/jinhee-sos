#!/usr/bin/env python3
"""Prepare the portable Python environment and verify the bundled cube firmware."""
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT/'pairing_station/.venv'

def main():
    if sys.version_info < (3,11):
        raise SystemExit('Python 3.11 or newer is required.')
    try:
        import tkinter
    except ImportError:
        raise SystemExit('Tk is missing. macOS Homebrew: install matching python-tk; Ubuntu: apt install python3-tk; Windows: select Tcl/Tk in the Python installer.')
    python = ENV/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():venv.EnvBuilder(with_pip=True).create(ENV)
    subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'flashing_station/requirements.txt')],check=True)
    subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'console/requirements.txt')],check=True)
    subprocess.run([str(python),'-c',"import sys; sys.path.insert(0, 'flashing_station'); from core import load_manifest; m=load_manifest(); print('Firmware ready:',m['version'],m['build_hash'][:12])"],cwd=ROOT,check=True)
    subprocess.run([str(python), str(ROOT/'scripts/sync_inventory.py')], check=True)
    print('Ready. Run: '+str(python)+' '+str(ROOT/'flashing_station/app.py'))

if __name__=='__main__':main()
