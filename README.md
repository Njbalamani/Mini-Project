# NexaMind

An AI-powered personal assistant and intelligent automation platform built with
Django 5.2 (LTS). NexaMind combines an AI assistant, task management, a
calendar, an email assistant, workflow automation, integrations, document
analysis, notifications, analytics and subscription plans into a single
workspace with a custom "royal" design system.

> **Design principle:** the assistant never fabricates answers. If no AI
> provider is configured, the platform says so instead of inventing a reply.

---

## Features

- **AI Assistant** — conversations, message history, feedback, export, and a
  strict adapter layer supporting OpenAI, Gemini, or an explicit offline
  `mock` provider. **Replies stream token-by-token over SSE** with a JSON
  fallback for older clients. Structured actions (create task/event/workflow)
  are schema-validated and only executed after explicit user confirmation.
- **Tasks** — list and kanban views, priorities, categories, colour-coded
  **tags/labels**, due dates, status transitions with an activity trail,
  per-task discussion comments, reusable **saved views**, and CSV export.
  **Celery beat sends due-date reminders** (24h and overdue) respecting each
  user's preferences.
- **Calendar** — month matrix, event CRUD, free-slot suggestions, **drag-and-drop
  rescheduling**, and a subscribable **iCalendar (.ics) feed** with a rotatable
  private URL.
- **Email Assistant** — Gmail metadata sync, categorization rules, AI summaries,
  draft replies, and approval-gated sending (disabled by default).
- **Workflow Automation** — trigger/condition/action engine with idempotency
  keys, timeouts, retries, and execution history. Actions can notify, summarize
  tasks, suggest deadlines, or **create follow-up tasks**. Beat-driven scans
  fire scheduled + overdue workflows, and an **inbound webhook trigger** lets
  external services POST to a per-workflow secret URL to run a workflow.
- **Integrations** — Google, GitHub, **LinkedIn** and **Facebook** OAuth, plus
  **WhatsApp** — either the **Business Cloud API** (send/receive with a signed
  inbound webhook) or an **unofficial QR bridge** that links your existing
  personal number via the Linked-devices flow (see `whatsapp-bridge/`). Tokens
  are encrypted at rest, and connecting or disconnecting any account requires a
  fresh **step-up identity check** (TOTP or password).
- **Video calling** — browser-to-browser **WebRTC** calls with a camera/mic
  permission prompt; media flows peer-to-peer and is never recorded or relayed.
- **Documents** — upload, text extraction (PDF/DOCX), AI analysis and Q&A.
- **Notifications** — in-app notification center with a live bell dropdown,
  **real-time WebSocket pushes** (Django Channels), an optional weekly in-app
  digest, and an on-demand **digest preview** you can send to yourself.
- **Unified search** — a **Ctrl/Cmd+K command palette** searches tasks, events,
  documents, conversations, workflows and email from anywhere.
- **Theming** — light/dark toggle persisted per-user (and per-browser before
  login) with a flash-free boot script, system-theme detection, and a keyboard
  shortcuts overlay.
- **Security** — TOTP two-factor authentication with QR enrolment and one-time
  backup codes, per-user API tokens for the REST API, and **active session
  management** (review and revoke signed-in devices).
- **Data portability** — export everything you own as JSON or a ZIP archive
  (documents and avatar included), and delete your account on demand.
- **Bulk task actions** — multi-select the list or board to complete, reopen,
  re-prioritise, reschedule or delete many tasks at once.
- **Recurring tasks** — daily/weekly/monthly tasks spawn their next occurrence
  automatically when completed, carrying their **tags** along.
- **Task tags** — colour-coded labels with autocomplete on the task form, a tag
  manager to rename/recolour/delete, and a `?tag=` list filter.
- **Assistant slash commands** — `/task`, `/event`, `/email`, `/summarize` and
  `/help` run deterministically without needing an AI provider.
- **Analytics** — server-computed metrics and Chart.js visualizations.
- **Subscriptions** — plans, quotas and usage metering.
- **Audit log** — security-relevant activity trail.
- **REST API** — DRF endpoints (tasks, tags, task comments, saved views, events,
  workflows, documents, notifications…) with schema (`/api/schema/`) and Swagger
  UI (`/api/docs/`).
- **Continuous integration** — GitHub Actions workflow runs the system check,
  migration check and the full test suite on every push/PR.

---

## Tech stack

| Layer      | Choice                                             |
| ---------- | -------------------------------------------------- |
| Backend    | Django 5.2 LTS, Django REST Framework              |
| Auth       | Custom email-login user model, optional TOTP 2FA   |
| Security   | Fernet-encrypted secrets, per-user API tokens      |
| Async      | Celery + Redis beat/worker, Django Channels        |
| Real-time  | WebSockets (notifications) + SSE (AI streaming)    |
| Database   | SQLite (dev) / PostgreSQL (production)             |
| Frontend   | Server-rendered templates, custom CSS, Chart.js    |
| Docs/API   | drf-spectacular                                    |
| CI         | GitHub Actions                                     |
| Packaging  | pip + requirements, Docker / docker-compose        |

---

## Quick start (local)

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/bin/activate          # macOS / Linux

# 2. Install dependencies
pip install -r requirements/development.txt

# 3. Configure environment
Copy-Item .env.example .env          # then edit values as needed

# 4. Create the database schema and load demo data
python manage.py migrate
python manage.py seed_demo

# 5. Run the development server
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

### Demo credentials

| Role  | Email                  | Password        |
| ----- | ---------------------- | --------------- |
| Demo  | demo@nexamind.local    | demo-pass-123   |
| Admin | admin@nexamind.local   | admin-pass-123  |

Change or remove these before any real deployment.

---

## Configuration

All settings are read from environment variables (see `.env.example`). Key
groups:

- **Django**: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`
- **Database**: `DB_ENGINE` (`sqlite` | `postgresql` | `mysql`) and the
  matching `DB_*` variables
- **Celery/Redis**: `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`,
  `CELERY_TASK_ALWAYS_EAGER` (beat schedule is defined in `base.py`)
- **Channels**: `CHANNEL_BACKEND` (`InMemoryChannelLayer` for dev,
  `channels_redis.core.RedisChannelLayer` for production), `CHANNEL_REDIS_URL`
- **AI**: `AI_PROVIDER` (empty | `openai` | `gemini` | `mock`), `AI_API_KEY`,
  `AI_MODEL`, `AI_BASE_URL`
- **OAuth**: `GOOGLE_CLIENT_ID/SECRET`, `GITHUB_CLIENT_ID/SECRET`,
  `LINKEDIN_CLIENT_ID/SECRET`, `FACEBOOK_CLIENT_ID/SECRET`
- **WhatsApp**: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
  `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_DISPLAY_NUMBER`;
  QR bridge: `WHATSAPP_BRIDGE_URL`, `WHATSAPP_BRIDGE_SECRET`
- **Security**: `TOKEN_ENCRYPTION_KEY` (Fernet), `LOGIN_MAX_ATTEMPTS`,
  `SESSION_IDLE_MINUTES`

Two-factor authentication and API tokens are managed per user in the app
(**Settings → Security & 2FA**, **Settings → API tokens**) and need no extra
environment variables.

Provider credentials (Google/Gmail, GitHub, LinkedIn, Facebook and WhatsApp) can
also be entered from the app UI by an administrator under
**Integrations → Provider credentials** — they are stored Fernet-encrypted and
override the environment values below, so no server file edits are required.

#### WhatsApp QR bridge (unofficial)

To link a **personal** WhatsApp number (not a Business Cloud API number), set
`Bridge URL` (default `http://127.0.0.1:3100`) and `Bridge secret` on the
WhatsApp credentials card, plus the `App secret` for webhook signatures, then run
the Node bridge in `whatsapp-bridge/` (see `whatsapp-bridge/README.md`). Open
**Integrations → WhatsApp → Connect** and link either with an **8-digit pairing
code** (type your number → enter the code in *Linked devices → Link with phone
number instead*) or by scanning the QR. **Warning:** this reverse-engineers
WhatsApp Web, violates WhatsApp's Terms of Service, and can get the number banned.

Settings modules: `config.settings.development` (default), `.production`
(secure defaults, used by WSGI/Celery in containers) and `.test` (pytest).

### Enabling the AI provider

```powershell
# Offline demo (no network calls, canned deterministic replies)
$env:AI_PROVIDER = "mock"

# OpenAI
$env:AI_PROVIDER = "openai"
$env:AI_API_KEY  = "sk-..."
$env:AI_MODEL    = "gpt-4o-mini"
```

If `AI_PROVIDER` is left empty the assistant reports that it is not configured.

---

## Running tests

```powershell
python -m pytest
```

Tests use `config.settings.test` and do not require a running database server
or a `collectstatic` run.

---

## Docker

```powershell
docker compose up --build
```

This starts PostgreSQL, Redis, the web server, a Celery worker and Celery beat.
Provide real secrets via environment variables or a `.env` file before using
this in any non-local environment.

---

## Project layout

```
config/            # project settings, urls, wsgi/asgi, celery
apps/              # 14 feature apps (accounts, tasks, ai_assistant, ...)
templates/         # server-rendered templates + shared components
static/            # css/js design system
tests/             # pytest suite
requirements/      # base / development / production
docs/              # architecture and security notes
```

See `docs/ARCHITECTURE.md` and `docs/SECURITY.md` for details.

---

## Security notes

- Email sending is **disabled by default** and requires explicit approval.
- OAuth tokens are encrypted with `cryptography`'s Fernet before storage.
- TOTP secrets are Fernet-encrypted at rest; backup codes are stored only as
  salted hashes and consumed once.
- API tokens are per-user, revocable, and sent via the `Authorization: Token`
  header.
- All data access is scoped to the authenticated user; the API enforces
  per-user permissions and throttling.
- The AI layer never executes arbitrary code and validates every proposed
  action against an explicit schema.
- Production settings enforce HTTPS, HSTS and secure cookies.
