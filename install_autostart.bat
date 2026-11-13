@echo off
REM Registers run_agent.bat to start automatically when you log in to Windows.
schtasks /create /f /tn "DigitalMarketingAgent" /sc onlogon /rl limited /tr "\"%~dp0run_agent.bat\""
echo.
echo Done. The agent will start every time you log in. Remove with: schtasks /delete /tn DigitalMarketingAgent /f
pause
