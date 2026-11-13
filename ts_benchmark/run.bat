@echo off
rem Start the term sheet benchmark front end. Extra arguments are passed to run.py.
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python run.py %*
) else (
  py -3 run.py %*
)
if errorlevel 1 pause
