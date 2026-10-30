@echo off
setlocal EnableExtensions
title PrintDash - Instalacao do Agente v2.4.2

:: Autoeleva sem exigir que o usuario saiba como abrir como administrador.
net session >nul 2>&1
if not %errorlevel%==0 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

set "DESTINO=C:\AgentImpressao"
set "EXE=%DESTINO%\agent_2.0.exe"
set "NOVO=%~dp0agent_2.0.exe"
set "STARTUP=C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\PrintDashAgente.exe"

cls
echo ============================================================
echo        PRINTDASH - ATUALIZACAO DO AGENTE v2.4.2
echo ============================================================
echo.

if not exist "%NOVO%" (
    echo [ERRO] O novo executavel nao foi encontrado:
    echo        %NOVO%
    echo.
    pause
    exit /b 1
)

echo [1/6] Parando tarefas antigas...
schtasks /end /tn "PrintDashAgente" >nul 2>&1
schtasks /end /tn "PrintDashSwap" >nul 2>&1
schtasks /end /tn "MonitorImpressao" >nul 2>&1
timeout /t 2 /nobreak >nul

echo [2/6] Encerrando processos antigos...
taskkill /f /im agent_2.0.exe /t >nul 2>&1
timeout /t 2 /nobreak >nul
tasklist /fi "imagename eq agent_2.0.exe" | find /i "agent_2.0.exe" >nul
if %errorlevel%==0 (
    echo [ERRO] O agente antigo nao pode ser encerrado.
    echo        Execute este instalador como administrador.
    echo.
    pause
    exit /b 1
)

echo [3/6] Removendo inicializacoes antigas...
schtasks /delete /tn "PrintDashAgente" /f >nul 2>&1
schtasks /delete /tn "PrintDashSwap" /f >nul 2>&1
del /f /q "%STARTUP%" >nul 2>&1
if not exist "%DESTINO%" mkdir "%DESTINO%" >nul 2>&1

echo [4/6] Instalando o agente novo...
if exist "%EXE%" copy /y "%EXE%" "%EXE%.bak" >nul 2>&1
copy /y "%NOVO%" "%EXE%" >nul
if not %errorlevel%==0 (
    echo [ERRO] Nao foi possivel copiar o novo agente.
    pause
    exit /b 1
)

echo [5/6] Configurando inicializacao automatica...
schtasks /create /tn "PrintDashAgente" /tr "\"%EXE%\"" /sc ONLOGON /rl HIGHEST /f >nul
if not %errorlevel%==0 (
    echo [ERRO] Nao foi possivel criar a tarefa automatica.
    pause
    exit /b 1
)

echo [6/6] Iniciando e verificando o agente...
schtasks /run /tn "PrintDashAgente" >nul 2>&1
timeout /t 5 /nobreak >nul
tasklist /fi "imagename eq agent_2.0.exe" | find /i "agent_2.0.exe" >nul
if not %errorlevel%==0 (
    echo [ERRO] O agente foi instalado, mas nao iniciou.
    echo        Verifique o arquivo: %DESTINO%\agent.log
    pause
    exit /b 1
)

cls
echo ============================================================
echo        INSTALACAO CONCLUIDA COM SUCESSO!
echo ============================================================
echo.
echo Agente instalado: v2.4.2
echo Pasta: %DESTINO%
echo Execucao: em segundo plano
echo Inicializacao: automatica no login do Windows
echo.
echo O agente ja esta monitorando as impressoes desta maquina.
echo Voce pode fechar esta janela.
echo ============================================================
pause
exit /b 0
