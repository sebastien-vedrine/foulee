@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Foulee - construction de l'installateur

rem ---- 1. Python 3.12 ou plus ------------------------------------------
set "PY="
for /f "delims=" %%i in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
if not defined PY for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable) if sys.version_info>=(3,12) else None" 2^>nul') do set "PY=%%i"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
    echo Python 3.12 introuvable : installation via winget...
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
    echo Python 3.12 toujours introuvable. Relance ce script dans une nouvelle fenetre.
    pause
    exit /b 1
)
echo Python : %PY%

rem ---- 2. Environnement virtuel et dependances ---------------------------
if not exist ".venv\Scripts\python.exe" "%PY%" -m venv .venv || goto :fail
set "VPY=.venv\Scripts\python.exe"
%VPY% -m pip install --upgrade pip || goto :fail
%VPY% -m pip install -r requirements.txt pyinstaller || goto :fail

rem ---- 3. Tests --------------------------------------------------------
%VPY% -m unittest discover -s tests || goto :fail

rem ---- 4. Application (PyInstaller) -----------------------------------
%VPY% -m PyInstaller --noconfirm --clean foulee.spec || goto :fail

rem ---- 5. Version -----------------------------------------------------
for /f "delims=" %%v in ('%VPY% tools\get_version.py') do set "VERSION=%%v"
echo Version : %VERSION%

rem ---- 6. Installateur (Inno Setup 6) ------------------------------------
call :find_iscc
if not defined ISCC (
    echo Inno Setup introuvable : installation via winget...
    winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
    call :find_iscc
)
if not defined ISCC (
    echo Inno Setup toujours introuvable. Installe-le depuis jrsoftware.org puis relance.
    pause
    exit /b 1
)
"%ISCC%" /DMyAppVersion=%VERSION% foulee.iss || goto :fail

echo.
echo Termine : dist\Foulee-Setup-%VERSION%.exe
pause
exit /b 0

:find_iscc
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
exit /b 0

:fail
echo.
echo ECHEC de la construction (voir les messages ci-dessus).
pause
exit /b 1
