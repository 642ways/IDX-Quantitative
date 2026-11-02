@echo off
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
    python -m pip install --target .venv\Lib\site-packages -r requirements.txt
)
.venv\Scripts\python.exe run.py
rem Exit code 106 means the .venv launcher couldn't start on this PC
if %errorlevel%==106 python run.py
