# Crime News API — Architecture Guide

> Complete reference for this codebase: every file, every layer, the full AI
> pipeline, and a step-by-step trace of every type of user request.

---

## Table of Contents

1. [What This App Does](#1-what-this-app-does)
2. [Tech Stack](#2-tech-stack)
3. [Project Structure — Every File Explained](#3-project-structure--every-file-explained)
4. [Database Schema](#4-database-schema)
5. [Pipeline — Bird's Eye View](#5-pipeline--birds-eye-view)
6. [Service Layer — Deep Dive](#6-service-layer--deep-dive)
7. [How the AI Works](#7-how-the-ai-works)
8. [Request Flows — End to End](#8-request-flows--end-to-end)
9. [API Reference & Usage Guide](#9-api-reference--usage-guide)
10. [Configuration Reference](#10-configuration-reference)
11. [Adding a New Provider](#11-adding-a-new-provider)

---

## 1. What This App Does

An **automated AI-powered crime news aggregator** for India.

Every 5 minutes the scheduler:
1. Fetches articles from all active RSS/REST sources
2. Deduplicates them by SHA-256 hash — the same article is never processed twice
3. Pre-filters using a ~50-keyword crime keyword list — skips ~70 % of articles from general sources (BBC, TOI) before any AI call
4. Sends remaining articles concurrently to the configured AI provider, which in a **single call**:
   - Decides if the article is crime-related (non-crime → discard immediately, near-zero tokens)
   - Extracts: original title, URL, description, image, published date
   - Rewrites the title and description in original words (plagiarism-safe)
   - Assigns an importance score 1–100 based on severity, scope, and public impact
   - Labels one or more crime sub-categories (murder, fraud, terrorism, …)
   - Resolves the location (city/state → Indian state DB FK)
5. Stores crime articles in two pipeline tables (`filtered_articles` → `post_processed_articles`)
6. Runs a publishing job every 5 minutes that picks the top 20 articles, applies time-decay, and upserts them into `final_articles` — the public ranked feed

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI (async) |
| ORM | SQLAlchemy 2.x async |
| Database | PostgreSQL |
| Migrations | Alembic |
| Scheduler | APScheduler (AsyncIOScheduler) |
| AI — primary | Gemini via OpenAI-compatible endpoint (`gemini` provider) |
| AI — multimodal | Gemini Flash via LangChain + LangGraph structured output (`gemini_multimodal`) |
| AI — langgraph | Gemini Flash via LangChain (`gemini_langgraph`) |
| AI — anthropic | Anthropic SDK (`anthropic`) |
| RSS fetching | feedparser (async) |
| REST fetching | httpx |
| Validation | Pydantic v2 |
| Settings | pydantic-settings |
| Python | 3.11+ (`.venv/bin/python3`) |

---

## 3. Project Structure — Every File Explained

```
app/
├── main.py                         # FastAPI app factory, router registration, lifespan
├── core/
│   ├── config.py                   # All settings read from .env (pydantic-settings)
│   ├── database.py                 # AsyncEngine + AsyncSessionLocal + get_db()
│   ├── deps.py                     # FastAPI dependency functions (wires repos + services)
│   └── enums.py                    # SubCategoryEnum, CategoryEnum, lookup dicts
│
├── models/                         # SQLAlchemy ORM table definitions
│   ├── base.py                     # DeclarativeBase
│   ├── source.py                   # news_sources table (Source model)
│   ├── raw_event.py                # raw_ingestion table (RawIngestion model)
│   ├── filter_article.py           # filtered_articles table (FilterArticle model)
│   ├── post_processed_article.py   # post_processed_articles table
│   ├── final_article.py            # final_articles table (public ranked feed)
│   ├── ai_provider.py              # ai_provider_configs table
│   ├── category.py                 # master_category + master_sub_category tables
│   └── location.py                 # country + state tables
│
├── repositories/                   # Data access layer — one class per table
│   ├── source_repo.py              # SourceRepository (CRUD for news_sources)
│   ├── raw_ingestion_repo.py       # RawIngestionRepository (store_batch, mark_*)
│   ├── filter_article_repo.py      # FilterArticleRepository (insert_batch, get_all)
│   ├── post_processed_article_repo.py  # PostProcessedArticleRepository (insert_batch, get_top)
│   ├── final_article_repo.py       # FinalArticleRepository (upsert_batch, get_feed)
│   ├── ai_provider_repo.py         # AIProviderRepository (CRUD + activate)
│   ├── master_data_repo.py         # MasterCategoryRepository, MasterSubCategoryRepository, StateRepository
│   └── article_repo.py             # Thin alias: ArticleRepository = PostProcessedArticleRepository
│
├── schemas/                        # Pydantic request/response models
│   ├── source_schema.py            # SourceCreate, SourceUpdate, SourceResponse
│   ├── article_schema.py           # FilterArticleResponse, PostProcessedArticleResponse, list wrappers
│   ├── final_article_schema.py     # FinalArticleResponse, FinalArticleListResponse
│   ├── ai_provider_schema.py       # AIProviderCreate, AIProviderResponse, AIProviderActivateResponse
│   └── master_data_schema.py       # MasterCategoryResponse, StateResponse
│
├── api/                            # HTTP route handlers
│   ├── routes_sources.py           # GET/POST/PATCH/DELETE /sources/
│   ├── routes_ingest.py            # POST /ingest/
│   ├── routes_filter_articles.py   # GET /filter-articles/
│   ├── routes_post_processed.py    # GET /post-processed/
│   ├── routes_final_articles.py    # GET /final-articles/, POST /final-articles/publish
│   ├── routes_ai_providers.py      # GET/POST/PATCH/DELETE /ai-providers/
│   └── routes_master_data.py       # GET /master/categories, /master/states
│
└── services/                       # Business logic layer
    ├── ingestion_service.py        # IngestionService — the main pipeline orchestrator
    ├── publishing_service.py       # PublishingService — ranking + feed refresh
    ├── scheduler.py                # APScheduler jobs (ingestion + publishing)
    ├── source_normalizer.py        # to_plain_dict(), parse_date() — feed-agnostic dict conversion
    ├── fetchers/
    │   ├── rss_fetcher.py          # RSSFetcher — async feedparser wrapper
    │   └── rest_fetcher.py         # RestFetcher — async httpx GET → list[dict]
    └── normalization/
        ├── ai_processor.py         # get_env_fallback_provider() — env-var AI resolution
        ├── provider_factory.py     # create_from_config(), process-lifetime provider cache
        ├── resolvers.py            # CategoryResolver, LocationResolver, load_resolvers()
        ├── canonical_validator.py  # URL and field sanitisation helpers
        └── providers/
            ├── base.py             # AIProvider ABC, SINGLE_PROCESS_PROMPT, parse_single_output()
            ├── openai_prov.py      # OpenAICompatibleProvider (OpenAI / Gemini / Ollama)
            ├── gemini_langgraph_prov.py      # GeminiLangGraphProvider (LangChain simple)
            ├── gemini_multimodal_prov.py     # GeminiMultimodalLangGraphProvider (RECOMMENDED)
            └── anthropic_prov.py   # AnthropicProvider (Claude)
```

---

## 4. Database Schema

### Table flow

```
news_sources
    │
    └─→ raw_ingestion          (every article ever seen; status tracks lifecycle)
            │
            └─→ filtered_articles        (AI-confirmed crime articles: extracted + scored)
                    │
                    └─→ post_processed_articles  (same data + rewritten content)
                                │
                                └─→ final_articles  (public ranked feed: top N by rank_score)
```

### Reference / lookup tables

```
master_category       (8 categories: Violent Crime, Financial Crime, …)
master_sub_category   (10 sub-categories: murder, theft, fraud, …)
country               (seeded once)
state                 (36 Indian states/UTs — used for location FK)
ai_provider_configs   (DB-managed AI provider credentials + active flag)
```

### Key columns

**`raw_ingestion`**

| Column | Type | Notes |
|---|---|---|
| content_hash | VARCHAR(64) UNIQUE | SHA-256 of `source_id + raw_payload` — deduplication key |
| source_id | FK → news_sources | |
| raw_payload | JSONB | full original article dict |
| status | VARCHAR | `pending` → `filtered` / `filtered_out` / `failed` |
| normalized_by | VARCHAR(200) | e.g. `ai:gemini_multimodal:gemini-2.0-flash` |
| processed_at | TIMESTAMP | |

**`filtered_articles`**

| Column | Type | Notes |
|---|---|---|
| raw_ingestion_id | FK → raw_ingestion | |
| title | TEXT | original headline from AI extraction |
| rewritten_title | TEXT | AI-rephrased headline |
| url | TEXT | canonical article URL |
| sub_category_id | FK → master_sub_category | primary crime type |
| sub_category_ids | JSONB | `[1, 4]` — multi-label int array |
| category_ids | JSONB | parent category IDs derived from sub_category_ids |
| location_state_id | FK → state | resolved from AI location string |
| location | TEXT | raw AI location string |
| region | VARCHAR | e.g. `south asia` |
| imp_score | INTEGER | 1–100 |

**`post_processed_articles`**

Same structure as filtered_articles, plus:

| Column | Type | Notes |
|---|---|---|
| filter_article_id | FK → filtered_articles | |
| description | TEXT | original source description |
| rewritten_description | TEXT | AI-rewritten description |
| image_url | TEXT | |
| reference_urls | JSONB | reserved for future web-search reference links |

**`final_articles`**

| Column | Type | Notes |
|---|---|---|
| post_processed_article_id | FK (UNIQUE) | upsert key |
| title | TEXT | copied from post_processed_articles |
| description | TEXT | rewritten_description |
| image_url | TEXT | |
| reference_urls | JSONB | |
| rank_score | FLOAT | `imp_score × time_decay_factor` |

---

## 5. Pipeline — Bird's Eye View

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SCHEDULER (every 5 min)                      │
│                                                                     │
│  run_ingestion_for_all_active_sources()                             │
│    ├── for each active source → _ingest_one_source(source)          │
│    │     └── IngestionService.ingest(source)         ◄── MAIN LOGIC │
│    └── on any OK → run_publishing()                                 │
│          └── PublishingService.publish(top_n=20)     ◄── RANKING    │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    IngestionService.ingest()                        │
│                                                                     │
│  1. FETCH         RSSFetcher / RestFetcher → list[dict]             │
│  2. CAP           slice to AI_MAX_ITEMS_PER_RUN (default 10)        │
│  3. HASH          compute SHA-256 per article                       │
│  4. DEDUP         raw_repo.store_batch()                            │
│                   → returns only NEW (unseen) hashes                │
│  5. KEYWORD FILTER _has_crime_keywords()                            │
│                   → skip ~70% of general-news articles              │
│  6. AI PIPELINE   asyncio.gather() with semaphore + rate limiter    │
│                   per article → ai_provider.process()               │
│  7. SORT RESULTS  crime / filtered_out / failed                     │
│  8. RESOLVE FKs   CategoryResolver + LocationResolver               │
│  9. SAVE          filter_article_repo.insert_batch()                │
│                   post_processed_repo.insert_batch()                │
│ 10. UPDATE STATUS raw_repo.mark_filtered / mark_filtered_out / mark_failed
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   PublishingService.publish()                       │
│                                                                     │
│  1. SELECT   post_processed_repo.get_top_by_imp_score(limit=20)     │
│  2. RANK     rank_score = imp_score × time_decay_factor             │
│              decay: 1.0 (<6 h) / 0.75 (<24 h) / 0.50 (<3 d)        │
│                     0.25 (<7 d) / 0.10 (older)                      │
│  3. UPSERT   final_article_repo.upsert_batch()                      │
│              (ON CONFLICT post_processed_article_id → UPDATE)       │
└─────────────────────────────────────────────────────────────────────┘
```

### Article lifecycle statuses (raw_ingestion.status)

```
pending → (keyword filter fails) → filtered_out
        → (AI says not crime)   → filtered_out
        → (AI call error)       → failed
        → (AI says crime, saved)→ filtered
```

---

## 6. Service Layer — Deep Dive

### 6.1 `ingestion_service.py` — IngestionService

**Responsibility:** Orchestrates the entire article lifecycle from fetch to DB write.

**Constructor dependencies:**

```python
IngestionService(
    source_repo,          # read news_sources
    raw_repo,             # store raw payloads, update statuses
    filter_article_repo,  # write stage-1 results
    post_processed_repo,  # write stage-2 results
    ai_provider_repo,     # read active AI config from DB
    db,                   # AsyncSession — passed to resolvers
)
```

**`ingest(source)` — full pipeline in order:**

| Step | Code | What it does |
|---|---|---|
| 1 | `_fetch_items(source)` | Calls RSSFetcher or RestFetcher based on `source.type` |
| 2 | slice `raw_items` | Caps at `AI_MAX_ITEMS_PER_RUN` (default 10) |
| 3 | `compute_content_hash()` | SHA-256 of `source_id + json(raw_payload)` per article |
| 4 | `raw_repo.store_batch()` | INSERT OR IGNORE; returns `{hash→id}` + set of new hashes |
| 5 | `_load_ai_provider()` | DB config → env fallback → None |
| 6 | `_has_crime_keywords(raw)` | Keyword pre-filter (frozenset ~50 terms) |
| 7 | `asyncio.gather(process_with_semaphore)` | Concurrent AI calls, rate-limited |
| 8 | sort into `crime_articles / filtered_out_hashes / failed_hashes` | |
| 9 | `load_resolvers(db)` | One DB query (state table); categories use enum |
| 10 | `cat_resolver.resolve_all()` + `loc_resolver.resolve()` | AI strings → FK ints |
| 11 | `filter_article_repo.insert_batch()` | Writes `filter_articles` |
| 12 | `post_processed_repo.insert_batch()` | Writes `post_processed_articles` |
| 13 | `_update_raw_statuses()` | Updates `raw_ingestion.status` |

**Concurrency model:**

```python
_global_rate_limiter = _RateLimiter(rpm=AI_REQUESTS_PER_MINUTE)
_global_semaphore    = asyncio.Semaphore(concurrency_from_rpm(rpm))

# rpm=5  → concurrency=1, interval=12s between calls
# rpm=10 → concurrency=1
# rpm=30 → concurrency=2
# rpm=60 → concurrency=5
```

Both are **process-level singletons** — all source ingest tasks share the same limiter, preventing total AI request rate from exceeding the configured RPM even when multiple sources run in parallel.

**Retry logic:**

`_call_with_retry()` wraps every AI call. On rate-limit errors (429 / "quota" / "resource_exhausted") it uses exponential back-off: `delay × 2^attempt`. Non-rate-limit errors fail immediately (no retry). Configured via `AI_RETRY_ATTEMPTS` (default 3) and `AI_RETRY_DELAY_SECONDS` (default 15 s).

---

### 6.2 `publishing_service.py` — PublishingService

**Responsibility:** Selects the top N articles and computes their final ranked scores.

**`publish(top_n=20)` steps:**

1. `post_processed_repo.get_top_by_imp_score(limit=top_n)` — fetches top articles ordered by `imp_score DESC`
2. For each: `rank_score = imp_score × _time_decay_factor(published_at)`
3. `final_article_repo.upsert_batch(rows)` — `ON CONFLICT (post_processed_article_id) DO UPDATE SET rank_score = ...`

**Time decay factors (configurable):**

| Age | Factor setting | Default |
|---|---|---|
| < 6 hours | `DECAY_FRESH` | 1.00 |
| 6–24 hours | `DECAY_RECENT` | 0.75 |
| 1–3 days | `DECAY_DAY` | 0.50 |
| 3–7 days | `DECAY_WEEK` | 0.25 |
| > 7 days | `DECAY_OLD` | 0.10 |

**Example:** `imp_score=80`, article is 10 hours old → `rank_score = 80 × 0.75 = 60.0`

---

### 6.3 `scheduler.py` — APScheduler jobs

Two jobs registered at startup:

```python
# Job 1 — ingestion
run_ingestion_for_all_active_sources()
  trigger: interval, every INGEST_INTERVAL_MINUTES (default 5)
  max_instances: 1  # prevents overlapping runs

# Job 2 — publishing
run_publishing()
  trigger: interval, every PUBLISH_INTERVAL_MINUTES (default 5)
  + PUBLISH_OFFSET_SECONDS (default 30s)
  max_instances: 1
```

Additionally: after every successful ingestion run, `run_ingestion_for_all_active_sources()` calls `run_publishing()` directly — so a good ingestion run immediately refreshes the feed without waiting for the next scheduled publishing interval.

---

### 6.4 `fetchers/rss_fetcher.py` — RSSFetcher

**What it does:** Wraps `feedparser.parse()` in an async executor call, returning `feed.entries` as-is (feedparser objects).

**Input:** RSS URL
**Output:** `feedparser.FeedParserDict` — caller (IngestionService) passes entries to `to_plain_dict()`

---

### 6.5 `fetchers/rest_fetcher.py` — RestFetcher

**What it does:** `httpx.AsyncClient.get(url, headers)` → JSON → `list[dict]`

Handles both a list-at-root response and a dict-with-articles-key response. Used for GNews-style REST APIs.

---

### 6.6 `source_normalizer.py`

**`to_plain_dict(entry)`:** Converts feedparser or REST API objects to a plain `dict[str, Any]` without feedparser-specific types. Handles HTML entities, `time.struct_time`, nested dicts.

**`parse_date(s)`:** Parses ISO 8601, RFC 2822, and common formats into a UTC-aware `datetime`. Returns `None` on failure.

---

### 6.7 `normalization/resolvers.py`

**`CategoryResolver`** (no DB query — uses enums from `app.core.enums`):

```
resolve("murder")                       → 1   (SubCategoryEnum.MURDER)
resolve_all(["murder", "terrorism"])    → [1, 3]
resolve_categories_from_ids([1, 3])     → [1]  (both belong to Violent Crime)
```

**`LocationResolver`** (one DB query at startup — loads state table):

```
resolve("Mumbai, Maharashtra, India")   → 14  (Maharashtra state id)
resolve("Bengaluru")                    → 9   (Karnataka via city alias map)
resolve("Germany")                      → None (not an Indian state)
```

Strategy: (1) substring match on state name → (2) city alias map (`_CITY_TO_STATE` — 80+ Indian cities) → (3) None.

**`load_resolvers(db)`:** Creates both resolvers. Called once per ingest run after the AI stage.

---

### 6.8 `normalization/provider_factory.py`

**Responsibility:** Creates and caches `AIProvider` instances for the lifetime of the process.

```
cache key = (config.id, config.model, config.api_key)
```

IngestionService is created fresh per HTTP request, but the AI SDK client (with connection pools) is created **once** and reused. Supports: `anthropic`, `gemini_langgraph`, `gemini_multimodal`, `openai`, `gemini`, `custom`.

To add a new provider: add a subclass in `providers/`, import it here, add an `elif` branch in `_build()`.

---

### 6.9 `normalization/ai_processor.py`

**`get_env_fallback_provider()`** — called when no DB config is active.

Resolution order:
1. `GEMINI_API_KEY` → `GeminiMultimodalLangGraphProvider` (gemini-2.0-flash) — **recommended**
2. `GEMINI_API_KEY` (fallback) → `GeminiLangGraphProvider`
3. `ANTHROPIC_API_KEY` → `AnthropicProvider` (claude-haiku-4-5-20251001)
4. Neither → `None` → ingestion skips AI

---

## 7. How the AI Works

### 7.1 The Single Prompt Design

All four providers use a **single AI call per article** (no separate extract + rewrite stages). The system prompt (`SINGLE_PROCESS_PROMPT` in `base.py`) instructs the model to:

- **Return `{"is_crime": false}` immediately** if the article is not crime-related. This costs near-zero tokens for ~30% of articles that pass the keyword filter.
- **Return the full JSON** for crime articles — including original text, rewritten content, classification, location, and importance score — in one pass.

This is intentionally simpler than a two-stage pipeline because:
- Gemini Flash is fast enough to do all of this in one call
- Fewer API calls = lower quota usage
- No partial-result storage complexity

---

### 7.2 Provider: `OpenAICompatibleProvider` (`openai_prov.py`)

**Best for:** Gemini via the Google OpenAI-compatible endpoint, standard OpenAI, Ollama/vLLM.

```python
response = await client.chat.completions.create(
    model=self._model,
    max_tokens=4096,
    temperature=0,
    response_format={"type": "json_object"},  # forces JSON output
    messages=[
        {"role": "system", "content": SINGLE_PROCESS_PROMPT},
        {"role": "user",   "content": build_process_message(raw_payload, source_type)},
    ],
)
text = response.choices[0].message.content
return parse_single_output(text, raw_payload)
```

**JSON parsing:** `parse_single_output()` calls `_extract_json()` which:
1. Strips markdown code fences (` ```json ... ``` `)
2. Removes `<thinking>...</thinking>` blocks (emitted by some Gemini models)
3. Slices `text[first '{' : last '}']` to isolate the JSON even with prose preamble
4. `json.loads()` → Pydantic `SingleOutput` validation

**URL fallback:** If AI returns `url: null`, the raw payload's `link` or `url` field is used instead.

---

### 7.3 Provider: `GeminiMultimodalLangGraphProvider` (`gemini_multimodal_prov.py`)

**Recommended for env-var configuration.** Uses LangGraph with **structured output** — no JSON parsing, no code fence stripping.

**Graph:**

```
START → extract_node → classify_node → END
```

**`extract_node` (no AI call):**
- Extracts candidate title from `title / headline / name / subject` fields
- Extracts candidate image URL from `media_content[0].url` or common image field names
- Cost: zero API calls

**`classify_node` (one Gemini call with structured output):**
- Builds a multimodal message: text payload + image URL if available
- Calls `llm.with_structured_output(SingleClassification)` → Pydantic model returned directly (no `json.loads` needed)
- If `is_crime=False`: returns `{"is_crime": False}`
- If `is_crime=True`: builds the full article dict, falling back raw `link` for URL

**Multimodal advantage:** Gemini can see the article's thumbnail image (e.g., crime scene photo, mug shot) and use it as an additional signal for classification and sub-category labelling.

---

### 7.4 Provider: `GeminiLangGraphProvider` (`gemini_langgraph_prov.py`)

Simple LangGraph provider using LangChain's `ChatGoogleGenerativeAI`. Single `ainvoke()` call with system + human message. Uses `parse_single_output()` for JSON parsing (same as OpenAI provider). No multimodal, no structured output.

---

### 7.5 Provider: `AnthropicProvider` (`anthropic_prov.py`)

Uses `anthropic.AsyncAnthropic`. Passes the same `SINGLE_PROCESS_PROMPT` as the system prompt and the raw payload as the user message. Uses `parse_single_output()` for JSON parsing.

---

### 7.6 AI Output Schema

All providers produce a dict matching this shape after parsing:

```python
{
    "is_crime": True,
    "title": "...",              # original headline
    "rewritten_title": "...",    # AI rephrased, ≤ 15 words, active voice
    "url": "https://...",        # canonical URL (or raw link as fallback)
    "description": "...",        # original source description (1-3 sentences)
    "rewritten_description": "...",  # AI rephrased, 3-5 sentences
    "image_url": "https://...",  # or None
    "published_at": datetime,    # parsed to UTC datetime, or None
    "sub_category": "murder",    # primary crime type string
    "sub_category_ids": ["murder", "violence"],  # multi-label strings
    "location": "Mumbai, India", # free text
    "region": "south asia",
    "imp_score": 72,             # 1-100
    "content_hash": "abc123...", # added by IngestionService, not AI
    "raw_payload": {...},        # original article dict
}
```

After resolver pass, `sub_category_ids` becomes `[1, 2]` (int IDs), `category_ids` becomes `[1]` (parent int IDs), and `location_state_id` is added.

---

### 7.7 Importance Score (imp_score)

The AI assigns 1–100 based on:

| Range | Label | Examples |
|---|---|---|
| 1–20 | Hyperlocal / minor | Petty theft in a small town |
| 21–40 | Local / notable | Single murder in a major city |
| 41–60 | Regional / significant | Gang bust, notable fraud case |
| 61–80 | National / high impact | Major terror foiled, senior official arrested |
| 81–100 | International / breaking | Multi-city attack, political assassination |

Factors: crime severity, number of victims, geographic scope, public official involvement.

---

## 8. Request Flows — End to End

### 8.1 Automated ingestion (scheduler trigger)

```
APScheduler (every 5 min)
  │
  ├── run_ingestion_for_all_active_sources()
  │     │
  │     ├── SourceRepository.get_all(active_only=True) → [source1, source2, ...]
  │     │
  │     └── asyncio.gather([_ingest_one_source(s) for s in sources])
  │           │
  │           └── (for each source, own DB session)
  │                 IngestionService.ingest(source)
  │                   │
  │                   ├── _fetch_items(source)
  │                   │     └── RSSFetcher.fetch(url)    [or RestFetcher]
  │                   │           → feedparser.entries → to_plain_dict() → list[dict]
  │                   │
  │                   ├── slice to AI_MAX_ITEMS_PER_RUN
  │                   │
  │                   ├── compute_content_hash(source_id, raw) per article
  │                   │
  │                   ├── raw_repo.store_batch()
  │                   │     INSERT OR IGNORE INTO raw_ingestion
  │                   │     → returns {hash→id}, set of unprocessed hashes
  │                   │
  │                   ├── _load_ai_provider()
  │                   │     ai_provider_repo.get_active()
  │                   │       → create_from_config(config)  [cached]
  │                   │     OR get_env_fallback_provider()  [if no DB config]
  │                   │
  │                   ├── keyword pre-filter (_has_crime_keywords)
  │                   │     → crime_candidates / pre_filtered_hashes
  │                   │
  │                   ├── asyncio.gather(process_with_semaphore per article)
  │                   │     semaphore + rate_limiter.wait()
  │                   │     → ai_provider.process(raw, source_type)
  │                   │         [builds prompt, calls AI API, parses JSON]
  │                   │         → article dict or None
  │                   │
  │                   ├── bucket results
  │                   │     crime_articles / filtered_out_hashes / failed_hashes
  │                   │
  │                   ├── load_resolvers(db)
  │                   │     SELECT id, name FROM state → LocationResolver
  │                   │     CategoryResolver (enum-based, no DB)
  │                   │
  │                   ├── for each crime article:
  │                   │     cat_resolver.resolve_all(sub_category_ids → int list)
  │                   │     cat_resolver.resolve_categories_from_ids(→ parent int list)
  │                   │     loc_resolver.resolve(location → state_id or None)
  │                   │
  │                   ├── filter_article_repo.insert_batch(crime_articles, hash_to_raw_id)
  │                   │     INSERT INTO filtered_articles ... RETURNING url→id
  │                   │
  │                   ├── post_processed_repo.insert_batch(crime_articles, url_to_filter_id)
  │                   │     INSERT INTO post_processed_articles ...
  │                   │
  │                   └── raw_repo.mark_filtered / mark_filtered_out / mark_failed
  │
  └── (if any OK) → run_publishing()
        │
        └── PublishingService.publish(top_n=20)
              │
              ├── post_processed_repo.get_top_by_imp_score(limit=20)
              │     SELECT ... ORDER BY imp_score DESC LIMIT 20
              │
              ├── for each: rank_score = imp_score × time_decay_factor
              │
              └── final_article_repo.upsert_batch(rows)
                    INSERT INTO final_articles ...
                    ON CONFLICT (post_processed_article_id)
                    DO UPDATE SET rank_score = ..., title = ..., ...
```

---

### 8.2 `POST /ingest/` — Manual ingestion trigger

```
HTTP POST /ingest/  {"source_id": 2}
  │
  ├── routes_ingest.trigger_ingest()
  │     │
  │     ├── source_repo.get_by_id(2)    → Source ORM row
  │     ├── validate source.type in {"rss", "rest"}
  │     └── svc.ingest(source)          [same IngestionService.ingest() as scheduler]
  │           └── (all steps as §8.1)
  │
  └── return IngestResponse(source_id=2, source_type="rss", ingested=5)
```

---

### 8.3 `GET /final-articles/` — Public feed

```
HTTP GET /final-articles/?limit=20&offset=0&sub_category_id=1&q=murder
  │
  ├── routes_final_articles.list_final_articles()
  │     │
  │     ├── final_article_repo.get_feed(limit, offset, sub_category_id, q)
  │     │     SELECT fa.*, pp.sub_category_id
  │     │     FROM final_articles fa
  │     │     JOIN post_processed_articles pp ON pp.id = fa.post_processed_article_id
  │     │     [WHERE pp.sub_category_id = ? AND (fa.title ILIKE ? OR fa.description ILIKE ?)]
  │     │     ORDER BY fa.rank_score DESC
  │     │     LIMIT 20 OFFSET 0
  │     │
  │     └── final_article_repo.count(sub_category_id, q)
  │
  └── return FinalArticleListResponse(total=N, items=[...])
```

---

### 8.4 `POST /final-articles/publish` — Manual publish trigger

```
HTTP POST /final-articles/publish?top_n=20
  │
  ├── routes_final_articles.trigger_publishing()
  │     │
  │     └── PublishingService.publish(top_n=20)
  │           [same as §8.1 publishing sub-flow]
  │
  └── return {"published": 20, "top_n": 20}
```

---

### 8.5 `POST /ai-providers/` → `PATCH /ai-providers/{id}/activate`

```
# Register
POST /ai-providers/
  Body: {"name": "Gemini Flash", "provider": "gemini", "model": "gemini-2.5-flash",
         "api_key": "AIza...", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"}
  └── ai_provider_repo.create(payload) → INSERT INTO ai_provider_configs
  └── return AIProviderResponse (api_key is NEVER returned)

# Activate
PATCH /ai-providers/3/activate
  └── ai_provider_repo.activate(3)
        UPDATE ai_provider_configs SET is_active=false WHERE is_active=true
        UPDATE ai_provider_configs SET is_active=true  WHERE id=3
  └── return {"activated_id": 3, "message": "'Gemini Flash' (gemini:gemini-2.5-flash) is now active"}

# Effect: next ingestion run → IngestionService._load_ai_provider()
#          → ai_provider_repo.get_active() → config.id=3
#          → create_from_config(config) → OpenAICompatibleProvider (cached)
```

---

### 8.6 AI provider resolution at each ingest run

```
IngestionService._load_ai_provider()
  │
  ├── ai_provider_repo.get_active()
  │     SELECT * FROM ai_provider_configs WHERE is_active=true LIMIT 1
  │     → config OR None
  │
  ├── if config: create_from_config(config)
  │               └── provider_factory._provider_cache[(id, model, key)]
  │                   hit  → return cached AIProvider instance
  │                   miss → _build(config) → new provider + cache it
  │
  └── if no config: get_env_fallback_provider()
                    GEMINI_API_KEY set?
                      → GeminiMultimodalLangGraphProvider (recommended)
                      → fallback: GeminiLangGraphProvider
                    ANTHROPIC_API_KEY set?
                      → AnthropicProvider
                    neither → None → skip AI for this run
```

---

## 9. API Reference & Usage Guide

### Base URL
```
http://localhost:8000
```

### Interactive docs
```
http://localhost:8000/docs   (Swagger UI)
http://localhost:8000/redoc  (ReDoc)
```

---

### Feed (public)

| Method | Path | Description |
|---|---|---|
| GET | `/final-articles/` | Ranked crime news feed |
| GET | `/final-articles/{id}` | Single ranked article |
| POST | `/final-articles/publish` | Force-refresh the feed ranking |

**GET `/final-articles/` query params:**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 20 | Articles per page (max 100) |
| `offset` | int | 0 | Pagination offset |
| `sub_category_id` | int | null | Filter by crime type (1=murder, 2=theft, …) |
| `q` | string | null | Keyword search in title + description |

**Example response:**
```json
{
  "total": 147,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "id": 91,
      "title": "Police arrest four suspects in Delhi gang robbery case",
      "description": "Delhi Police arrested four men connected to a series of armed robberies...",
      "image_url": "https://...",
      "rank_score": 60.0,
      "created_at": "2026-02-26T08:14:00Z"
    }
  ]
}
```

---

### Pipeline inspection (internal/debug)

| Method | Path | Description |
|---|---|---|
| GET | `/filter-articles/` | Stage-1 crime-filtered articles |
| GET | `/filter-articles/{id}` | Single filter article |
| GET | `/post-processed/` | Stage-2 enriched articles |
| GET | `/post-processed/{id}` | Single post-processed article |

**GET `/post-processed/` extra query params:**

| Param | Type | Description |
|---|---|---|
| `from_date` | ISO 8601 | Published on or after |
| `to_date` | ISO 8601 | Published on or before |

---

### Admin — Sources

| Method | Path | Description |
|---|---|---|
| GET | `/sources/` | List all sources (`?include_inactive=true`) |
| POST | `/sources/` | Add a new RSS or REST source |
| GET | `/sources/{id}` | Get source by ID |
| PATCH | `/sources/{id}` | Update (pause: `{"is_active": false}`) |
| DELETE | `/sources/{id}` | Permanently delete |

**POST `/sources/` body:**
```json
{
  "name": "NDTV Crime",
  "url": "https://feeds.feedburner.com/ndtvnews-crime",
  "type": "rss",
  "is_active": true,
  "config": {}
}
```

---

### Admin — Ingestion

| Method | Path | Description |
|---|---|---|
| POST | `/ingest/` | Trigger immediate ingestion for a source |

**POST `/ingest/` body:**
```json
{"source_id": 2}
```

**Response:**
```json
{"source_id": 2, "source_type": "rss", "ingested": 4}
```

---

### Admin — AI Providers

| Method | Path | Description |
|---|---|---|
| GET | `/ai-providers/` | List all providers |
| POST | `/ai-providers/` | Register a new provider |
| GET | `/ai-providers/active` | Get currently active provider |
| GET | `/ai-providers/{id}` | Get provider by ID |
| PATCH | `/ai-providers/{id}/activate` | Activate a provider |
| DELETE | `/ai-providers/active` | Deactivate all (fall back to env vars) |
| DELETE | `/ai-providers/{id}` | Delete a provider |

**POST `/ai-providers/` body:**
```json
{
  "name": "Gemini 2.5 Flash",
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "api_key": "AIzaSy...",
  "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"
}
```

Supported `provider` values: `openai`, `gemini`, `anthropic`, `gemini_langgraph`, `gemini_multimodal`, `custom`

---

### Master Data

| Method | Path | Description |
|---|---|---|
| GET | `/master/categories` | List crime categories |
| GET | `/master/sub-categories` | List crime sub-categories |
| GET | `/master/states` | List Indian states |

---

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status": "ok"}` |

---

## 10. Configuration Reference

All settings are read from `.env` via pydantic-settings (`app/core/config.py`).

| Variable | Type | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | str | **required** | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `GEMINI_API_KEY` | str | None | Enables Gemini env-fallback provider |
| `ANTHROPIC_API_KEY` | str | None | Enables Anthropic env-fallback provider |
| `AI_REQUESTS_PER_MINUTE` | int | 5 | API rate limit (0 = unlimited) |
| `AI_RETRY_ATTEMPTS` | int | 3 | Retries on rate-limit errors |
| `AI_RETRY_DELAY_SECONDS` | float | 15.0 | Base delay for exponential back-off |
| `AI_MAX_ITEMS_PER_RUN` | int | 10 | Max articles fetched per source per run |
| `INGEST_INTERVAL_MINUTES` | int | 5 | Scheduler ingestion interval |
| `PUBLISH_INTERVAL_MINUTES` | int | 5 | Scheduler publishing interval |
| `PUBLISH_OFFSET_SECONDS` | int | 30 | Publishing job offset after ingestion job |
| `FEED_TOP_N` | int | 20 | Articles selected for `final_articles` |
| `DECAY_FRESH` | float | 1.00 | Time-decay: articles < 6 h old |
| `DECAY_RECENT` | float | 0.75 | Time-decay: articles 6–24 h old |
| `DECAY_DAY` | float | 0.50 | Time-decay: articles 1–3 days old |
| `DECAY_WEEK` | float | 0.25 | Time-decay: articles 3–7 days old |
| `DECAY_OLD` | float | 0.10 | Time-decay: articles > 7 days old |
| `DEBUG` | bool | False | FastAPI debug mode |

**Free-tier recommendations (Gemini 5 RPM):**

```env
AI_REQUESTS_PER_MINUTE=5
AI_MAX_ITEMS_PER_RUN=10
AI_RETRY_ATTEMPTS=3
AI_RETRY_DELAY_SECONDS=15
```

---

## 11. Adding a New Provider

1. **Create the provider class** in `app/services/normalization/providers/your_prov.py`:

```python
from app.services.normalization.providers.base import (
    AIProvider, SINGLE_PROCESS_PROMPT,
    build_process_message, parse_single_output,
)

class YourProvider(AIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        # initialise your SDK client

    @property
    def model_id(self) -> str:
        return f"ai:your_provider:{self._model}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        user_msg = build_process_message(raw_payload, source_type)
        # call your API with SINGLE_PROCESS_PROMPT as system + user_msg as user
        text = ...
        return parse_single_output(text, raw_payload)
```

2. **Register it** in `provider_factory.py`:

```python
from app.services.normalization.providers.your_prov import YourProvider

# in _build():
if provider == "your_provider":
    return YourProvider(api_key=api_key, model=model)
```

3. **Add the provider name** to `SUPPORTED_PROVIDERS` in `app/models/ai_provider.py`.

4. **Test** with `POST /ai-providers/` → `PATCH /{id}/activate` → `POST /ingest/`.

No other files need changes.
