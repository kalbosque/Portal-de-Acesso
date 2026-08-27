Param(
    [string]$DbHost = $env:DB_HOST,
    [string]$DbUser = $env:DB_USER,
    [string]$DbName = $env:DB_NAME,
    [string]$DbPass = $env:DB_PASS,
    [string]$SqlFile = "db/migrations/001_add_whatsapp_instance.sql"
)

if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
    Write-Error "psql não encontrado no PATH. Instale o cliente Postgres ou execute o SQL manualmente."
    exit 1
}

if (-not $DbHost) { $DbHost = Read-Host "DB_HOST (host do Postgres)" }
if (-not $DbUser) { $DbUser = Read-Host "DB_USER (usuário)" }
if (-not $DbName) { $DbName = Read-Host "DB_NAME (database)" }
if (-not $DbPass) { $DbPass = Read-Host -AsSecureString "DB_PASS (senha)"; $DbPass = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($DbPass)) }

if (-not (Test-Path $SqlFile)) {
    Write-Error "Arquivo SQL não encontrado: $SqlFile"
    exit 1
}

# Exporta PGPASSWORD temporariamente
$env:PGPASSWORD = $DbPass
try {
    Write-Output "Aplicando migração: $SqlFile -> host=$DbHost db=$DbName user=$DbUser"
    & psql -h $DbHost -U $DbUser -d $DbName -f $SqlFile
    if ($LASTEXITCODE -ne 0) {
        Write-Error "psql retornou código $LASTEXITCODE"
        exit $LASTEXITCODE
    }
    Write-Output "Migração aplicada com sucesso."
} finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
