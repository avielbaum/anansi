@echo off
rem One-step volunteer setup for Windows. Usage: node\join.bat --gateway URL --token TOKEN [--dry-run]
rem Makes a private Python environment in %USERPROFILE%\.anansi-venv (httpx only), then runs node\join.py.
setlocal
set "VENV=%USERPROFILE%\.anansi-venv"
where python >nul 2>&1 || (echo Python 3.10 or newer is required: https://www.python.org/downloads/ & exit /b 2)
if not exist "%VENV%\Scripts\python.exe" (
  python -m venv "%VENV%" || exit /b 2
  "%VENV%\Scripts\pip" install --quiet httpx || exit /b 2
)
"%VENV%\Scripts\python" "%~dp0join.py" %*
