# ARCHITECTURE — `ai-news-service`

> **Version:** 1.0.0  
> **Framework:** FastAPI (Python 3.12)  
> **Purpose:** AI-powered crime news aggregation, classification, and ranked feed delivery for India.

---

## Table of Contents

1. [Service Overview](#1-service-overview)
2. [Core Responsibilities](#2-core-responsibilities)
3. [Internal Module Structure](#3-internal-module-structure)
4. [API Endpoints](#4-api-endpoints)
5. [Request Processing Flow](#5-request-processing-flow)
6. [External Dependencies](#6-external-dependencies)
7. [Data Flow](#7-data-flow)
8. [Tech Stack](#8-tech-stack)
9. [Deployment Details](#9-deployment-details)
10. [Mermaid Diagrams](#10-mermaid-diagrams)

---

## 1. Service Overview

`ai-news-service` is a standalone FastAPI microservice that forms the intelligence core of a crime news aggregation platform targeting Indian audiences. It fetches raw news from RSS feeds and REST APIs, applies a multi-stage AI processing pipeline to classify, rewrite, and score articles, enriches them with web-search reference links, and exposes a ranked, time-decayed public feed updated every 5 minutes.

The service operates **autonomously** via an internal APScheduler and also exposes **admin-facing HTTP endpoints** for manual triggering and configuration management. All non-public endpoints are protected by a shared internal secret header (`x-internal-secret`), making the service designed to operate exclusively behind an API Gateway and never be exposed directly to end users.

---

## 2. Core Responsibilities

| Responsibility | Description |
|---|---|
| **News Ingestion** | Fetches raw articles from configured RSS and REST sources on a 5-minute schedule |
| **Deduplication** | SHA-256 content hashing per `(source_id, payload)` prevents reprocessing identical articles |
| **Keyword Pre-filter** | Fast in-process regex scan eliminates non-crime articles before any AI call |
| **AI Classification** | Calls a pluggable LLM provider to determine if an article is crime-related, classify by category, and produce a 1–100 importance score |
| **Content Rewriting** | AI rewrites titles and descriptions to be publication-ready, neutral, and non-verbatim |
| **Category Resolution** | Maps AI-returned string labels (`"murder"`, `"fraud"`) to integer FK IDs in the database |
| **Location Tagging** | Resolves free-text location strings to State FK IDs |
| **Search Enrichment** | Calls Google Custom Search API once per article to populate `reference_urls` |
| **Publishing / Ranking** | Selects top-N articles by `imp_score × time_decay_factor` and upserts them into the public feed table |
| **Rate Limiting** | Per-provider async rate limiter + semaphore protects cloud API quotas (Gemini, Anthropic, OpenAI) and GPU thermal limits (Ollama) |
| **Internal Auth** | Enforces `x-internal-secret` on all non-public endpoints via Starlette middleware |

---

## 3. Internal Module Structure

```
ai-news-service/
├── app/
│   ├── main.py                         # FastAPI app factory, router registration, lifespan hooks
│   ├── core/
│   │   ├── config.py                   # Pydantic Settings — reads from .env
│   │   ├── database.py                 # Async SQLAlchemy engine + session factory
│   │   ├── deps.py                     # FastAPI dependency injection wiring
│   │   └── enums.py                    # CategoryEnum, SubCategoryEnum, AI→DB string maps
│   ├── middleware/
│   │   └── internal_auth.py            # InternalServiceMiddleware (x-internal-secret gate)
│   ├── api/
│   │   ├── routes_ingest.py            # POST /ingest/ — manual pipeline trigger
│   │   ├── routes_sources.py           # CRUD /sources/
│   │   ├── routes_ai_providers.py      # CRUD + activation /ai-providers/
│   │   ├── routes_raw_ingestion.py     # Read-only /raw-ingestion/ (pipeline audit)
│   │   ├── routes_filter_articles.py   # Read-only /filter-articles/ (stage 1 output)
│   │   ├── routes_post_processed.py    # Read-only /post-processed/ (stage 2 output)
│   │   ├── routes_final_articles.py    # Feed GET + manual publish trigger
│   │   └── routes_master_data.py       # Read-only categories, sub-categories, states
│   ├── models/
│   │   ├── base.py                     # DeclarativeBase
│   │   ├── source.py                   # news_sources table
│   │   ├── raw_event.py                # raw_ingestion table (pipeline inbox)
│   │   ├── filter_article.py           # filtered_articles table (stage 1)
│   │   ├── post_processed_article.py   # post_processed_articles table (stage 2)
│   │   ├── final_article.py            # final_articles table (public feed)
│   │   ├── ai_provider.py              # ai_provider_configs table
│   │   ├── category.py                 # master_category / master_sub_category tables
│   │   └── location.py                 # state table
│   ├── schemas/
│   │   ├── article_schema.py           # Pydantic I/O models for pipeline stages
│   │   ├── source_schema.py
│   │   ├── ai_provider_schema.py
│   │   ├── final_article_schema.py
│   │   └── master_data_schema.py
│   ├── repositories/
│   │   ├── source_repo.py
│   │   ├── raw_ingestion_repo.py       # Includes content_hash deduplication
│   │   ├── filter_article_repo.py
│   │   ├── post_processed_article_repo.py
│   │   ├── final_article_repo.py
│   │   ├── master_data_repo.py
│   │   └── ai_provider_repo.py
│   └── services/
│       ├── ingestion_service.py        # Orchestrates the full per-source pipeline
│       ├── publishing_service.py       # Rank scoring + final feed upsert
│       ├── search_enrichment_service.py# Google Search reference URL population
│       ├── scheduler.py                # APScheduler: ingestion + publishing jobs
│       ├── source_normalizer.py        # Normalizes RSS/REST payloads to plain dicts
│       ├── google_search_service.py    # Google Custom Search API client
│       ├── fetchers/
│       │   ├── rss_fetcher.py          # feedparser-based async RSS fetcher
│       │   └── rest_fetcher.py         # httpx-based async REST fetcher
│       └── normalization/
│           ├── ai_processor.py         # Env-variable fallback provider resolution
│           ├── provider_factory.py     # Factory + module-level provider cache
│           ├── canonical_validator.py  # Validates AI output schema
│           ├── resolvers.py            # CategoryResolver + LocationResolver
│           └── providers/
│               ├── base.py             # AIProvider ABC + SINGLE_PROCESS_PROMPT + output parser
│               ├── anthropic_prov.py   # Claude (Haiku/Sonnet/Opus)
│               ├── openai_prov.py      # GPT-4o / OpenAI-compatible (Ollama, vLLM, etc.)
│               ├── gemini_langgraph_prov.py     # Gemini + LangGraph agent
│               ├── gemini_multimodal_prov.py    # Gemini multimodal (RECOMMENDED)
│               └── aws_bedrock_prov.py          # AWS Bedrock (Llama 3, etc.)
├── migrations/                         # Alembic migrations
│   └── versions/
├── alembic.ini
├── .python-version                     # Python 3.12
└── .env                                # Runtime secrets (not committed)
```

---

## 4. API Endpoints

All endpoints require the `x-internal-secret` header unless listed as **Public**.

### Feed

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/final-articles/` | Public | Ranked crime news feed ordered by `rank_score` desc. Supports `limit`, `offset`, `sub_category_id`, `q` |
| `GET` | `/final-articles/{id}` | Public | Single ranked article by ID |
| `POST` | `/final-articles/publish` | Internal | Force immediate re-ranking and feed refresh; `top_n` query param |

### Pipeline Inspection (Read-Only)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/raw-ingestion/` | Internal | List raw ingestion inbox; filter by `status`, `source_id` |
| `GET` | `/raw-ingestion/{id}` | Internal | Single raw row including full `raw_payload` JSON |
| `GET` | `/filter-articles/` | Internal | Stage-1 AI-filtered articles; filter by `sub_category_id`, `q` |
| `GET` | `/filter-articles/{id}` | Internal | Single filtered article |
| `GET` | `/post-processed/` | Internal | Stage-2 AI-enriched articles; filter by `sub_category_id`, `q`, `from_date`, `to_date` |
| `GET` | `/post-processed/{id}` | Internal | Single post-processed article |

### Admin — Sources

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/sources/` | Internal | Register a new RSS or REST source |
| `GET` | `/sources/` | Internal | List all sources (`include_inactive` flag) |
| `GET` | `/sources/{id}` | Internal | Get source by ID |
| `PATCH` | `/sources/{id}` | Internal | Partial update (e.g. pause with `is_active: false`) |
| `DELETE` | `/sources/{id}` | Internal | Permanently delete a source |

### Admin — Ingestion

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/ingest/` | Internal | Trigger full pipeline immediately for a given `source_id` |

### Admin — AI Providers

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/ai-providers/` | Internal | Register a new AI provider config (starts inactive) |
| `GET` | `/ai-providers/` | Internal | List all registered providers (API keys never returned) |
| `GET` | `/ai-providers/active` | Internal | Get the currently active provider |
| `GET` | `/ai-providers/{id}` | Internal | Get provider by ID |
| `PATCH` | `/ai-providers/{id}/activate` | Internal | Activate a provider (deactivates all others) |
| `DELETE` | `/ai-providers/active` | Internal | Deactivate all providers (falls back to env vars) |
| `DELETE` | `/ai-providers/{id}` | Internal | Delete a provider config |

### Master Data

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/master/categories/` | Internal | List crime categories |
| `GET` | `/master/categories/{id}` | Internal | Single category |
| `GET` | `/master/sub-categories/` | Internal | List sub-categories; filter by `category_id` |
| `GET` | `/master/sub-categories/{id}` | Internal | Single sub-category |
| `GET` | `/master/states/` | Internal | List states; filter by `country_id` |
| `GET` | `/master/states/{id}` | Internal | Single state |

### Health

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | Public | Returns `{"status": "ok"}` |
| `GET` | `/` | Public | Returns welcome message + docs link |

---

## 5. Request Processing Flow

### Scheduled Ingestion Flow (Automatic — every 5 minutes)

```
APScheduler
  └── run_ingestion_for_all_active_sources()
        ├── Load all active sources from DB
        └── For each source → _ingest_one_source(source)
              └── IngestionService.ingest(source)
                    1. Fetch raw items (RSS or REST)
                    2. Load active AI provider (DB config → env fallback)
                    3. Cap items to provider's max_items_per_run
                    4. Compute SHA-256 content hashes
                    5. store_batch → dedup against raw_ingestion table
                    6. Keyword pre-filter (_has_crime_keywords)
                    7. Async AI processing (rate limiter + semaphore)
                    8. Parse + validate AI output (SingleOutput Pydantic model)
                    9. Resolve category/sub-category IDs (CategoryResolver)
                   10. Resolve location → State FK (LocationResolver)
                   11. Bulk insert → filtered_articles
                   12. Bulk insert → post_processed_articles
                   13. Update raw_ingestion statuses (filtered / filtered_out / failed)
  └── run_search_enrichment()
        └── SearchEnrichmentService.enrich()
              ├── Fetch unenriched articles (reference_urls IS NULL)
              └── For each → Google Custom Search → update reference_urls
  └── run_publishing()
        └── PublishingService.publish(top_n=20)
              ├── Get top-N articles by imp_score
              ├── Compute rank_score = imp_score × time_decay_factor
              └── Upsert → final_articles
```

### Manual API Request Flow (e.g., `POST /ingest/`)

```
Client
  └── HTTP POST /ingest/ {source_id: 2}
        └── InternalServiceMiddleware
              ├── Check x-internal-secret header
              └── (valid) → forward to route handler
                    └── trigger_ingest()
                          ├── SourceRepository.get_by_id(2)
                          └── IngestionService.ingest(source)
                                └── (same pipeline as scheduled flow above)
```

### Time Decay Scoring

The `PublishingService` applies a time-decay multiplier when computing `rank_score`:

| Article Age | Decay Factor |
|---|---|
| < 6 hours | 1.00 (fresh) |
| 6–24 hours | 0.75 |
| 24–72 hours | 0.50 |
| 72–168 hours | 0.25 |
| > 168 hours | 0.10 |

`rank_score = imp_score × decay_factor`

---

## 6. External Dependencies

### Infrastructure

| Dependency | Role | Notes |
|---|---|---|
| **PostgreSQL** | Primary database | Async access via `asyncpg`. Tables: `news_sources`, `raw_ingestion`, `filtered_articles`, `post_processed_articles`, `final_articles`, `ai_provider_configs`, `master_*`, `state` |
| **API Gateway** | Request routing + TLS termination | Routes external traffic; passes `x-internal-secret` header to this service |
| **Auth Service** | Identity validation | Upstream of API Gateway; JWT/session validation happens before requests reach this service |

### AI Providers (pluggable — one active at a time)

| Provider | Identifier | Notes |
|---|---|---|
| **Google Gemini Multimodal** | `gemini_multimodal` | Recommended. Multimodal, structured output, multi-label classification |
| **Google Gemini + LangGraph** | `gemini_langgraph` | Gemini with LangGraph agent and DuckDuckGo search |
| **Anthropic Claude** | `anthropic` | Claude Haiku / Sonnet / Opus via Anthropic SDK |
| **OpenAI** | `openai` | GPT-4o / GPT-4o-mini |
| **AWS Bedrock** | `aws_bedrock` | Llama 3 and other Bedrock-hosted models |
| **Ollama** | `ollama` | Local GPU inference (Qwen3 default); no API key; single-GPU concurrency enforced |
| **Custom / vLLM** | `custom` | Any OpenAI-compatible endpoint |

Provider selection priority: **DB-configured active provider → `OLLAMA_MODEL` env → `GEMINI_API_KEY` env → `ANTHROPIC_API_KEY` env**

### Third-Party APIs

| Service | Usage | Quota / Notes |
|---|---|---|
| **Google Custom Search API** | Populates `reference_urls` on post-processed articles | 100 queries/day free tier; `GOOGLE_SEARCH_MAX_PER_RUN` caps spend per cycle; each article searched exactly once |

---

## 7. Data Flow

### Pipeline Tables (Left → Right = processing stages)

```
news_sources
     │
     ▼  (RSSFetcher / RestFetcher)
raw_ingestion          ← SHA-256 dedup | status: pending → filtered / filtered_out / failed
     │
     │  keyword pre-filter + AI classification
     ▼
filtered_articles      ← crime-positive articles; category_ids[], sub_category_ids[] as JSONB
     │
     │  AI rewrite + imp_score + location resolution
     ▼
post_processed_articles ← rewritten title/description; imp_score; reference_urls (ARRAY)
     │
     │  SearchEnrichmentService (Google Search, once per article)
     │
     │  PublishingService: imp_score × time_decay → rank_score
     ▼
final_articles          ← public feed; ordered by rank_score DESC
```

### Article Status Lifecycle (`raw_ingestion.status`)

```
pending → (keyword pre-filter fails) → filtered_out
        → (AI says not crime)        → filtered_out
        → (AI succeeds, is crime)    → filtered  (after filter_articles insert)
        → (AI call fails)            → failed
```

### AI Provider Switching (Zero-Downtime)

```
Admin: PATCH /ai-providers/{id}/activate
           │
           ▼
  ai_provider_configs: all rows is_active=false
                       target row is_active=true
           │
           ▼
  Next ingestion run: IngestionService loads new config
  Provider factory cache: keyed on (config.id, model, api_key)
                          → fresh client for new config
                          → stale entries GC'd on restart
```

---

## 8. Tech Stack

| Layer | Technology | Version / Notes |
|---|---|---|
| **Language** | Python | 3.12 |
| **Web Framework** | FastAPI | Async, OpenAPI auto-docs at `/docs` |
| **ASGI Server** | Uvicorn | Production deployment |
| **ORM** | SQLAlchemy (async) | `asyncpg` driver |
| **DB Migrations** | Alembic | `migrations/versions/` |
| **Database** | PostgreSQL | JSONB for payloads, ARRAY(Text) for reference URLs |
| **Scheduling** | APScheduler (`AsyncIOScheduler`) | Ingestion every 5 min; publishing every 5 min (+30s offset) |
| **HTTP Client** | httpx (async) | REST fetcher + AI provider HTTP calls |
| **RSS Parsing** | feedparser | RSS/Atom feed ingestion |
| **Config** | pydantic-settings | `.env` → typed `Settings` object |
| **AI — Anthropic** | `anthropic` SDK | Claude family |
| **AI — Google** | `google-generativeai` + LangGraph | Gemini multimodal + agent pipelines |
| **AI — OpenAI** | `openai` SDK | GPT-4o / Ollama-compatible |
| **AI — AWS** | `boto3` (1.42.73) | Bedrock invocation |
| **Linting / Formatting** | `ruff`, `black` | Dev tooling |
| **Testing** | `pytest` | Unit + integration tests |

---

## 9. Deployment Details

### Environment Variables (`.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | ✅ | — | Async PostgreSQL DSN (`postgresql+asyncpg://...`) |
| `INTERNAL_SERVICE_SECRET` | ✅ | — | Shared secret for `x-internal-secret` header |
| `AWS_ACCESS_KEY_ID` | ✅ | — | AWS credentials for Bedrock |
| `AWS_SECRET_ACCESS_KEY` | ✅ | — | AWS credentials for Bedrock |
| `AWS_DEFAULT_REGION` | ✅ | — | AWS region |
| `ANTHROPIC_API_KEY` | ⚡ | `None` | Env fallback if no DB provider active |
| `GEMINI_API_KEY` | ⚡ | `None` | Env fallback (priority over Anthropic) |
| `OLLAMA_URL` | — | `http://localhost:11434/v1` | Local Ollama base URL |
| `OLLAMA_MODEL` | — | `None` | Env fallback for Ollama |
| `GOOGLE_SEARCH_API_KEY` | — | `None` | Enables reference URL enrichment |
| `GOOGLE_SEARCH_ENGINE_ID` | — | `None` | Custom Search Engine ID |
| `INGEST_INTERVAL_MINUTES` | — | `5` | Scheduler: ingestion frequency |
| `PUBLISH_INTERVAL_MINUTES` | — | `5` | Scheduler: publishing frequency |
| `FEED_TOP_N` | — | `20` | Articles in public feed |
| `CLOUD_REQUESTS_PER_MINUTE` | — | `3` | RPM for cloud AI providers |
| `CLOUD_MAX_ITEMS_PER_RUN` | — | `5` | Articles per run for cloud providers |
| `OLLAMA_REQUESTS_PER_MINUTE` | — | `60` | RPM for local Ollama |
| `OLLAMA_MAX_ITEMS_PER_RUN` | — | `50` | Articles per run for Ollama |
| `OLLAMA_CONCURRENCY` | — | `1` | GPU concurrency cap |
| `OLLAMA_BATCH_SIZE` | — | `10` | Batch size before GPU cooldown |
| `OLLAMA_BATCH_COOLDOWN_SECONDS` | — | `15.0` | Pause between GPU batches |
| `DEBUG` | — | `False` | Enables SQLAlchemy echo |

### Process & Server

- Entry point: `uvicorn app.main:app`
- Lifespan hooks start APScheduler on startup and stop it on shutdown
- Database connection pool: `pool_size=10`, `max_overflow=20`
- CORS: `allow_origins=["*"]` (API Gateway handles origin restriction)
- All non-public routes protected by `InternalServiceMiddleware` via `x-internal-secret`

### Database Migrations

```bash
alembic upgrade head     # Apply all migrations
alembic revision --autogenerate -m "description"  # Generate new migration
```

### Health Check

`GET /health` — returns `{"status": "ok"}`, no authentication required. Suitable for load-balancer probes.

### Scaling Considerations

- The service is **stateless** (aside from the module-level provider cache); multiple replicas can run behind a load balancer
- APScheduler runs **in-process** — if running multiple replicas, use `max_instances=1` per job (already set) and consider externalizing the scheduler (e.g., to a dedicated worker pod) to prevent duplicate ingestion runs
- The rate limiter cache (`_limiter_cache`) is process-local; each replica maintains its own limits independently

---

