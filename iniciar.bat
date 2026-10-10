@echo off
rem Mesa do Mestre Desktop - dois cliques para abrir.
rem Primeira vez: cria o ambiente virtual e instala as dependencias (precisa de Python 3.12+ e internet).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Preparando o programa pela primeira vez, aguarde...
    python -m venv .venv || goto erro
    ".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || goto erro
)
start "" ".venv\Scripts\pythonw.exe" -m mesa_desktop
exit /b 0
:erro
echo.
echo Nao foi possivel preparar o programa. Confira se o Python 3.12 ou superior esta instalado
echo (marque "Add python.exe to PATH" na instalacao) e se ha conexao com a internet.
pause
exit /b 1
