# RAGForge

A workspace for Retrieval-Augmented Generation. Upload documents, chat with them
using the LLM provider of your choice (bring your own key), get answers with
page-level citations, and measure latency, token usage, cost and answer quality.

The design is in [`docs/SPEC.md`](docs/SPEC.md). This repository ships the
**API** (FastAPI, with Swagger UI), its **Celery worker** and the **web app**
(Next.js, in [`frontend/`](frontend)), with Docker Compose for all of it and an
optional monitoring stack. The decisions the spec left open, and the limits
that remain, are in [Assumptions and limits](#assumptions-and-limits).

## What it does

| Area | What you get |
|---|---|
| Accounts | Register and log in (argon2 password hashing, JWT). Every document, key, conversation and metric is private to its owner. |
| Providers (BYOK) | OpenAI, Anthropic, Google Gemini, Groq, OpenRouter, NVIDIA NIM, Together AI, Mistral AI, plus any self-hosted OpenAI-compatible server (Ollama, LM Studio, vLLM). Keys are checked against the provider before they are saved, encrypted at rest, and only ever returned masked. |
| Documents | Upload PDF, Markdown or text. Text is extracted and cleaned on upload, then chunked, embedded and stored in Qdrant in the background. Embeddings come from a local model, or from a provider with your own key. Re-index or delete at any time. |
| Chat | Hybrid retrieval (dense vectors + keyword search, merged with reciprocal rank fusion, optionally reranked), streamed answers over server-sent events, `[n]` citations resolved to document and page, conversation history. |
| Telemetry | Latency, time to first token, prompt/completion tokens and cost for every LLM call, summarised per model and per day, with CSV/JSON export. |
| Observability | Prometheus metrics, OpenTelemetry traces (to any OTLP backend and to Langfuse), JSON logs with trace ids, and an optional Prometheus + Alertmanager + Grafana + Jaeger stack with alert rules and a ready-made dashboard. |
| Prompts and experiments | A versioned prompt library you can chat with, and experiments that answer the same questions with several prompts, models and retrieval strategies and compare their quality, latency and cost (run as a LangGraph pipeline), with CSV/JSON export. |
| Evaluation | Scoring of any answer with RAGForge's own LLM judge, Ragas or DeepEval (on your own provider): faithfulness, answer relevancy, context precision, context recall (with a reference answer) and hallucination rate, plus lexical baselines. |

## Quick start with Docker Compose

Requires Docker with Compose v2.

```bash
cp .env.example .env
# Fill in JWT_SECRET, PROVIDER_KEY_SECRET and POSTGRES_PASSWORD. For example:
python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build
```

This starts PostgreSQL 16, Qdrant, Redis, the API, an indexing worker and the
web app. Migrations run automatically. Open <http://localhost:3000>, create an account, add a provider
key and upload a document. The interactive API is at <http://localhost:8000/docs>.

The API image includes the optional evaluators Ragas and DeepEval (1.6 GB).
For a slimmer image without them (870 MB), build with
`EVALUATOR_EXTRAS= docker compose up --build`, or set `EVALUATOR_EXTRAS=` in
`.env`; the app then offers only its built-in judge.

To add monitoring, start the `observability` profile:
`docker compose --profile observability up --build`. Grafana (with the RAGForge
dashboard) is at <http://localhost:3001>, Prometheus at <http://localhost:9090>,
Alertmanager at <http://localhost:9093> and Jaeger at <http://localhost:16686>;
see [Observability](#observability).

Unless you choose a provider for embeddings in Settings, the first document you
upload triggers a one-time download of the local embedding model (`BAAI/bge-small-en-v1.5`, about 70 MB, from Hugging Face). It is cached in
the `model-cache` volume.

## Quick start without Docker

Requires Python 3.11+. Nothing else needs to run: the defaults are a SQLite
file and an embedded Qdrant store in `./data/qdrant`.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # fill in JWT_SECRET and PROVIDER_KEY_SECRET
alembic upgrade head
uvicorn app.main:app --reload --no-proxy-headers
```

To try it offline, set `EMBEDDING_BACKEND=fake` (and `RERANK_BACKEND=fake`) in
`.env`. That uses a hashing embedder and a word-overlap reranker instead of the
real models, so retrieval quality is poor, but every feature works.

Then start the web app (Node.js 20.9+) in a second terminal:

```bash
cd frontend
npm install
npm run dev                     # http://localhost:3000, talks to the API on :8000
```

Set `API_URL` if the API is somewhere else.

## Walkthrough

In the web app: **Providers** → add a key, **Documents** → upload the files in
[`samples/`](samples), **Chat** → ask "What does error code E-4711 mean?". The
answer cites its passages; click a citation to open the passage, or
**Evaluate answer** to score it. **Telemetry** and **Evaluations** show the
numbers.

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
#    Self-hosted server instead (private addresses need ALLOW_PRIVATE_PROVIDER_URLS=true):
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
    browser[Browser] --> web[Next.js web app<br/>frontend/]
    web -->|/backend/* proxy, JWT| api[FastAPI routes<br/>app/api]
    swagger[Swagger UI / curl] -->|JWT| api
    api --> services[Services<br/>app/services]
    services --> pg[(PostgreSQL<br/>users, documents, chunks,<br/>conversations, telemetry,<br/>evaluations)]
    services --> qdrant[(Qdrant<br/>chunk vectors)]
    services --> embed[Embeddings<br/>local fastembed model,<br/>or a provider with the user's key]
    services --> llm[LLM providers<br/>user's own keys]

    subgraph Ingestion
      up[Upload] --> extract[Extract + clean<br/>PyMuPDF] --> store[(document text)]
      store -. job via Redis .-> worker[Celery worker] --> chunk[Chunk per page] --> vec[Embed] --> qdrant
    end

    subgraph Chat turn
      q[Question] --> dense[Dense search] & keyword[Keyword search<br/>PostgreSQL full-text]
      dense & keyword --> rrf[Reciprocal rank fusion] --> prompt[Numbered passages] --> gen[Stream answer] --> cite[Resolve n citations]
      gen --> tel[Telemetry]
    end

    subgraph Experiments
      run[Run] -. job via Redis .-> graph[LangGraph pipeline<br/>retrieve, prompt, generate,<br/>evaluate, record]
      graph --> evaluators[Evaluator<br/>built-in judge, Ragas, DeepEval]
    end

    subgraph Observability
      api & worker -->|METRICS_PORT| prom[(Prometheus)] --> grafana[Grafana]
      prom -->|alerts| am[Alertmanager] --> receivers[Your receivers]
      api & worker -->|OTLP| traces[Jaeger / any OTLP backend<br/>Langfuse]
    end
```

- **Layers.** Route handlers in `app/api` only parse requests and call services.
  Business logic lives in `app/services`, and tables in `app/models`
  (see [CONTRIBUTING.md](CONTRIBUTING.md)).
- **Where data lives.** Vectors live only in Qdrant, and each point carries only
  ids. Chunk text lives in the SQL `chunks` table. Every vector query is filtered
  by the owner's `user_id`. Each embedding model has its own collection, named
  after the model and its vector size.
- **Embeddings.** By default documents are embedded by a local model
  (fastembed, no key needed). In Settings → Embeddings a user can switch to one
  of their provider keys: OpenAI (`text-embedding-3-small`), Google Gemini
  (`gemini-embedding-001`), Mistral (`mistral-embed`), Together AI, NVIDIA NIM,
  or a self-hosted OpenAI-compatible server such as Ollama (any model it
  serves). Anthropic, Groq and OpenRouter offer no embeddings API.
  - A choice is checked with one embedding call before it is saved.
  - It applies to documents indexed from then on. Each document records the
    model its vectors were made with, and a question is embedded once per model
    in use, so documents made with different models are searched side by side.
    Settings shows how many documents use another model and re-indexes them on
    request.
  - If a provider can't be used when a question is asked (its key was deleted,
    the provider is down), those documents are still searched by keyword, and
    the answer says so. Indexing with an unusable choice fails with a message
    saying what to fix.
  - Embedding calls are recorded in telemetry (operation `embedding`) with
    their token counts and cost.
- **Indexing.** Upload extracts and cleans the text right away, so a bad file
  fails immediately. Chunking and embedding then run as a job that records
  `pending → indexing → ready | failed`. The cleaned pages are kept, so
  re-indexing never needs the original file.
  - With `TASK_QUEUE=celery` (Docker Compose) jobs go through Redis to Celery
    workers (`celery -A app.worker worker`); add workers with
    `docker compose up --scale worker=3`. With the default `inline`, the API
    runs them itself after responding, so local development needs no Redis.
  - Each run claims the document with a token. If a second run starts for the
    same document (Reindex during indexing, a job delivered twice), the newest
    one wins and the older one discards its chunks and vectors, so the index is
    never duplicated or left half-replaced.
  - Jobs lost to a crash, a restart or an unreachable Redis are picked up
    again. Workers acknowledge a job only after finishing it, so a job whose
    worker dies is delivered again. The API also checks every
    `INDEX_SWEEP_MINUTES` (default 5), and workers check when they start, for
    documents queued or indexing for longer than `INDEX_STALE_MINUTES`
    (default 60; keep it above your longest queue wait plus indexing time).
    An upload whose job could not reach Redis is retried at the next check. In
    inline mode the API re-queues every unfinished document when it starts,
    since its own jobs died with the previous process; inline mode is meant for
    a single API process.
  - `POST /api/documents/batch-status` reports how many of your documents are
    queued, indexing, ready or failed, with each one's status.
- **Retrieval.** Each question runs a dense search in Qdrant and a keyword
  search, and merges the two rankings with reciprocal rank fusion. Dense search
  finds passages that say the same thing in other words; keyword search finds
  exact names, codes and numbers that embeddings blur.
  - On PostgreSQL, keyword search runs in the database: each chunk has a
    generated `tsvector` column with a GIN index (migration 0025), so a question
    reads only the chunks that contain its terms. The question is parsed by
    the same PostgreSQL parser as the chunks, so versions (`3.2.1`), decimals,
    e-mail addresses, URLs and codes like `E-4711` match as written. Matches
    are ranked like BM25: any term matches, rare terms weigh more than common
    ones, and `ts_rank` with length normalisation scores how often a term
    appears. Common English words are left out of the query. The `simple`
    text search configuration lowercases without stemming, so it works the
    same in every language.
  - How rare a term is comes from the statistics PostgreSQL keeps on the
    column (`pg_stats`, refreshed by autovacuum), so weighting costs no extra
    query. These cover all users' chunks, as search engines do: the weights
    reflect how common a word is overall, never anyone's text, and results
    only ever include your own chunks.
  - On SQLite (local development and the tests) your chunks are scored with
    BM25 in memory, which is fine up to tens of thousands of chunks.
  - Only the passages that are returned are loaded from the database.
- **Reranking** (optional, off by default; Settings → Reranking or
  `PUT /api/settings/reranking`). A reranker reads the question together with
  each candidate passage and scores how well it answers it, which is sharper
  than comparing vectors but slower. When it is on, the best
  `RERANK_CANDIDATES` (default 20) fused passages are scored and the top ones
  are kept.
  - `local` runs a small cross-encoder on the server with fastembed
    (`LOCAL_RERANK_MODEL`, default `Xenova/ms-marco-MiniLM-L-6-v2`, about
    80 MB, downloaded on first use into `EMBEDDING_CACHE_DIR`).
  - A provider's rerank API with the user's own key: Together AI
    (`/v1/rerank`), NVIDIA NIM (`ai.api.nvidia.com/v1/retrieval/.../reranking`),
    or a self-hosted server with a Cohere-style `/rerank` endpoint (vLLM,
    Infinity, LocalAI). The choice is checked with a test call before it is
    saved, and every call is in telemetry as `rerank`.
  - If the reranker can't be used (key deleted, provider down), the passages
    keep their fused order and the answer says why.
  - Chat uses the setting; an experiment variant can be set to rerank or not,
    so the two can be compared on the same questions.
- **Web app.** `frontend/` is a Next.js App Router app. The browser only talks to
  its own origin: a route handler forwards `/backend/*` to `API_URL` at runtime
  (streaming, so chat tokens arrive as they are generated). No CORS setup is
  needed, and one build works against any API address.
- **Prompt library.** A user's own system prompts, versioned: saving changes
  adds a version and earlier ones stay as they were; prompts can be cloned. A
  template must contain `{context}` (the numbered passages) and may contain
  `{question}`. Chat can answer with any version (the prompt picker, or
  `prompt_version_id` on a message); the choice is kept for the conversation.
- **Experiments.** Questions (optionally with reference answers) and up to six
  variants, each a prompt, a provider and model, a retrieval strategy
  (`hybrid`, `dense` or `keyword`) and a number of passages.
  - A run answers every question with every variant through a LangGraph
    `StateGraph`: retrieve → assemble prompt → generate → evaluate → record
    (`app/services/experiment_runner.py`). It runs on the Celery worker (or in
    the API process with `TASK_QUEUE=inline`), on the user's own keys, and every
    call is recorded in telemetry.
  - Each result stores the answer, citations, the passages used, latency,
    tokens and cost, the LLM judge's scores (judged by each variant's own model
    unless a judge is chosen) and ROUGE-L against the reference answer.
  - Several answers are worked on at once: `concurrency` per experiment (1 to
    16, "Answers at once" in the form), `EXPERIMENT_CONCURRENCY` (default 4)
    when it isn't given. Each runs in its own thread with its own database
    session. A call that hits a provider's rate limit or a passing error (429,
    503, 529, ...) waits as the provider asks (`Retry-After`) or backs off, and
    is tried up to three more times; chat does not retry.
  - A failed call is recorded with its error and the run goes on. Running again
    replaces the results; a run lost with its worker can be restarted once it
    is older than `INDEX_STALE_MINUTES`.
  - The comparison averages each metric per variant and marks the variant that
    is strictly best at it (ties name none). `/export` gives every result as
    CSV (cells that a spreadsheet would run as formulas are escaped) or JSON;
    `/api/experiments/report` lists every experiment with its best variants.
  - The RAG flow in chat stays plain service code; LangGraph runs the
    experiment pipeline, where its graph of steps and conditional skips (a
    failed generation goes straight to recording) earns its place.
- **Evaluators.** An answer (in chat or in an experiment) is scored by one of
  three evaluators (`app/services/evaluators`), all judged by the user's own
  provider and model and all reporting the same metrics:
  - `builtin`: RAGForge's LLM judge, one call for all four metrics.
  - `ragas`: Ragas's faithfulness, answer relevancy (which also embeds, with the
    user's embedding model), context precision and context recall.
  - `deepeval`: DeepEval's faithfulness, answer relevancy, contextual
    precision (contextual relevancy without a reference answer), contextual
    recall and hallucination.
  - Ragas and DeepEval never call a model themselves: small adapters (a Ragas
    `InstructorBaseRagasLLM` and `BaseRagasEmbedding`, a DeepEval
    `DeepEvalBaseLLM`) route their prompts through our provider adapters and
    ask for JSON matching each prompt's schema, so keys, providers and
    telemetry work as for every other call. Their usage analytics are switched
    off, and DeepEval runs in plain LLM mode (nothing goes to Confident AI).
    They make several calls per answer, so they cost more than `builtin`.
  - They are optional extras (`pip install ".[ragas]"`, `".[deepeval]"`); the
    Docker image and `.[dev]` include both. Building the image with
    `EVALUATOR_EXTRAS=` leaves them out and roughly halves its size (see
    [Quick start](#quick-start-with-docker-compose)). `GET /api/evaluators`
    says which are installed, and the web app only offers those.
  - A metric an evaluator could not score is left empty (Ragas has no
    faithfulness for an answer that makes no claims). DeepEval 4's
    hallucination score measures agreement, so it is stored inverted.
- **Provider adapters.** These live in `app/services/llm`: one adapter for the
  OpenAI-compatible family, one for Gemini, and one using the official
  `anthropic` SDK. All stream text and report token usage the same way.

## Observability

- **Telemetry in the app.** Every LLM call (chat, evaluation, experiments,
  embeddings) is stored with its latency, time to first token, tokens and cost,
  and shown per model and per day on the Telemetry page.
  `GET /api/export/metrics?days=30&format=csv|json` exports a user's usage
  (totals, per model, per day), evaluation averages and activity counts.
- **Prometheus metrics** (`app/core/metrics.py`) on `METRICS_PORT`, a port of
  their own: the web app forwards `/backend/*` to the API, so a `/metrics` route
  there would be public. They cover:
  - requests and latency by route template;
  - LLM calls, latency, time to first token, tokens and cost by provider, model
    and operation;
  - index runs by outcome and duration;
  - retrieval latency by strategy;
  - documents waiting to be indexed.

  They carry no user ids or text, and the model label is bounded (self-hosted
  model names are one label). The Celery worker serves the metrics of all its
  child processes through Prometheus's multiprocess mode.
- **Traces** (`app/core/tracing.py`) are off until configured.
  `OTEL_EXPORTER_OTLP_ENDPOINT` sends them to any OTLP/HTTP backend (Jaeger,
  Tempo, an OpenTelemetry Collector).
  - `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` (plus `LANGFUSE_HOST` for a
    self-hosted Langfuse) send them to Langfuse's OTLP endpoint.
  - Requests get server spans. `rag.retrieve`, `rag.rerank`, `rag.generate`,
    `rag.evaluate`, `index.document` and each experiment step get their own
    spans, with the OpenTelemetry GenAI attributes (`gen_ai.system`, model,
    token usage) that Langfuse reads as generations, and the user and
    conversation as `user.id` and `session.id`.
  - Prompt and answer text are added only with `TRACE_CONTENT=true`; keys never
    are.
- **Logs** are JSON lines with every field a log call passes (request id, path,
  status, document id…) and the trace and span id of the active trace.
- **Monitoring stack.** `docker compose --profile observability up` adds:
  - Prometheus, scraping the API and every worker, with the alert rules in
    `docker/prometheus/alerts.yml`:

    | Alert | Fires when |
    |---|---|
    | `RagforgeApiDown`, `RagforgeWorkerDown` | no api (or worker) has answered a scrape for 2 minutes |
    | `RagforgeHighErrorRate` | over 5% of requests get a 5xx for 10 minutes |
    | `RagforgeSlowRequests` | a route's p95 is over 5 s for 10 minutes (routes that wait on an LLM excepted) |
    | `RagforgeLlmErrors` | over 20% of calls to a provider fail for 10 minutes |
    | `RagforgeIndexingFailures` | a document failed to index in the last 15 minutes |
    | `RagforgeIndexingStalled` | documents are waiting and none finished in 15 minutes |

  - Alertmanager (<http://localhost:9093>), which collects the alerts. To be
    notified (webhook, Slack, e-mail…), add a receiver to
    `docker/alertmanager/alertmanager.yml`; the file has examples.
  - Grafana, with Prometheus and Alertmanager data sources and a RAGForge
    dashboard: firing alerts, requests, errors, latency, LLM calls, cost,
    tokens and time to first token per model, indexing, retrieval and
    reranking. Grafana's Alerting page lists the rules.
  - Jaeger, keeping traces for 7 days on disk (the `jaeger-data` volume), so
    they survive restarts. Set `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318`
    in `.env` to send traces to it.

  Their ports are bound to `127.0.0.1`. The Grafana password is
  `GRAFANA_ADMIN_PASSWORD` (default `admin`).

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

Rate limiting (`RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_BURST`) counts signed-in
requests per user and other requests (login, register) per client address.
`X-Forwarded-For` and `X-Forwarded-Proto` are only believed from the reverse
proxies listed in `TRUSTED_PROXIES`; otherwise the connecting address is used.
Login attempts are also limited per account (`LOGIN_ATTEMPTS_PER_MINUTE`,
default 10), whatever address they claim to come from.

The limits are token buckets. With `RATE_LIMIT_BACKEND=redis` (Docker Compose)
they are kept in Redis (`REDIS_URL`), so every API process and host shares
them and the API can be scaled out. The default, `memory`, keeps them in each
process, which is enough for one process. If Redis can't be reached, each
process limits on its own until it can again, so requests are never let
through unlimited. A 429 response says in `Retry-After` when to try again.

To run several API containers with Docker Compose, drop the `api` service's
fixed host port (the web app reaches them by service name), for example with
a `docker-compose.override.yml` containing
`services: {api: {ports: !reset []}}`, then
`docker compose up --scale api=3`.

`docker compose` gives the web container a fixed address and trusts it, so
signed-out visitors get their own limits. The web app passes on an
`X-Forwarded-For` the browser sent itself, so that address can be forged; the
per-account login limit is what stops password guessing. With a reverse proxy
(nginx, a load balancer) in front of the web app, add its address to
`TRUSTED_PROXIES` together with the web container's.

Run uvicorn with `--no-proxy-headers` (the Docker image does). Without it,
uvicorn itself replaces the client address with the `X-Forwarded-For` value for
connections from `127.0.0.1`, before the app can check it.

Self-hosted providers (Ollama, LM Studio, vLLM) are added as `custom` with a
base URL. The server calls that URL, so by default it must be a public address;
set `ALLOW_PRIVATE_PROVIDER_URLS=true` to allow localhost, your LAN or other
containers. Error messages from a custom provider carry only the HTTP status,
never the response body.

Changing your password (`PATCH /auth/me/password`) signs out every existing
session and returns a new token.

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
| `GET/PUT /api/settings/embeddings`, `POST /api/settings/embeddings/reindex` | Embedding model |
| `GET/PUT /api/settings/reranking` | Reranker (`none`, `local` or a provider) |
| `POST/GET /api/prompts`, `GET/PATCH/DELETE /api/prompts/{id}`, `POST /api/prompts/{id}/versions`, `POST /api/prompts/{id}/clone`, `GET /api/prompts/default` | Prompt library |
| `POST/GET /api/experiments`, `GET/DELETE /api/experiments/{id}`, `POST /api/experiments/{id}/run`, `GET /api/experiments/{id}/compare`, `GET /api/experiments/{id}/export?format=csv\|json`, `GET /api/experiments/report` | Experiments |
| `POST/GET /api/conversations`, `GET/DELETE /api/conversations/{id}`, `POST /api/conversations/{id}/messages` | Chat |
| `GET /api/telemetry/summary`, `GET /api/telemetry/events`, `GET /api/export/metrics?format=json\|csv` | Telemetry and export |
| `POST /api/evaluations`, `GET /api/evaluations`, `GET /api/evaluators` | Evaluation |
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

A few tests also run against a real PostgreSQL when `TEST_POSTGRES_URL` points
at a database they may wipe; without it they are skipped:

```bash
docker run -d --name ragforge-test-pg -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=pw postgres:16-alpine
TEST_POSTGRES_URL=postgresql+psycopg://postgres:pw@127.0.0.1:55432/postgres pytest -q
```

Schema changes go through Alembic:

```bash
alembic revision -m "describe the change"   # write the migration by hand
alembic upgrade head
```

`tests/test_migrations.py` fails if the migrations and the models ever disagree.

### Frontend

```bash
cd frontend
npm run lint && npm run typecheck && npm test   # unit tests: Jest, no server needed
```

The end-to-end tests drive a real browser through sign-up, adding a key,
uploading the samples, a cited answer, evaluation, telemetry and a password
change. They use a stub OpenAI-compatible LLM (`frontend/e2e/stub-llm.mjs`, key
`stub-key`), so no real key is needed. Start the API with the fake embedder and
private provider URLs allowed (the stub runs on localhost), then build and run
the suite:

```bash
# terminal 1, repository root
EMBEDDING_BACKEND=fake ALLOW_PRIVATE_PROVIDER_URLS=true uvicorn app.main:app --no-proxy-headers

# terminal 2
cd frontend
npx playwright install chromium   # once
npm run build && npm run e2e      # starts the stub LLM and the web app itself
```

Against the Docker Compose stack instead, point the suite at it and let the API
container reach the stub on the host:
`E2E_BASE_URL=http://localhost:3000 E2E_LLM_URL=http://host.docker.internal:9999/v1 npm run e2e`
(the `api` service needs `ALLOW_PRIVATE_PROVIDER_URLS: "true"` and
`extra_hosts: ["host.docker.internal:host-gateway"]` on Linux).

## Assumptions and limits

The spec leaves these open; this is what RAGForge assumes:

- **Accounts are private.** Every document, key, prompt, experiment and metric
  belongs to one user; there are no teams or shared workspaces.
- **Evaluation runs on the user's own models.** The built-in judge, Ragas and
  DeepEval all use a provider key the user stored, so evaluating costs the user,
  like chatting does. Ragas and DeepEval make several calls per answer where
  the built-in judge makes one.
- **Each document has one embedding model**, the one the user had chosen when it
  was indexed. Changing the choice affects new documents until the old ones are
  re-indexed.
- **Keyword search is PostgreSQL full-text search** with the `simple`
  configuration (no stemming, works in any language). Term weights come from
  PostgreSQL's statistics over all users' chunks; results never cross users.
- **The task queue is Celery with Redis.** The `inline` mode, which needs no
  Redis, is for development and single-process installs.
- **Experiments share the user's provider limits.** Running several answers at
  once is faster, but a provider with a low rate limit answers with 429s that
  the run waits out; lower an experiment's concurrency for such a provider.
- **Monitoring is for whoever runs the server.** Alerts cover the service as a
  whole, never individual users, and Alertmanager notifies no one until a
  receiver is configured.
- **Redis holds the shared rate limits** when there are several API processes.
  Losing Redis loosens them to one allowance per process for the duration,
  rather than stopping the API.

What is still not there:

- **Tested against stand-ins, not every provider.** Provider adapters and
  embedders are tested against mocked HTTP and a stub OpenAI-compatible server
  (the browser tests use it); they follow each provider's published API but
  have not all been exercised against the real services here.

## License

Licensed under the [Apache License 2.0](LICENSE).
