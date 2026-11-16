@echo off
cd /d "%~dp0"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "%USERPROFILE%\venvs\conversor\Scripts\python.exe" set "PY=%USERPROFILE%\venvs\conversor\Scripts\python.exe"

if not defined PY (
    echo No virtual environment found. Using Python 3.13 from the system.
    set "PY=py -3.13"
)

%PY% launcher.py
echo.
echo The program has stopped. If there was an error, copy it above.
pause