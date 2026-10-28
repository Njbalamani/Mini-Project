# Security model

NexaMind handles personal data (tasks, calendar, email, documents) and OAuth
credentials, so it is built around least privilege and explicit consent.

## Authentication

- Custom user model authenticating by **email** (`AUTH_USER_MODEL =
  accounts.User`).
- Password validators enforce a minimum length of 8 and common-password checks.
- Email verification flow is supported.
- Failed-login throttling and optional idle-session logout are configurable
  (`LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES`, `SESSION_IDLE_MINUTES`).

## Authorization / data isolation

- All reads and writes are filtered by `owner=request.user` (or an equivalent
  relation) at the query level.
- The REST API uses `IsAuthenticated` by default with per-user object access
  and scoped throttling (`api.permissions`, DRF throttle rates).

## Secrets and credentials

- Secrets are never committed; they are read from the environment
  (`.env` is git-ignored).
- OAuth access/refresh tokens are encrypted at rest with a Fernet key
  (`TOKEN_ENCRYPTION_KEY`) before being stored in `integrations`.
- Production settings refuse to start with the development secret key and
  require `DJANGO_ALLOWED_HOSTS`.

## AI safety

- The AI adapter **never fabricates** a response: if no provider is configured,
  `AINotConfigured` is raised and surfaced to the user.
- Model output is treated as untrusted. Any proposed structured action
  (create task/event/workflow) is validated against an explicit schema, value
  ranges and application rules (`ai_assistant.services.schemas`).
- Actions are **never executed automatically** — the user must confirm each one.
- No arbitrary code execution path exists in the workflow engine; only a fixed
  allow-list of action types is supported.

## Email

- Sending is **disabled by default** (`EmailSettings.sending_enabled`).
- Drafts require explicit approval before any send occurs.
- Only minimal message metadata is stored unless the user opts in to storing
  bodies.

## Transport / platform hardening

Production settings (`config.settings.production`) enable:

- `SECURE_SSL_REDIRECT`, HSTS (with preload and subdomains)
- Secure + HttpOnly session/CSRF cookies
- `X_FRAME_OPTIONS = DENY`, content-type nosniff, same-origin referrer policy
- Trusted-proxy SSL header handling

## Audit trail

Security-relevant events (logins, credential changes, AI action execution,
deletions) are recorded by `audit_logs` and viewable per user.
