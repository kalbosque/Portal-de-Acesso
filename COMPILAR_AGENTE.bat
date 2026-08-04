@echo off
echo ============================================
echo   SUPER CONSTRUTOR PRINTDASH 2.0.1
echo ============================================
echo.
cd /d "%~dp0"

echo [1/4] Verificando e Instalando Dependencias...
python -m pip install --upgrade pip
python -m pip install pyinstaller requests

echo.
echo [2/4] Limpando versoes antigas...
if exist dist del /q dist\*.*
if exist build rd /s /q build

echo.
echo [3/4] Compilando novo Agente...
python -m PyInstaller --onefile --noconsole agent_2.0.py

echo.
echo [4/4] Finalizando...
if exist dist\agent_2.0.exe (
    echo.
    echo SUCESSO! O novo agente foi criado em: %~dp0dist\agent_2.0.exe
    explorer "%~dp0dist"
) else (
    echo.
    echo ERRO: Nao foi possivel criar o .EXE. 
)
pause
