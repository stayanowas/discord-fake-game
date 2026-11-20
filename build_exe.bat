@echo off
chcp 65001 >nul
title Orbs — Compilation de l'application
cd /d "%~dp0"

echo.
echo   Compilation de Orbs.exe
echo   =======================
echo.

rem ── Python de compilation ───────────────────────────────────────────
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYTHON=%%i"
)
if not defined PYTHON set "PYTHON=python"

rem ── Environnement isolé ─────────────────────────────────────────────
if not exist ".venv-build\Scripts\python.exe" (
    echo Création de l'environnement de compilation...
    "%PYTHON%" -m venv .venv-build
    if errorlevel 1 goto :error
)
set "BUILD_PY=.venv-build\Scripts\python.exe"

echo Installation des dépendances et de PyInstaller...
"%BUILD_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
if errorlevel 1 goto :error

echo Compilation en cours (1 à 4 minutes)...
"%BUILD_PY%" -m PyInstaller --noconfirm --clean --windowed ^
    --distpath "dist-quests" ^
    --workpath "build-quests" ^
    --name Orbs ^
    --icon "web\assets\orbs.ico" ^
    --add-data "web;web" ^
    --collect-all webview ^
    --hidden-import webview.platforms.edgechromium ^
    --hidden-import webview.platforms.winforms ^
    --hidden-import clr ^
    --hidden-import pypresence ^
    --hidden-import requests ^
    --exclude-module tkinter ^
    --exclude-module customtkinter ^
    main.py
if errorlevel 1 goto :error

copy /Y "README.md" "dist-quests\Orbs\README.md" >nul
copy /Y "LICENSE" "dist-quests\Orbs\LICENSE" >nul

echo.
echo ============================================
echo   Terminé : dist-quests\Orbs\Orbs.exe
echo ============================================
echo Le dossier dist-quests\Orbs est autonome : tu peux le zipper et l'envoyer.
echo (Lance Orbs.exe, pas le dossier.)
echo.
pause
exit /b 0

:error
echo.
echo Échec de la compilation (regarde les messages ci-dessus).
pause
exit /b 1
