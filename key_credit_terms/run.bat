@echo off
rem Populate Key_Credit_Terms_<Client>.docx for every term sheet in the documents folder
rem (or for the term sheets / client names given as arguments).
cd /d "%~dp0"
if exist "..\.venv\Scripts\python.exe" (set "PY=..\.venv\Scripts\python.exe") else (set "PY=python")
"%PY%" populate_key_credit_terms.py %*
pause
