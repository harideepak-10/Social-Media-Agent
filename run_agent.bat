@echo off
REM Starts the Digital Marketing Agent (dashboard + daily scheduler) on this PC.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python cli.py serve --host 127.0.0.1 --port 8000
