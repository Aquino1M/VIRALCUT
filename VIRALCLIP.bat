@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==============================================
echo        ViralClip Studio V4.2 - Local Worker
echo ==============================================

set "PY_CMD="
py -3.12 -V >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3.12"
if defined PY_CMD goto :run
py -3.11 -V >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3.11"
if defined PY_CMD goto :run
py -3.10 -V >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3.10"
if defined PY_CMD goto :run
python -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" >nul 2>nul
if not errorlevel 1 set "PY_CMD=python"
if defined PY_CMD goto :run
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) else 1)" >nul 2>nul
  if not errorlevel 1 set PY_CMD="%LocalAppData%\Programs\Python\Python312\python.exe"
)
if defined PY_CMD goto :run

echo Python 3.10-3.12 nao encontrado. Tentando instalar Python 3.12...
where winget >nul 2>nul
if errorlevel 1 goto :python_missing
winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements --silent
if errorlevel 1 goto :python_missing
goto :detect_after_install

:detect_after_install
set "PY_CMD="
py -3.12 -V >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3.12"
if defined PY_CMD goto :run
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set PY_CMD="%LocalAppData%\Programs\Python\Python312\python.exe"
if defined PY_CMD goto :run
echo.
echo Python foi instalado, mas o executavel ainda nao ficou visivel nesta sessao.
echo Feche esta janela e execute VIRALCLIP.bat novamente.
pause
exit /b 2

:run
%PY_CMD% tools\bootstrap.py %*
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" exit /b 0
echo.
echo [ERRO] O ViralClip encerrou com codigo %EXIT_CODE%.
echo Tente executar: VIRALCLIP.bat repair
pause
exit /b %EXIT_CODE%

:python_missing
echo.
echo Nao foi possivel instalar Python automaticamente.
echo Execute: winget install -e --id Python.Python.3.12 --scope user
pause
exit /b 1
