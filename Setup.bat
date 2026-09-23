@echo off
rem Windows twin of Setup.command: creates pairing_station\.venv, installs arduino-cli, the ESP32 core
rem and pinned libraries, then builds stale firmware (setup.py --no-firmware skips the firmware step).
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if %errorlevel%==0 (py -3 scripts\setup.py) else (python scripts\setup.py)
pause
