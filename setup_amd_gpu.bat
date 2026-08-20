@echo off
rem Compatibilidade AMD legada. O caminho recomendado e VIRALCLIP.bat, que detecta a GPU.
setlocal EnableExtensions
chcp 65001 >nul
cd /d %~dp0

echo ==============================================
echo   ViralClip AI - Ativar AMD RX 580 / DirectML
echo ==============================================

if not exist .venv\Scripts\python.exe (
  echo Ambiente virtual nao encontrado. Execute VIRALCLIP.bat primeiro.
  pause
  exit /b 1
)

.venv\Scripts\python.exe -c "import sys; v=sys.version_info[:2]; raise SystemExit(0 if (3,8) ^<= v ^<= (3,12) else 1)" >nul 2>nul
if errorlevel 1 (
  echo A versao atual do Python nao e compativel com torch-directml.
  echo Procurando Python 3.12, 3.11 ou 3.10...

  call :find_compatible_python
  if not defined PY_COMPAT (
    echo Python compativel nao encontrado. Tentando instalar Python 3.12 automaticamente...
    where winget >nul 2>nul
    if errorlevel 1 goto :python_missing

    winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements --silent
    if errorlevel 1 (
      echo A instalacao automatica com winget falhou.
      goto :python_missing
    )

    call :find_compatible_python
    if not defined PY_COMPAT (
      if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY_COMPAT=%LocalAppData%\Programs\Python\Python312\python.exe"
    )
    if not defined PY_COMPAT goto :python_missing
  )

  echo Recriando .venv com: %PY_COMPAT%
  rmdir /s /q .venv
  %PY_COMPAT% -m venv .venv
  if errorlevel 1 goto :error
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  if errorlevel 1 goto :error
  pip install -r requirements.txt
  if errorlevel 1 goto :error
) else (
  call .venv\Scripts\activate.bat
)

echo.
echo [1/4] Instalando PyTorch DirectML...
pip install --upgrade torch-directml numba numpy tqdm more-itertools tiktoken ffmpeg-python
if errorlevel 1 goto :error

echo.
echo [2/4] Baixando o Whisper DirectML oficial da Microsoft...
if exist vendor\directml_whisper\whisper rmdir /s /q vendor\directml_whisper\whisper
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $zip=Join-Path $env:TEMP 'viralclip_directml.zip'; $dst=Join-Path $env:TEMP 'viralclip_directml_src'; Remove-Item -Force $zip -ErrorAction SilentlyContinue; Remove-Item -Recurse -Force $dst -ErrorAction SilentlyContinue; Invoke-WebRequest -UseBasicParsing 'https://github.com/microsoft/DirectML/archive/8700779fe7a09ea7a007cf3d7ab4293c78e41017.zip' -OutFile $zip; Expand-Archive -Force $zip $dst; $src=Join-Path $dst 'DirectML-8700779fe7a09ea7a007cf3d7ab4293c78e41017\PyTorch\audio\whisper'; New-Item -ItemType Directory -Force 'vendor\directml_whisper' | Out-Null; Copy-Item -Recurse -Force (Join-Path $src 'whisper') 'vendor\directml_whisper\whisper'; Copy-Item -Force (Join-Path $src 'LICENSE') 'vendor\directml_whisper\MICROSOFT_WHISPER_LICENSE.txt'; Remove-Item -Force $zip; Remove-Item -Recurse -Force $dst"
if errorlevel 1 goto :error

echo.
echo [3/4] Ativando DirectML e encoder AMD no .env...
if not exist .env copy .env.example .env >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='.env'; $c=Get-Content $p -Raw; if($c -match '(?m)^WHISPER_BACKEND='){ $c=[regex]::Replace($c,'(?m)^WHISPER_BACKEND=.*$','WHISPER_BACKEND=directml') } else { $c += [Environment]::NewLine + 'WHISPER_BACKEND=directml' }; if($c -match '(?m)^VIDEO_ENCODER='){ $c=[regex]::Replace($c,'(?m)^VIDEO_ENCODER=.*$','VIDEO_ENCODER=auto') } else { $c += [Environment]::NewLine + 'VIDEO_ENCODER=auto' }; Set-Content -Path $p -Value $c -Encoding UTF8"
if errorlevel 1 goto :error

echo.
echo [4/4] Testando GPU e FFmpeg...
python tools\check_acceleration.py
if errorlevel 1 goto :error

echo.
echo ==============================================
echo GPU AMD configurada. Para uso normal, inicie com VIRALCLIP.bat.
echo No Gerenciador de Tarefas, abra Desempenho ^> GPU e visualize Compute.
echo ==============================================
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
goto :eof

:python_missing
echo.
echo Nao foi possivel localizar ou instalar Python 3.10-3.12.
echo Tente manualmente:
echo   winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
echo Depois execute VIRALCLIP.bat novamente.
pause
exit /b 1

:error
echo.
echo Falha ao configurar DirectML. O ViralClip continua podendo funcionar em CPU.
echo Copie a mensagem de erro acima se quiser que eu ajuste.
pause
exit /b 1
