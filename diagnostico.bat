@echo off
rem Compatibilidade legada. Para uso normal: VIRALCLIP.bat diagnose
chcp 65001 >nul
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo Ambiente virtual nao encontrado. Execute VIRALCLIP.bat primeiro.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo ==============================================
echo   ViralClip Studio V3.1 - Diagnostico Completo
echo ==============================================
python tools\check_system.py
echo.
echo Dica: o mesmo diagnostico pode ser aberto com VIRALCLIP.bat diagnose.
pause
