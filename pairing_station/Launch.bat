@echo off
rem Windows twin of Launch.command. The console stays open so a startup error can be read.
cd /d "%~dp0"
set PYTHONUTF8=1
".venv\Scripts\python.exe" app.py --connect
if errorlevel 1 pause
