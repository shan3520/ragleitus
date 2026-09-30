# RAGForge

A backend for Retrieval-Augmented Generation. Upload documents, chat with them
using the LLM provider of your choice (bring your own key), get answers with
page-level citations, and measure latency, token usage, cost and answer quality.

The target design is in [`docs/SPEC.md`](docs/SPEC.md). This repository
currently ships the **backend** (REST API with Swagger UI). The web frontend is
not built yet; see [What is not done yet](#what-is-not-done-yet).

## What it does

| Area | What you get |
|---|---|
| Accounts | Register and log in (argon2 password hashing, JWT). Every document, key, conversation and metric is private to its owner. |
| Providers (BYOK) | OpenAI, Anthropic, Google Gemini, Groq, OpenRouter, NVIDIA NIM, Together AI, Mistral AI, plus any self-hosted OpenAI-compatible server (Ollama, LM Studio, vLLM). Keys are checked against the provider before they are saved, encrypted at rest, and only ever returned masked. |
| Documents | Upload PDF, Markdown or text. Text is extracted and cleaned on upload, then chunked, embedded and stored in Qdrant in the background. Re-index or delete at any time. |
| Chat | Hybrid retrieval (dense vectors + BM25, merged with reciprocal rank fusion), streamed answers over server-sent events, `[n]` citations resolved to document and page, conversation history. |
| Telemetry | Latency, time to first token, prompt/completion tokens and cost for every LLM call, summarised per model and per day. |
| Evaluation | LLM-as-a-judge scoring of any answer: faithfulness, answer relevancy, context precision, context recall (with a reference answer) and hallucination rate, plus lexical baselines. |

## Quick start with Docker Compose

Requires Docker with Compose v2.

```bash
cp .env.example .env
# Fill in JWT_SECRET, PROVIDER_KEY_SECRET and POSTGRES_PASSWORD. For example:
python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build
```

This starts PostgreSQL 16, Qdrant and the API. Migrations run automatically.
Open <http://localhost:8000/docs> for the interactive API.

The first document you upload triggers a one-time download of the embedding
model (`BAAI/bge-small-en-v1.5`, about 70 MB, from Hugging Face). It is cached in
the `model-cache` volume.

## Quick start without Docker

Requires Python 3.11+. Nothing else needs to run: the defaults are a SQLite
file and an embedded Qdrant store in `./data/qdrant`.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # fill in JWT_SECRET and PROVIDER_KEY_SECRET
alembic upgrade head
uvicorn app.main:app --reload
```

To try it offline, set `EMBEDDING_BACKEND=fake` in `.env`. That uses a hashing
embedder instead of the real model, so retrieval quality is poor, but every
feature works.

## Walkthrough

The same flow works in the Swagger UI. With `curl`:

```bash
API=http://localhost:8000

# 1. Create an account and log in
curl -s -X POST $API/auth/register -H 'Content-Type: application/json' \
  -d '{"username": "ada", "password": "correct-horse-battery"}'
TOKEN=$(curl -s -X POST $API/auth/login -H 'Content-Type: application/json' \
  -d '{"username": "ada", "password": "correct-horse-battery"}' | python -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

# 2. Add a provider key (checked against the provider, stored encrypted)
curl -s -X POST $API/api/provider-keys -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"provider": "anthropic", "key": "sk-ant-..."}'
#    Self-hosted server instead:
#    -d '{"provider": "custom", "key": "none", "base_url": "http://localhost:11434/v1"}'

# 3. Upload the sample documents and wait for status "ready"
curl -s -X POST $API/api/documents -H "$AUTH" -F file=@samples/roboarm-x2-faq.pdf
curl -s -X POST $API/api/documents -H "$AUTH" -F file=@samples/employee-handbook.md
curl -s $API/api/documents -H "$AUTH"

# 4. Start a conversation and ask a question (streamed as server-sent events)
CONV=$(curl -s -X POST $API/api/conversations -H "$AUTH" -H 'Content-Type: application/json' -d '{}' \
  | python -c 'import sys,json; print(json.load(sys.stdin)["id"])')
curl -N -X POST $API/api/conversations/$CONV/messages -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"content": "What does error code E-4711 mean?"}'
#    Events: sources -> token ... -> citations -> done (usage, cost, latency)
#    Add "stream": false for a single JSON response.

# 5. Evaluate the answer (use the message_id from the "done" event)
curl -s -X POST $API/api/evaluations -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"message_id": 2, "reference_answer": "Joint-3 encoder lost calibration."}'

# 6. Look at the numbers
curl -s "$API/api/telemetry/summary?days=7" -H "$AUTH"
curl -s $API/api/evaluations -H "$AUTH"
```

## Architecture

```mermaid
flowchart LR
    client[Client / Swagger UI] -->|JWT| api[FastAPI routes<br/>app/api]
    api --> services[Services<br/>app/services]
    services --> pg[(PostgreSQL<br/>users, documents, chunks,<br/>conversations, telemetry,<br/>evaluations)]
    services --> qdrant[(Qdrant<br/>chunk vectors)]
    services --> embed[fastembed<br/>local ONNX model]
    services --> llm[LLM providers<br/>user's own keys]

    subgraph Ingestion
      up[Upload] --> extract[Extract + clean<br/>PyMuPDF] --> store[(document text)]
      store -. background task .-> chunk[Chunk per page] --> vec[Embed] --> qdrant
    end

    subgraph Chat turn
      q[Question] --> dense[Dense search] & bm25[BM25]
      dense & bm25 --> rrf[Reciprocal rank fusion] --> prompt[Numbered passages] --> gen[Stream answer] --> cite[Resolve n citations]
      gen --> tel[Telemetry]
    end
```

- **Layers.** Route handlers in `app/api` only parse requests and call services.
  Business logic lives in `app/services`, and tables in `app/models`
  (see [AGENTS.md](AGENTS.md)).
- **Where data lives.** Vectors live only in Qdrant, and each point carries only
  ids. Chunk text lives in the SQL `chunks` table. Every vector query is filtered
  by the owner's `user_id`.
- **Indexing.** Upload extracts and cleans the text right away, so a bad file
  fails immediately. Chunking and embedding then run as a background task that
  records `pending → indexing → ready | failed`. The cleaned pages are kept, so
  re-indexing never needs the original file.
- **Provider adapters.** These live in `app/services/llm`: one adapter for the
  OpenAI-compatible family, one for Gemini, and one using the official
  `anthropic` SDK. All stream text and report token usage the same way.

## Configuration

Settings are environment variables (or `.env`). [`.env.example`](.env.example)
lists them all. Only these are required:

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | Signs login tokens. At least 32 characters. The app refuses to start without it. |
| `PROVIDER_KEY_SECRET` | Encrypts stored provider keys. Changing it makes stored keys unreadable. |
| `POSTGRES_PASSWORD` | Only for `docker compose`. |

`DATABASE_URL` accepts any SQLAlchemy URL. PostgreSQL uses
`postgresql+psycopg://user:pass@host/db`. `VECTOR_STORE_URL` takes a Qdrant URL,
a local directory, or `:memory:`.

Cost estimates use the table in
[`app/services/llm/pricing.py`](app/services/llm/pricing.py) (USD per million
tokens). Models that are not listed get no cost rather than a guess, and are
counted as `unpriced_requests` in the telemetry summary.

## API overview

| Endpoint | |
|---|---|
| `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `PATCH /auth/me/password` | Accounts |
| `GET /api/providers`, `POST/GET/DELETE /api/provider-keys`, `POST /api/provider-keys/{provider}/validate` | Providers and keys |
| `POST /api/documents`, `GET /api/documents[/{id}]`, `POST /api/documents/{id}/reindex`, `DELETE /api/documents/{id}` | Documents |
| `POST/GET /api/conversations`, `GET/DELETE /api/conversations/{id}`, `POST /api/conversations/{id}/messages` | Chat |
| `GET /api/telemetry/summary`, `GET /api/telemetry/events` | Telemetry |
| `POST /api/evaluations`, `GET /api/evaluations` | Evaluation |
| `GET /health`, `GET /api/health/subsystems` | Health (no login needed) |

Analytics endpoints predate the chat flow and are scoped to the logged-in user:
search statistics, unanswered queries, feedback, history, groups and saved
searches. They are all listed in `/docs`.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

The tests need no external services and no network. They use SQLite, an
in-process Qdrant, a fake embedder and mocked HTTP. `tests/conftest.py` blocks
outbound connections, so a test that tries to reach a real provider fails.
Schema changes go through Alembic:

```bash
alembic revision -m "describe the change"   # write the migration by hand
alembic upgrade head
```

`tests/test_migrations.py` fails if the migrations and the models ever disagree.

## What is not done yet

`docs/SPEC.md` describes more than this backend. Still to build:

- **Frontend.** The Next.js app (dashboard, chat, documents, providers, prompt
  library, experiments, telemetry, evaluations, settings pages). The API is ready
  for it.
- **Task queue.** Indexing runs as an in-process background task. Moving it to
  Celery + Redis means wrapping `app.services.ingestion.index_document`, which
  already opens its own session. Until then, an API restart during indexing
  leaves the document `pending` or `indexing`, and `POST .../reindex` recovers it.
- **Prompt library and experiments.** Saving and versioning prompts, and
  comparing prompts, models or retrieval strategies side by side.
- **Observability stack.** No Langfuse, OpenTelemetry, Prometheus or Grafana.
  Telemetry is stored in PostgreSQL and served by the API.
- **Evaluation frameworks.** No Ragas or DeepEval. Evaluation uses its own LLM
  judge with the same metric names.
- **Embeddings through a provider key.** Embeddings come from the local model for
  every user. Per-user embedding providers would need each document to record its
  embedding model.
- **LangGraph.** The RAG flow is plain service code; it does not need an agent
  graph yet.
- **Scale.** BM25 scores a user's chunks in memory on each question. That is fine
  up to tens of thousands of chunks per user; beyond that it needs a keyword
  index (e.g. PostgreSQL full-text search).

Some older endpoints still return placeholder data: `/api/export/metrics`,
`/api/experiments/report` and `/api/documents/batch-status`.
