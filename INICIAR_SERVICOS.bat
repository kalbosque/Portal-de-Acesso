@echo off
setlocal

cd /d C:\sistema-impressao

echo Iniciando os servicos do Sistema de Impressao...

docker info >nul 2>&1
if errorlevel 1 (
    echo Docker Desktop ainda nao esta pronto. Aguarde alguns segundos e tente novamente.
    exit /b 1
)

docker compose up -d
if errorlevel 1 (
    echo Falha ao iniciar os servicos.
    exit /b 1
)

echo.
echo Servicos iniciados. Verificando status:
docker compose ps

endlocal
