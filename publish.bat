@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Foulee - publication sur GitHub

rem Cree le depot GitHub "foulee" sur ton compte, pousse le code, puis pousse
rem le tag de version : GitHub Actions construit alors l'installateur Windows
rem et le publie dans une release (detectee ensuite par Vedware).

rem ---- 1. Outils : Git et GitHub CLI -------------------------------------
where git >nul 2>&1 || (
    echo Installation de Git via winget...
    winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
    set "PATH=%PATH%;%ProgramFiles%\Git\cmd"
)
where gh >nul 2>&1 || (
    echo Installation de GitHub CLI via winget...
    winget install -e --id GitHub.cli --accept-package-agreements --accept-source-agreements
    set "PATH=%PATH%;%ProgramFiles%\GitHub CLI"
)
where git >nul 2>&1 || goto :need_restart
where gh >nul 2>&1 || goto :need_restart

rem ---- 2. Connexion GitHub (droit "workflow" requis pour pousser la CI) ---
gh auth status >nul 2>&1 || gh auth login --hostname github.com --git-protocol https --web --scopes workflow || goto :fail
gh auth status 2>&1 | findstr /i "workflow" >nul || gh auth refresh --hostname github.com --scopes workflow || goto :fail
gh auth setup-git || goto :fail
set "GHUSER="
for /f "delims=" %%u in ('gh api user --jq .login') do set "GHUSER=%%u"
if not defined GHUSER goto :fail
echo Compte GitHub : %GHUSER%

rem ---- 3. Version et depot local ----------------------------------------
set "PYX="
if exist ".venv\Scripts\python.exe" set "PYX=.venv\Scripts\python.exe"
if not defined PYX (
    where py >nul 2>&1 && set "PYX=py -3"
)
if not defined PYX set "PYX=python"
set "VERSION="
for /f "delims=" %%v in ('%PYX% tools\get_version.py') do set "VERSION=%%v"
if not defined VERSION goto :fail
echo Version : %VERSION%

if not exist ".git" (
    git init -b main || goto :fail
)
git config user.name >nul 2>&1 || git config user.name "%GHUSER%"
git config user.email >nul 2>&1 || git config user.email "%GHUSER%@users.noreply.github.com"
git add -A || goto :fail
git diff --cached --quiet || git commit -m "Foulee %VERSION%" || goto :fail

rem ---- 4. Depot GitHub (public : Vedware lit les releases sans jeton) -----
gh repo view "%GHUSER%/foulee" >nul 2>&1
if errorlevel 1 (
    gh repo create foulee --public --description "Foulee - assistant de course a pied alimente par Garmin" --source . --remote origin || goto :fail
) else (
    git remote get-url origin >nul 2>&1 || git remote add origin "https://github.com/%GHUSER%/foulee.git"
)
git push -u origin main || goto :fail

rem ---- 5. Tag de version : declenche la construction de l'installateur ---
git rev-parse "v%VERSION%" >nul 2>&1 || git tag "v%VERSION%" || goto :fail
git push origin "v%VERSION%" || goto :fail

rem ---- 6. Suivi de la construction (5 a 10 minutes) ----------------------
echo.
echo Construction de l'installateur sur GitHub Actions...
timeout /t 15 /nobreak >nul
set "RUN="
for /f "delims=" %%r in ('gh run list --workflow release.yml --limit 1 --json databaseId --jq ".[0].databaseId"') do set "RUN=%%r"
if defined RUN (
    gh run watch %RUN% --exit-status || goto :ci_fail
)
gh release view "v%VERSION%" --repo "%GHUSER%/foulee" >nul 2>&1 || goto :ci_fail
echo.
echo Release publiee : https://github.com/%GHUSER%/foulee/releases/tag/v%VERSION%
echo URL a ajouter dans Vedware : https://github.com/%GHUSER%/foulee
pause
exit /b 0

:ci_fail
echo.
echo La construction n'a pas abouti. Journal : https://github.com/%GHUSER%/foulee/actions
pause
exit /b 1

:need_restart
echo.
echo Git ou GitHub CLI vient d'etre installe : ferme cette fenetre et relance publish.bat.
pause
exit /b 1

:fail
echo.
echo ECHEC de la publication (voir les messages ci-dessus).
pause
exit /b 1
