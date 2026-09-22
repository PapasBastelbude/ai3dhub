@echo off
rem Startet den AI-3D-Hub API Importer per Doppelklick.
rem Zusaetzliche Argumente (z.B. --dry-run) werden durchgereicht.
chcp 65001 >nul
setlocal

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

%PY% "%~dp0api_importer.py" %*
set "RC=%errorlevel%"

echo.
pause
exit /b %RC%
