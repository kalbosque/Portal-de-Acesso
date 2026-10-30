@echo off
title Desinstalador PrintDash Agente

net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [ERRO] Execute como Administrador!
    pause
    exit /b 1
)

echo Parando o agente...
taskkill /f /im agent_2.0.exe >nul 2>&1

echo Removendo tarefa agendada...
schtasks /delete /tn "PrintDashAgente" /f >nul 2>&1

echo Removendo do Startup global...
del /f /q "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\PrintDashAgente.exe" >nul 2>&1

echo Removendo arquivos...
rmdir /s /q "C:\AgentImpressao" >nul 2>&1

echo.
echo Agente PrintDash removido com sucesso!
pause
