@echo off
:: ============================================================
::   ATUALIZADOR DO AGENTE NO SERVIDOR LOCAL
::   Usa tarefa agendada SYSTEM para matar o processo e instalar
:: ============================================================
title Atualizador PrintDash v2.3.0 - Servidor

net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [ERRO] Execute como ADMINISTRADOR!
    pause
    exit /b 1
)

echo.
echo  ============================================
echo    ATUALIZANDO AGENTE NO SERVIDOR v2.3.0
echo  ============================================
echo.

set DESTINO=C:\AgentImpressao
set NOVO_EXE=%~dp0agent_2.0.exe
set SCRIPT_SWAP=%TEMP%\swap_agent.bat

:: Verifica se o novo exe existe
if not exist "%NOVO_EXE%" (
    echo [ERRO] agent_2.0.exe nao encontrado em %~dp0
    pause
    exit /b 1
)

echo  [1/4] Preparando script de troca...
(
    echo @echo off
    echo taskkill /F /IM agent_2.0.exe /T ^>nul 2^>^&1
    echo timeout /t 2 /nobreak ^>nul
    echo copy /y "%NOVO_EXE%" "%DESTINO%\agent_2.0.exe" ^>nul
    echo start "" "%DESTINO%\agent_2.0.exe"
    echo schtasks /delete /tn "PrintDashSwap" /f ^>nul 2^>^&1
) > "%SCRIPT_SWAP%"
echo       OK!

echo  [2/4] Registrando tarefa de sistema para swap...
schtasks /delete /tn "PrintDashSwap" /f >nul 2>&1
schtasks /create /tn "PrintDashSwap" /tr "cmd.exe /c \"%SCRIPT_SWAP%\"" /sc once /st 00:00 /ru SYSTEM /rl HIGHEST /f >nul
echo       OK!

echo  [3/4] Executando swap agora como SYSTEM...
schtasks /run /tn "PrintDashSwap" >nul 2>&1
timeout /t 5 /nobreak >nul
echo       OK!

echo  [4/4] Copiando para pasta de auto-update da API...
copy /y "%NOVO_EXE%" "c:\sistema-impressao\dist\agent_2.0.exe" >nul 2>&1
if %errorLevel% EQU 0 (
    echo       OK! API de auto-update atualizada.
) else (
    echo       AVISO: Nao foi possivel copiar para dist/. O processo pode ainda estar rodando.
    echo       Aguarde 10 segundos e tente novamente...
    timeout /t 10 /nobreak >nul
    copy /y "%NOVO_EXE%" "c:\sistema-impressao\dist\agent_2.0.exe" >nul 2>&1
    if %errorLevel% EQU 0 (echo       OK! Copiado na segunda tentativa.) else (echo       FALHOU. Copie manualmente.)
)

echo.
echo  ============================================
echo    ATUALIZACAO CONCLUIDA!
echo  ============================================
echo.
echo  Agente v2.3.0 ativo em: %DESTINO%\agent_2.0.exe
echo  Auto-update disponivel: c:\sistema-impressao\dist\agent_2.0.exe
echo.
echo  PARA AS OUTRAS MAQUINAS DA REDE:
echo  Execute INSTALAR.bat como Administrador em cada PC.
echo  O agente se atualiza automaticamente via rede.
echo.
pause
