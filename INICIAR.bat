@echo off
REM Iniciar o Monitor de Usuários - Menu Principal

echo.
echo ======================================================================
echo   🖥️  MONITOR DE USUARIOS - INICIANDO...
echo ======================================================================
echo.

REM Verifica se está em C:\sistema-impressao
cd /d C:\sistema-impressao

REM Verifica se o PowerShell script existe
if not exist MENU.ps1 (
    echo [ERRO] Arquivo MENU.ps1 nao encontrado em C:\sistema-impressao
    pause
    exit /b 1
)

REM Inicia o PowerShell com o menu
echo Abrindo menu...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "MENU.ps1"

pause
