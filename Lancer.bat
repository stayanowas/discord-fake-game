@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "APP_EXE=%~dp0dist-quests\Orbs\Orbs.exe"
if exist "%APP_EXE%" (
    start "" "%APP_EXE%"
    exit /b 0
)

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY=%~dp0.venv\Scripts\python.exe"
    set "PYW=%~dp0.venv\Scripts\pythonw.exe"
    set "PYARGS="
    set "PYWARGS="
    goto check_python
)

where py >nul 2>&1
if not errorlevel 1 (
    set "PY=py"
    set "PYARGS=-3"
    where pyw >nul 2>&1
    if not errorlevel 1 (
        set "PYW=pyw"
    ) else (
        set "PYW=py"
    )
    set "PYWARGS=-3"
    goto check_python
)

where python >nul 2>&1
if errorlevel 1 goto no_python
set "PY=python"
set "PYARGS="
where pythonw >nul 2>&1
if not errorlevel 1 (
    set "PYW=pythonw"
) else (
    set "PYW=python"
)
set "PYWARGS="
goto check_python

:no_python
echo Python 3 n'est pas installe. Installe-le puis lance Installer.bat.
pause
exit /b 1

:check_python
"%PY%" %PYARGS% -c "import webview, pypresence, requests" >nul 2>&1
if errorlevel 1 (
    call "%~dp0Installer.bat" /silent
    if errorlevel 1 exit /b 1
    set "PY=%~dp0.venv\Scripts\python.exe"
    set "PYW=%~dp0.venv\Scripts\pythonw.exe"
    set "PYARGS="
    set "PYWARGS="
)
start "" "%PYW%" %PYWARGS% "%~dp0main.py"
exit /b 0
