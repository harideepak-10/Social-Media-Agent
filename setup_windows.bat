@echo off
REM One-time setup of the Digital Marketing Agent on Windows.
cd /d "%~dp0"
echo.
echo === Digital Marketing Agent setup ===
where python >nul 2>nul || (echo Python not found. Install Python 3.11 or newer from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run this again. & pause & exit /b 1)
if not exist .venv (echo Creating virtual environment... & python -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :err
echo Installing the Chromium browser used for capturing and rendering...
python -m playwright install chromium || goto :err
where ffmpeg >nul 2>nul || (echo Installing ffmpeg... & winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements)
if not exist .env (copy .env.example .env >nul & echo Created .env from .env.example)
where npm >nul 2>nul && (echo Building the React dashboard... & pushd frontend & call npm install --no-fund --no-audit & call npm run build & popd) || echo Node.js not found - using the prebuilt dashboard in frontend\dist (install Node 20+ to rebuild it).
echo.
echo === Setup finished ===
echo 1. Open .env in Notepad and paste your ANTHROPIC_API_KEY, set DASHBOARD_PASSWORD.
echo 2. Run check_agent.bat to test everything.
echo 3. Start the agent with run_agent.bat
pause
exit /b 0
:err
echo.
echo Setup failed - see the error above.
pause
exit /b 1
