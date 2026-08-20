@echo off
rem Compatibilidade legada. Para uso normal, execute VIRALCLIP.bat.
chcp 65001 >nul
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo Ambiente virtual nao encontrado. Execute VIRALCLIP.bat para preparar tudo automaticamente.
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul || (
  echo FFmpeg nao encontrado no PATH.
  echo Instale com: winget install Gyan.FFmpeg
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
start "" http://127.0.0.1:8080
python run.py
pause
