@echo off
cd /d "%~dp0"
:loop
python -m bot.main
set code=%errorlevel%
if "%code%"=="3" (
    echo another bot instance already holds the lock - this launcher exits
    exit /b 3
)
if "%code%"=="0" (
    echo bot stopped normally ^(exit 0, e.g. missing BOT_TOKEN^) - not restarting
    exit /b 0
)
echo bot exited with code %code%, restarting in 60s...
timeout /t 60 /nobreak >nul
goto loop
