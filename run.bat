@echo off
title Claude Token Monitor
echo ========================================
echo  Claude Token Monitor – Desktop Widget
echo ========================================
echo.
echo Starting…  (minimise this window, don't close it)
echo.

REM Use the system Python 3.13
set PYTHON=C:\Users\%USERNAME%\AppData\Local\Microsoft\WindowsApps\python3.13.exe

REM Fallback: just 'python' if the above doesn't exist
if not exist "%PYTHON%" set PYTHON=python

REM Install/update dependencies silently
"%PYTHON%" -m pip install -r requirements.txt --quiet 2>nul

REM Launch the app
"%PYTHON%" -m app.main

pause
