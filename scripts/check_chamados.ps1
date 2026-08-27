Param(
    [string]$DbHost = $env:DB_HOST,
    [string]$DbUser = $env:DB_USER,
    [string]$DbName = $env:DB_NAME,
    [string]$DbPass = $env:DB_PASS,
    [int]$Limit = 10,
    [ValidateSet("table","csv")][string]$Format = "table"
)

if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
    Write-Error "psql não encontrado no PATH. Instale o cliente Postgres ou execute a query manualmente."
    exit 1
}

if (-not $DbHost) { $DbHost = Read-Host "DB_HOST (host do Postgres)" }
if (-not $DbUser) { $DbUser = Read-Host "DB_USER (usuário)" }
if (-not $DbName) { $DbName = Read-Host "DB_NAME (database)" }
if (-not $DbPass) { $secure = Read-Host -AsSecureString "DB_PASS (senha)"; $DbPass = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)) }

$env:PGPASSWORD = $DbPass

$sql = "COPY (SELECT id, whatsapp_cliente, whatsapp_instance, status, to_char(data_abertura, 'YYYY-MM-DD HH24:MI:SS') as data_abertura FROM chamados ORDER BY id DESC LIMIT $Limit) TO STDOUT WITH CSV HEADER"

try {
    $output = & psql -h $DbHost -U $DbUser -d $DbName -c $sql 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "psql retornou código $LASTEXITCODE`n$output"
        exit $LASTEXITCODE
    }

    # psql prints the CSV to stdout; capture it and parse
    $csvText = $output -join "`n"
    # psql sometimes includes notice lines before CSV; try to find header line
    $lines = $csvText -split "`n"
    $startIdx = ($lines | Select-String -Pattern '^id,whatsapp_cliente' -SimpleMatch).LineNumber
    if (-not $startIdx) {
        # fallback: try to detect header by looking for a line starting with id,
        $startIdx = ($lines | Select-String -Pattern '^id,' | Select-Object -First 1).LineNumber
    }
    if ($startIdx) {
        $csvPortion = $lines[($startIdx - 1)..($lines.Length - 1)] -join "`n"
    } else {
        # if cannot find, assume entire output is CSV
        $csvPortion = $csvText
    }

    if ($Format -eq 'csv') {
        $csvPortion | Out-File -Encoding utf8 chamado_export.csv
        Write-Output "CSV salvo em chamado_export.csv"
    } else {
        $rows = $csvPortion | ConvertFrom-Csv -ErrorAction SilentlyContinue
        if ($null -eq $rows) {
            Write-Output "Nenhum dado CSV detectado. Saída cruída:`n$csvText"
        } else {
            $rows | Format-Table -AutoSize
        }
    }
} finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
