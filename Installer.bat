@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo Orbs - installation des dependances

if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 goto error
)

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto error

echo Installation terminee. Lance Orbs avec Lancer.bat.
if /i not "%1"=="/silent" pause
exit /b 0

:error
echo Echec de l'installation. Verifie ta connexion Internet puis reessaie.
pause
exit /b 1
