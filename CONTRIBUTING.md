# Contributing

Read this before adding a file. These are not preferences — breaking them
produces work that passes the build and still has to be undone.

## One package root: `app/`

All Python source lives under `app/`. There is exactly one package root.

```
app/
  main.py          FastAPI app factory (create_app) and the module-level `app`
  api/             route handlers only — no business logic
  services/        business logic
  models/          SQLAlchemy models
  db/              engine, session, base
  core/            settings, logging, cross-cutting concerns
tests/             mirrors the app/ tree
alembic/           migrations
```

**Do not create a `src/` directory.** A second root splits the codebase down
the middle while still passing the build. `src/` is git-ignored so it cannot
come back by accident.

## Layering

A route handler calls a service. A service calls a repository or model. Nothing
skips a layer, and nothing goes the other way — `models/` must never import from
`api/`.

## Tests

Every change ships with its tests, in `tests/`, mirroring the path of what it
tests. `app/services/provider_key.py` is tested by
`tests/services/test_provider_key.py`.

Tests must pass with **no external services running**. Docker is not installed
on the machine that builds this repo, so a test that needs PostgreSQL, Qdrant or
Redis to be up cannot be verified and will be rejected. Use SQLite in-memory,
fakes, or mocked HTTP.

The one exception is `tests/live`, which checks the provider adapters against
the real services. Those tests are marked `live`, are left out of a plain
`pytest`, and skip any provider whose key is not in the environment; run them
with `pytest -m live tests/live` (see the README). They are an extra check,
never a substitute for the mocked tests.

## Secrets

Never hardcode an API key, and never log one. Provider keys are encrypted at
rest and are masked in every API response.
