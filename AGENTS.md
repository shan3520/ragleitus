# Conventions for agents working in this repo

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

**Do not create a `src/` directory.** Early on, two agents independently chose
two different roots, each passed the build, and the result was a codebase split
down the middle. That tree has since been consolidated into `app/`, and `src/`
is git-ignored so it cannot come back by accident.

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

## Secrets

Never hardcode an API key, and never log one. Provider keys are encrypted at
rest and are masked in every API response.
