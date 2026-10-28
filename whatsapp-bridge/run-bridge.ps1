# Start the NexaMind WhatsApp bridge (unofficial Baileys link).
#
# 1. Create a strong shared secret and make sure it matches the
#    "bridge_secret" you save under Integrations -> Provider credentials.
# 2. The webhook secret must match the "app_secret" you saved there too.
# 3. Run:  powershell -ExecutionPolicy Bypass -File .\run-bridge.ps1

$env:PORT              = if ($env:PORT)              { $env:PORT }              else { "3100" }
$env:WA_BRIDGE_SECRET  = if ($env:WA_BRIDGE_SECRET)  { $env:WA_BRIDGE_SECRET }  else { "change-me-bridge-secret" }
$env:WA_WEBHOOK_SECRET = if ($env:WA_WEBHOOK_SECRET) { $env:WA_WEBHOOK_SECRET } else { "change-me-app-secret" }
$env:WA_WEBHOOK_URL    = if ($env:WA_WEBHOOK_URL)    { $env:WA_WEBHOOK_URL }    else { "http://127.0.0.1:8000/integrations/whatsapp/webhook/" }

Write-Host "Starting WhatsApp bridge on port $env:PORT ..."
node "$PSScriptRoot\index.js"
