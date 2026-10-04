# RAGForge Product Specification

> Purpose: Build a production-quality AI engineering platform for
> Retrieval-Augmented Generation (RAG), multi-provider LLM
> experimentation, telemetry, and evaluation. This document
> intentionally specifies product decisions and leaves low-level
> implementation choices open.

------------------------------------------------------------------------

# 1. Product Vision

RAGForge is **not** a PDF chatbot. It is an AI engineering workspace
similar in spirit to LangSmith + Open WebUI + RAG Studio.

Primary goals: - Upload and manage knowledge bases. - Chat with
documents using RAG. - Support multiple LLM providers via BYOK. -
Compare prompts, models, and retrieval strategies. - Observe latency,
cost, and token usage. - Evaluate answer quality automatically.

------------------------------------------------------------------------

# 2. Locked Tech Stack

Backend - Python 3.12 - FastAPI - SQLAlchemy - PostgreSQL - Qdrant -
Redis - Celery - LangGraph

Frontend - Next.js - React - TypeScript - Tailwind CSS - shadcn/ui

Observability - Langfuse - OpenTelemetry - Prometheus - Grafana

Evaluation - Ragas - DeepEval

Deployment - Docker + Docker Compose

------------------------------------------------------------------------

# 3. Functional Features

Authentication - JWT authentication - Register/Login - Profile
management

Providers - BYOK - OpenAI - Gemini - Anthropic - Groq - OpenRouter -
NVIDIA NIM - Together AI - Mistral AI

Documents - PDF upload - Background indexing - Re-index - Delete -
Metadata

Chat - Streaming - Markdown - Code highlighting - Citations -
Conversation history

Prompt Library - Save prompts - Version prompts - Clone prompts

Experiments - Compare prompts - Compare models - Compare retrieval
strategies

Telemetry - Latency - Token usage - Cost - Provider/model - Errors

Evaluation - Faithfulness - Context Precision - Context Recall - Answer
Relevancy - Hallucination - LLM-as-a-Judge

------------------------------------------------------------------------

# 4. RAG Pipeline

1.  Upload PDF
2.  Extract text (PyMuPDF)
3.  Clean text
4.  Chunk
5.  Generate embeddings
6.  Store vectors in Qdrant
7.  Hybrid retrieval (Dense + BM25)
8.  Optional reranking
9.  Prompt assembly
10. LLM generation
11. Citations
12. Telemetry
13. Evaluation

------------------------------------------------------------------------

# 5. High-Level Architecture

Frontend → FastAPI → Authentication → Provider Manager → RAG
Orchestrator → Qdrant → LLM Provider → Telemetry → Evaluation →
PostgreSQL

------------------------------------------------------------------------

# 6. High-Level Data Model

Tables (agent may refine columns): - users - provider_keys - documents -
chunks - conversations - messages - prompts - experiments -
evaluations - telemetry_events - user_settings

Vectors belong in Qdrant, not PostgreSQL.

------------------------------------------------------------------------

# 7. REST APIs

Auth - POST /auth/register - POST /auth/login

Providers - CRUD provider keys - Validate key

Documents - Upload - List - Delete - Re-index

Document Search - GET /api/documents/search

Keyword search across the authenticated user's document titles and
chunk contents.

Query parameters: - q (required): keyword to search for - limit
(optional, default 10): maximum number of results to return - offset
(optional, default 0): number of results to skip before returning a
page

Response format (BREAKING CHANGE: this endpoint previously returned a
flat JSON array of match objects; it now returns a paginated object):

```
{
  "total": 42,
  "items": [
    {"document_id": 1, "title": "...", "score": 3.0, "snippet": "..."}
  ]
}
```

`total` is the number of matching documents regardless of paging;
`items` holds at most `limit` matches starting at `offset`, ordered by
descending relevance score. Clients that consumed the old flat array
must be updated to read `items`.

Chat - Start conversation - Continue conversation - Stream response

Experiments - Create - Compare - Export

Telemetry - Dashboard - Metrics

Evaluation - Run - History

------------------------------------------------------------------------

# 8. UI Pages

-   Dashboard
-   Chat
-   Documents
-   Providers
-   Prompt Library
-   Experiments
-   Telemetry
-   Evaluations
-   Settings

------------------------------------------------------------------------

# 9. Constraints

Must: - Use BYOK - Support multiple providers - Use Qdrant - Use
PostgreSQL - Docker Compose - Swagger/OpenAPI - Structured logging -
Clean Architecture - Repository + Service layers

Must not: - Hardcode API keys - Depend on one LLM provider - Mix
business logic into API routes - Store vectors in PostgreSQL

------------------------------------------------------------------------

# 10. Deliverables

-   Source code
-   Docker Compose
-   README
-   .env.example
-   API documentation
-   Tests
-   Sample data
-   Architecture diagram

------------------------------------------------------------------------

# 11. Acceptance Criteria

The project is complete when: - PDFs can be uploaded and indexed. -
Users can chat with citations. - Multiple providers are supported. -
BYOK works. - Telemetry dashboard shows latency, tokens, and cost. -
Evaluation metrics are available. - Docker Compose starts the
application. - Another developer can run the project from the README.

------------------------------------------------------------------------

# 12. Engineering Principles

-   Prefer maintainability over cleverness.
-   Keep the code modular.
-   Document assumptions in the README.
-   Produce production-quality code with meaningful tests and
    documentation.
