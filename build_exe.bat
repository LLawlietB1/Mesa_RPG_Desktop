@echo off
rem Gera dist\MesaDoMestre\MesaDoMestre.exe (programa independente, sem precisar do Python instalado).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv || goto erro
)
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements-dev.txt || goto erro
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name MesaDoMestre ^
    --icon assets\icon.ico --add-data "assets;assets" --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick mesa_desktop\__main__.py || goto erro
echo.
echo Pronto: dist\MesaDoMestre\MesaDoMestre.exe
pause
exit /b 0
:erro
echo Falha ao gerar o executavel.
pause
exit /b 1
