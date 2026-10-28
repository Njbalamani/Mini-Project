# REST API

Base path: `/api/v1/`. Interactive documentation:

- OpenAPI schema: `/api/schema/`
- Swagger UI: `/api/docs/`

Authentication uses the session (browser) or DRF token authentication. All
endpoints require an authenticated user and behave per-user. Responses are
paginated with a default page size of 20. Requests are throttled per user
(`user`, `assistant`, `sensitive` scopes).

## Router endpoints (CRUD)

| Resource                    | Path                              |
| --------------------------- | --------------------------------- |
| Tasks                       | `/api/v1/tasks/`                  |
| Calendar events             | `/api/v1/calendar/events/`        |
| Assistant conversations     | `/api/v1/assistant/conversations/`|
| Workflows                   | `/api/v1/workflows/`              |
| Workflow executions         | `/api/v1/workflows/executions/`   |
| Integrations                | `/api/v1/integrations/`           |
| Documents                   | `/api/v1/documents/`              |
| Notifications               | `/api/v1/notifications/`          |
| AI usage                    | `/api/v1/ai/usage/`               |

Each resource follows Django REST Framework conventions, supporting `GET`
(list/detail), `POST`, `PUT`/`PATCH` and `DELETE` where applicable.

## Convenience endpoints

| Method | Path                    | Description                          |
| ------ | ----------------------- | ------------------------------------ |
| `GET`  | `/api/v1/health/`       | Service health probe                 |
| `GET`  | `/api/v1/dashboard/`    | Aggregated dashboard summary         |
| `GET`  | `/api/v1/accounts/me/`  | Current authenticated user           |
| `GET`  | `/api/v1/analytics/`    | Server-computed analytics report     |

## Example

```bash
# List your tasks (session cookie or Authorization: Token <key>)
curl -H "Authorization: Token $TOKEN" http://127.0.0.1:8000/api/v1/tasks/
```

Errors use standard DRF response shapes:

```json
{ "detail": "Authentication credentials were not provided." }
```

See `/api/docs/` for the full, always-current specification.
