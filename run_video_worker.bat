@echo off
REM Makes the videos the website (Render) queued. Keep this window open while you want videos made.
REM Needs the same DATABASE_URL, SUPABASE_URL and SUPABASE_SERVICE_KEY as Render in this folder's .env
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python cli.py worker
pause
