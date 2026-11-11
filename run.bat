@echo off
REM Lanza RM Studio IA en Windows. Crea un entorno virtual la primera vez.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw -m rmstudio %*
