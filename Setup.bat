@echo off
rem Windows twin of Setup.command: creates pairing_station\.venv and checks the cube firmware.
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if %errorlevel%==0 (py -3 scripts\setup.py) else (python scripts\setup.py)
pause
