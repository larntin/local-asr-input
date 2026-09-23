@echo off
cd /d %~dp0
start "" pythonw local_asr_input.py
echo Started in background. Log: %~dp0local_asr_input.log  Quit: Ctrl+Alt+F9
timeout /t 3 >nul
