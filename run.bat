@echo off
rem Lance Foulee depuis les sources (apres build.bat ou pip install -r requirements.txt)
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (start "" ".venv\Scripts\pythonw.exe" main.py) else (start "" pythonw main.py)
