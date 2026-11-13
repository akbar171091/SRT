@echo off
REM Launch the TS vs CA reconciliation app. Uses the project virtualenv if present.
cd /d "%~dp0"
if exist "..\.venv\Scripts\python.exe" (
  "..\.venv\Scripts\python.exe" -m streamlit run app.py
) else (
  python -m streamlit run app.py
)
