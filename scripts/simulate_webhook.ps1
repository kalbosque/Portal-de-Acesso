Param(
    [string]$Instance = "printdash",
    [string]$Phone = "5511999999999",
    [string]$Name = "Teste Usuario",
    [string]$Text = "Mensagem de teste via webhook",
    [string]$Url = "http://localhost:8000/api/whatsapp/webhook"
)

try {
    $payload = @{
        event = "messages.upsert"
        instance = $Instance
        data = @(
            @{   
                key = @{ remoteJid = "$($Phone)@s.whatsapp.net"; fromMe = $false }
                pushName = $Name
                message = @{ conversation = $Text }
            }
        )
    }

    $json = $payload | ConvertTo-Json -Depth 10
    $resp = Invoke-RestMethod -Uri $Url -Method Post -Body $json -ContentType 'application/json' -ErrorAction Stop
    Write-Output "Webhook enviado com sucesso. Resposta:";
    Write-Output $resp | ConvertTo-Json -Depth 10
} catch {
    Write-Error "Falha ao enviar webhook: $($_.Exception.Message)"
}
