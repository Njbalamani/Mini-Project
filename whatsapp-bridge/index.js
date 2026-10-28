/**
 * NexaMind WhatsApp bridge (unofficial).
 *
 * Links a personal WhatsApp account through the multi-device "Linked devices"
 * QR flow using @whiskeysockets/baileys, then:
 *   - exposes the current pairing QR + status over HTTP for the Django UI,
 *   - sends messages on request from Django, and
 *   - forwards inbound messages to the Django webhook (Meta-shaped payload,
 *     HMAC-SHA256 signed) so the existing receiver handles them unchanged.
 *
 * WARNING: This is NOT an official WhatsApp API. It reverse-engineers WhatsApp
 * Web and using it violates WhatsApp's Terms of Service. The linked number can be
 * banned. Run it only with a number you can afford to lose.
 */
import crypto from 'node:crypto'
import path from 'node:path'

import express from 'express'
import pino from 'pino'
import QRCode from 'qrcode'
import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys'

const PORT = Number(process.env.PORT || 3100)
const SECRET = process.env.WA_BRIDGE_SECRET || ''
const WEBHOOK_URL =
  process.env.WA_WEBHOOK_URL || 'http://127.0.0.1:8000/integrations/whatsapp/webhook/'
const WEBHOOK_SECRET = process.env.WA_WEBHOOK_SECRET || ''
const AUTH_DIR = process.env.WA_AUTH_DIR || path.join(process.cwd(), 'auth_info')

if (!SECRET) {
  console.error('WA_BRIDGE_SECRET is required. Refusing to start.')
  process.exit(1)
}

const logger = pino({ level: 'silent' })

const state = {
  status: 'starting', // starting | qr | open | connecting | logout | close
  qr: null,
  pairingCode: null,
  me: null,
  lastError: null,
  socketReady: false,
}

let sock = null
let starting = false

function extractText(message) {
  if (!message) return ''
  if (message.conversation) return message.conversation
  if (message.extendedTextMessage?.text) return message.extendedTextMessage.text
  const media =
    message.imageMessage || message.videoMessage || message.documentMessage
  if (media?.caption) return media.caption
  return ''
}

function jidFor(number) {
  const digits = String(number).replace(/[^0-9]/g, '')
  return `${digits}@s.whatsapp.net`
}

async function forwardInbound(m) {
  if (!m.message || m.key?.fromMe) return
  const from = m.key?.remoteJid || ''
  if (!from || from.endsWith('@g.us') || from.endsWith('@broadcast')) return
  const text = extractText(m.message)
  if (!text) return
  const waId = from.replace(/@.*/, '')
  const payload = {
    object: 'whatsapp_business_account',
    bridge: true,
    entry: [
      {
        id: 'bridge',
        changes: [
          {
            field: 'messages',
            value: {
              messaging_product: 'whatsapp',
              metadata: {
                display_phone_number: state.me || '',
                phone_number_id: 'bridge',
              },
              contacts: [{ profile: { name: m.pushName || '' }, wa_id: waId }],
              messages: [
                {
                  from: waId,
                  id: m.key?.id || '',
                  timestamp: String(m.messageTimestamp || ''),
                  type: 'text',
                  text: { body: text },
                },
              ],
            },
          },
        ],
      },
    ],
  }
  const raw = JSON.stringify(payload)
  const headers = { 'Content-Type': 'application/json' }
  if (WEBHOOK_SECRET) {
    headers['X-Hub-Signature-256'] =
      'sha256=' + crypto.createHmac('sha256', WEBHOOK_SECRET).update(raw).digest('hex')
  }
  try {
    const res = await fetch(WEBHOOK_URL, { method: 'POST', headers, body: raw })
    if (!res.ok) logger.error(`webhook responded ${res.status}`)
  } catch (err) {
    logger.error(`webhook post failed: ${err.message}`)
  }
}

async function start() {
  if (starting) return
  starting = true
  state.status = 'connecting'
  state.socketReady = false
  try {
    const { state: authState, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
    const { version } = await fetchLatestBaileysVersion()
    sock = makeWASocket({
      version,
      auth: authState,
      printQRInTerminal: false,
      browser: Browsers.ubuntu('Chrome'),
      logger,
      syncFullHistory: false,
    })

    sock.ev.on('creds.update', saveCreds)

    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update
      if (qr) {
        try {
          state.qr = await QRCode.toDataURL(qr, { margin: 1, width: 320 })
        } catch (err) {
          state.qr = null
          logger.error(`qr encode failed: ${err.message}`)
        }
        state.status = 'qr'
        state.socketReady = true
      }
      if (connection === 'open') {
        state.status = 'open'
        state.qr = null
        state.pairingCode = null
        state.socketReady = true
        state.me = sock.user?.id ? sock.user.id.split(':')[0] : null
        logger.info(`linked as ${state.me}`)
      }
      if (connection === 'close') {
        const code = lastDisconnect?.error?.output?.statusCode
        const loggedOut = code === DisconnectReason.loggedOut
        state.lastError = lastDisconnect?.error?.message || null
        state.me = null
        state.pairingCode = null
        state.socketReady = false
        starting = false
        if (loggedOut) {
          state.status = 'logout'
          state.qr = null
          logger.warn('logged out of WhatsApp')
        } else {
          state.status = 'connecting'
          setTimeout(start, 2000)
        }
      }
    })

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
      if (type !== 'notify') return
      for (const m of messages || []) {
        await forwardInbound(m)
      }
    })
  } catch (err) {
    state.status = 'close'
    state.lastError = err.message
    starting = false
    logger.error(`start failed: ${err.message}`)
    setTimeout(start, 3000)
  } finally {
    if (state.status !== 'connecting') starting = false
    else starting = false
  }
}

const app = express()
app.use(express.json())

function requireSecret(req, res, next) {
  if (req.get('x-bridge-secret') !== SECRET) {
    return res.status(401).json({ error: 'unauthorized' })
  }
  next()
}

app.get('/qr', (req, res) => {
  res.json({
    status: state.status,
    qr: state.qr,
    pairingCode: state.pairingCode,
    me: state.me,
    error: state.lastError,
  })
})

app.get('/status', (req, res) => {
  res.json({
    status: state.status,
    pairingCode: state.pairingCode,
    me: state.me,
    error: state.lastError,
  })
})

app.post('/pair', requireSecret, async (req, res) => {
  const { number } = req.body || {}
  if (!number) return res.status(400).json({ error: 'number is required' })
  if (state.status === 'open') {
    return res.status(409).json({ error: 'already linked; unlink first' })
  }
  let clean = String(number).replace(/[^0-9]/g, '')
  if (clean.startsWith('0')) clean = clean.replace(/^0+/, '')
  if (clean.length < 8) {
    return res.status(400).json({
      error: 'Enter the full number with country code (e.g. 15551234567), no leading 0 or +.',
    })
  }
  // The socket must be connected before a pairing code can be requested,
  // otherwise WhatsApp issues a dead code that the phone rejects.
  const deadline = Date.now() + 20000
  while ((!sock || !state.socketReady) && state.status !== 'open' && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 300))
  }
  if (!sock || (!state.socketReady && state.status !== 'open')) {
    return res.status(409).json({ error: 'bridge not connected yet — wait a moment and try again' })
  }
  try {
    await new Promise((r) => setTimeout(r, 1000))
    state.pairingCode = await sock.requestPairingCode(clean)
    res.json({ ok: true, code: state.pairingCode })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

app.post('/send', requireSecret, async (req, res) => {
  const { to, text } = req.body || {}
  if (!to || !text) return res.status(400).json({ error: 'to and text are required' })
  if (state.status !== 'open' || !sock) {
    return res.status(409).json({ error: 'not linked' })
  }
  try {
    const result = await sock.sendMessage(jidFor(to), { text: String(text).slice(0, 4096) })
    res.json({ ok: true, id: result?.key?.id || null })
  } catch (err) {
    res.status(502).json({ error: err.message })
  }
})

app.post('/logout', requireSecret, async (req, res) => {
  try {
    if (sock) await sock.logout()
  } catch (err) {
    logger.error(`logout failed: ${err.message}`)
  }
  state.status = 'logout'
  state.me = null
  state.qr = null
  res.json({ ok: true })
})

app.listen(PORT, '127.0.0.1', () => {
  logger.info(`bridge listening on http://127.0.0.1:${PORT}`)
  console.log(`NexaMind WhatsApp bridge listening on http://127.0.0.1:${PORT}`)
  start()
})
