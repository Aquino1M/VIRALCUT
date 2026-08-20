@echo off
setlocal
cd /d "%~dp0"
echo ==============================================
echo ViralClip AI - Instalar fontes abertas
echo ==============================================
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tools\install_fonts.py
) else (
  py -3 tools\install_fonts.py 2>nul || python tools\install_fonts.py
)
echo.
echo A instalacao de fontes e opcional. O app usa fallback se alguma falhar.
pause
