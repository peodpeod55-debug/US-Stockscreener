@echo off
cd /d "%~dp0"
:loop
python -m bot.main
echo bot exited with code %errorlevel%, restarting in 60s...
timeout /t 60 /nobreak >nul
goto loop
