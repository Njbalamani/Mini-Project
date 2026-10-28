# NexaMind WhatsApp bridge (unofficial)

This small Node service links a **personal WhatsApp number** to NexaMind using the
multi-device "Linked devices" QR flow (via [`@whiskeysockets/baileys`](https://github.com/WhiskeySockets/Baileys)).
It lets NexaMind send and receive real WhatsApp messages on your existing number.

> **Warning.** This is **not** an official WhatsApp/Meta API. It reverse-engineers
> WhatsApp Web and therefore **violates WhatsApp's Terms of Service**. The linked
> number can be **permanently banned**. Only use a number you can afford to lose.
> The official, sanctioned alternative is the WhatsApp Business Cloud API.

## How it works

```
Django  ──GET /qr──────────▶  bridge  ──(Linked Devices QR)──▶  your phone
        ──POST /send───────▶  bridge  ──sendMessage─────────▶  WhatsApp
        ◀─POST webhook (HMAC)─ bridge  ◀─messages.upsert─────  WhatsApp
```

The bridge forwards inbound messages to the existing Django webhook
(`/integrations/whatsapp/webhook/`) as a Meta-shaped JSON body signed with
`WA_WEBHOOK_SECRET` (`X-Hub-Signature-256`), so the server-side receiver is reused.

## Setup

```powershell
cd whatsapp-bridge
npm install
```

Then start it with matching secrets (these must equal the `bridge_secret` and
`app_secret` values you save in **Integrations → Provider credentials**):

```powershell
$env:WA_BRIDGE_SECRET  = "your-bridge-secret"
$env:WA_WEBHOOK_SECRET = "your-app-secret"
powershell -ExecutionPolicy Bypass -File .\run-bridge.ps1
```

## Linking

Two ways, both under **Integrations → WhatsApp → Connect**:

- **Pairing code (recommended).** Type your number, press **Get code**, then on
  your phone open **WhatsApp → Linked devices → Link a device → Link with phone
  number instead** and enter the 8-digit code.
- **QR.** Expand *or scan a QR instead* and scan it from the same Linked devices
  screen.

Either way the bridge reports `open` with your number and NexaMind stores the
connection. Inbound messages appear in the WhatsApp panel; sending uses the bridge.

## Endpoints

| Method | Path      | Auth             | Purpose                         |
|--------|-----------|------------------|---------------------------------|
| GET    | `/qr`     | none             | `{status,qr,pairingCode,me,error}` |
| GET    | `/status` | none             | `{status,pairingCode,me,error}` |
| POST   | `/pair`   | `x-bridge-secret`| `{number}` → returns 8-digit pairing code |
| POST   | `/send`   | `x-bridge-secret`| `{to,text}` → sends a message   |
| POST   | `/logout` | `x-bridge-secret`| unlink the device               |

Status values: `starting`, `qr`, `connecting`, `open`, `logout`, `close`.

Session credentials are stored under `whatsapp-bridge/auth_info/` (git-ignored).
