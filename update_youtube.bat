@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d %~dp0

echo ==============================================
echo   ViralClip AI - Atualizar suporte YouTube
echo ==============================================

if not exist .venv\Scripts\python.exe (
  echo Ambiente virtual nao encontrado. Execute install.bat primeiro.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade "yt-dlp[default,deno]" yt-dlp-getpot-wpc bgutil-ytdlp-pot-provider
if errorlevel 1 goto :error

echo.
echo Verificando componentes...
python tools\check_youtube.py
if errorlevel 1 goto :error

echo.
echo Atualizacao do YouTube concluida.
echo Feche o ViralClip se ele estiver aberto e execute run.bat novamente.
pause
exit /b 0

:error
echo.
echo Houve um erro ao atualizar os componentes do YouTube.
echo Copie a mensagem acima para diagnostico.
pause
exit /b 1
