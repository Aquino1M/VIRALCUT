@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d %~dp0

echo ========================================
echo   ViralClip Studio V3.1 - Instalacao Avancada
echo ========================================

echo [1/6] Procurando Python compativel com DirectML...
call :find_compatible_python
if not defined PY_COMPAT (
  echo Python 3.10-3.12 nao encontrado. Tentando instalar Python 3.12...
  where winget >nul 2>nul
  if errorlevel 1 goto :python_missing
  winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements --silent
  if errorlevel 1 goto :python_missing
  call :find_compatible_python
  if not defined PY_COMPAT if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY_COMPAT=%LocalAppData%\Programs\Python\Python312\python.exe"
  if not defined PY_COMPAT goto :python_missing
)
echo Python selecionado: %PY_COMPAT%

if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import sys; raise SystemExit(0 if (3,10) ^<= sys.version_info[:2] ^<= (3,12) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo Ambiente antigo usa Python incompatível. Recriando .venv...
    rmdir /s /q .venv
  )
)
if not exist .venv\Scripts\python.exe (
  %PY_COMPAT% -m venv .venv
  if errorlevel 1 goto :error
)
call .venv\Scripts\activate.bat

echo [2/6] Instalando dependencias Python...
python -m pip install --upgrade pip
if errorlevel 1 goto :error
pip install --upgrade -r requirements.txt
if errorlevel 1 goto :error
if not exist .env copy .env.example .env >nul

echo [3/6] Verificando FFmpeg...
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [AVISO] FFmpeg nao esta no PATH.
  echo Tentando instalar Gyan.FFmpeg pelo winget...
  where winget >nul 2>nul
  if not errorlevel 1 winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements --silent
)

echo [4/6] Instalando fontes abertas...
python tools\install_fonts.py
if errorlevel 1 echo [AVISO] Algumas fontes opcionais nao foram instaladas. O app continuara funcionando.

echo [5/6] Instalando modelo leve de Face Tracking...
python tools\install_tracking_models.py
if errorlevel 1 echo [AVISO] YuNet nao foi instalado. O fallback Haar sera usado.

echo [6/6] Diagnostico geral...
python tools\check_system.py

echo.
echo ========================================
echo Instalacao base concluida.
echo Para uso normal, feche esta janela e use somente VIRALCLIP.bat.
echo O VIRALCLIP.bat detecta NVIDIA, AMD, Intel ou CPU automaticamente.
echo ========================================
pause
exit /b 0

:find_compatible_python
set "PY_COMPAT="
py -3.12 -V >nul 2>nul
if not errorlevel 1 set "PY_COMPAT=py -3.12"
if defined PY_COMPAT goto :eof
py -3.11 -V >nul 2>nul
if not errorlevel 1 set "PY_COMPAT=py -3.11"
if defined PY_COMPAT goto :eof
py -3.10 -V >nul 2>nul
if not errorlevel 1 set "PY_COMPAT=py -3.10"
if defined PY_COMPAT goto :eof
python -c "import sys; raise SystemExit(0 if (3,10) ^<= sys.version_info[:2] ^<= (3,12) else 1)" >nul 2>nul
if not errorlevel 1 set "PY_COMPAT=python"
goto :eof

:python_missing
echo.
echo Nao foi possivel localizar ou instalar Python 3.10-3.12.
echo Instale manualmente com:
echo   winget install -e --id Python.Python.3.12 --scope user
echo Depois execute VIRALCLIP.bat novamente.
pause
exit /b 1

:error
echo.
echo [ERRO] A instalacao foi interrompida. Veja a mensagem acima.
pause
exit /b 1
