# Architecture

NexaMind is a modular Django application. Each feature lives in its own app
under `apps/`, with a thin view layer and a service layer that holds business
logic. This keeps views focused on HTTP concerns and makes logic testable.

## High-level layout

```
config/
  settings/          base / development / production / test
  urls.py            root URL router (namespaced includes)
  wsgi.py asgi.py    entry points (default to production settings)
  asgi.py            Channels ProtocolTypeRouter (http + websocket notifications)
  celery.py          Celery app with a beat schedule (reminders, scans, digest)

apps/
  accounts/          custom email-login user, profile, sessions, security
  dashboard/         authenticated landing page + error handlers
  ai_assistant/      conversations, message adapter, action validation
  tasks/             tasks, kanban, tags, comments, saved views, activity trail
  calendar_manager/  events, month matrix, free slots
  email_manager/     Gmail metadata, rules, drafts, approval-gated sending
  workflow_automation/ trigger/condition/action engine + executions
  integrations/      Google/GitHub OAuth, encrypted credentials
  notifications/     in-app notification center + context processor
  documents/         upload, text extraction, AI analysis
  analytics/         server-computed metrics + selectors
  subscriptions/     plans, quotas, usage metering
  audit_logs/        security activity trail + middleware
  api/               DRF serializers, views, permissions, pagination

templates/           base shell + per-app templates + components/
static/              css/base.css design system + per-page js
```

## Layers

1. **Models** — persistence and small invariants (e.g. `Plan.price_display`,
   status transition helpers).
2. **Services** — the real business logic (`apps/*/services.py`): task
   creation/transitions, tag resolution (`set_task_tags`), workflow execution,
   AI adapters, credential encryption, usage checks. Views call services rather
   than mutating models directly.
3. **Views** — authenticate, validate input, call services, and render either a
   template or JSON.
4. **Templates/JS** — server-rendered HTML; progressive enhancement with small
   vanilla-JS controllers (`static/js/*.js`). Charts use Chart.js from a CDN.

## Request flow (example: assistant message)

1. `POST /assistant/c/<id>/send/` → `ai_assistant.views.send_message`.
2. `subscriptions.services.check_limit` enforces the plan quota.
3. When the client requests `Accept: text/event-stream`, the view returns a
   `StreamingHttpResponse` that yields SSE `data:` events from
   `services.assistant.stream_reply` (`start` → `delta`… → `done`). Otherwise it
   falls back to the existing JSON flow via `generate_reply`.
4. `ai_assistant.services` calls the configured provider adapter. Providers
   expose `complete()` and `stream_chunks()`; the fallback implementation
   streams the full completion in one chunk. If no provider is configured,
   `AINotConfigured` is raised and the view returns `configured: false` —
   **no fabricated reply**.
5. Any structured actions in the model output are validated by
   `services.schemas.validate_action` and returned to the client for
   confirmation. Only after the user approves does
   `POST /assistant/action/execute/` create the real object
   (task/event/workflow).

## Real-time flow (example: notification)

1. `notifications.services.notify` creates a `Notification` row and, if a
   channel layer is configured, `group_send`s an event to
   `user_notifications_<user_id>`.
2. `NotificationConsumer` (WebSocket at `/ws/notifications/`) receives the event
   and pushes JSON to the browser.
3. `static/js/notifications.js` bumps the bell badge, prepends the dropdown item
   and shows a toast. Development uses the in-memory channel layer; production
   uses `channels_redis` so web and worker processes share state.

## Cross-cutting

- **Context processors** expose unread notification counts, plan/usage
  summaries, site name, AI status and pending task counts to every template.
- **Middleware** adds session idle timeout, TOTP two-factor enforcement, and
  audit context.
- **Background jobs** run inline in development (`CELERY_TASK_ALWAYS_EAGER`)
  and via Redis + worker in production. Celery beat runs `scan-scheduled-workflows`
  (60s), `scan-overdue-tasks` (15 min), `send-due-task-reminders` (30 min) and
  `send-weekly-digest` (Mondays).
- **Feature modules** live beside their app: `accounts/twofactor.py` (TOTP
  enrolment/verification), `accounts/export.py` (JSON/ZIP data portability),
  `calendar_manager/ics.py` (RFC 5545 serialisation for exports/feeds),
  `tasks/services.py` (tag resolution + recurring spawn),
  `notifications/services.py` (preference-aware `notify` + `build_digest`) and
  `ai_assistant/services/commands.py` (deterministic slash commands).
- **Inbound webhooks** — a `webhook` trigger gives each `Workflow` an auto-issued
  `webhook_token` (`ensure_webhook_token`/`reset_webhook_token`). The
  `csrf_exempt` `webhook_receive` view resolves the token, checks the workflow is
  enabled, and runs the engine with the request body as context, honouring an
  `X-NexaMind-Idempotency` header (or `idempotency_key` in the payload) for
  de-duplication.
- **Client-side enhancements** — `static/js/calendar-dnd.js` reschedules events
  by dragging chips between day cells (POST `calendar_manager:event_move`), and
  `static/js/tags-input.js` reads a `data-suggestions` list from the tag field to
  render clickable autocomplete chips.
- **Integrations & step-up auth** — `apps/integrations/` holds OAuth providers
  (Google, GitHub, LinkedIn, Facebook) and WhatsApp. `security.py` gates every
  connect/disconnect behind a fresh identity check (TOTP when 2FA is on, else the
  account password) remembered in the session for five minutes.
- **WhatsApp messaging** — `apps/integrations/whatsapp.py` wraps the Business
  Cloud API (`send_text`) and the signed inbound webhook (`verify_signature` HMAC
  over `WHATSAPP_APP_SECRET`, `parse_inbound`). Inbound messages are stored as
  `WhatsAppMessage` rows. Calling is **not** part of the API.
- **Video calling** — `static/js/webrtc-call.js` uses `getUserMedia` +
  `RTCPeerConnection` with a manual offer/answer handshake; media is peer-to-peer
  and never touches the server.
- **Provider credentials** — `integrations/credentials.py` resolves each provider
  field from a Fernet-encrypted `ProviderConfig` row first and the `NEXAMIND`
  environment second, so admins can enable providers from
  **Integrations → Provider credentials** without editing files. OAuth specs and
  the WhatsApp client both read through this resolver.
- **WhatsApp QR bridge** — `whatsapp-bridge/` is an optional Node service
  (`@whiskeysockets/baileys`) that links a personal number through the
  Linked-devices QR and then talks to Django: it serves the pairing QR to
  `/integrations/whatsapp/qr/status/`, accepts sends from Django's
  `whatsapp.send_text`, and forwards inbound messages to the existing signed
  webhook. Unofficial — violates WhatsApp's ToS.

## Data isolation

Every queryset is scoped to the authenticated user at the view/service layer,
and the API applies matching per-user permissions. There is no shared mutable
state between accounts.
