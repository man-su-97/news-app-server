# Design: Hybrid Retrieval + Metadata Filtering

Status: **Proposed**. Extends the Phase 1 retrieval path (`app/services/ai/retrieval.py`,
`app/repositories/chunk_repo.py`) with lexical + semantic hybrid search, reciprocal
rank fusion, and metadata filters — plus a CI workflow to guard the whole suite.

## Motivation

Pure vector search retrieves by *meaning*, which is exactly wrong for the cases news
Q&A hits most: exact entity names, tickers, acronyms, and rare terms that embeddings
smear together ("Fed" vs. "the central bank", a specific person, a bill number).
Lexical search nails those but misses paraphrase. **Hybrid retrieval runs both and
fuses the rankings**, so a query gets semantic recall *and* exact-term precision.

Separately, news is intrinsically filtered by **source** and **recency** — "what did
Reuters say this week" is a filter, not a similarity signal. We add metadata filters
that apply *before* ranking so they compose with either search mode.

## Scope

- Hybrid retrieval available on `/ai/search`, `/ai/ask`, and the agent's
  `semantic_search` tool.
- **Opt-in**: a `mode` field selects `"vector"` (default, unchanged behaviour) or
  `"hybrid"`. Vector remains the default so existing behaviour and tests are
  untouched, and the two modes can be compared side by side.
- Metadata filters: **source** (`source_id` or `source_name`) and a **published-at
  date range** (`published_from` / `published_to`). No topic/category filter — that
  column does not exist and would require a classification pipeline (out of scope).

## Design

### 1. Data model & migration

New Alembic migration, `down_revision = a1b2c3d4e5f6`:

- Add a **generated** column to `article_chunks`:
  `content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED`.
  Generated-stored means the lexical index is always consistent with `content` with
  zero application-side maintenance and survives re-indexing.
- Add a **GIN index** on `content_tsv` for full-text matching.

Filters need no schema change: `articles.source_id` and `articles.published_at`
already exist, and `sources.name` is joinable.

### 2. Repository layer — `ChunkRepository`

- `search(query_embedding, k)` — the existing pure-vector query. **Unchanged.**
- New `hybrid_search(query_embedding, query_text, k, filters, candidate_n)`:
  1. **Vector arm** — existing cosine query, top `candidate_n`, `filters` applied as
     `WHERE`.
  2. **Lexical arm** — `content_tsv @@ websearch_to_tsquery('english', query_text)`
     ordered by `ts_rank`, top `candidate_n`, same `WHERE`.
  3. **Fusion** — Reciprocal Rank Fusion over the two ranked chunk-id lists:
     `score(d) = Σ_arm 1 / (RRF_K + rank_arm(d))`. Return the top `k`.
- A small `RetrievalFilters` **dataclass** (`source_id`, `source_name`,
  `published_from`, `published_to`) builds composable `WHERE` clauses shared by both
  arms — one filter definition, applied identically to each arm. This is the plain,
  framework-free type the repository and service pass around; the API layer's Pydantic
  filter model (§4) is validated at the edge and converted into it, keeping the
  repository free of Pydantic (consistent with the tools/repo layering).
- `RetrievedChunk` gains an `rrf_score: float | None`. For hybrid results `score`
  returns the RRF score; the vector `distance` is retained for the vector arm.

**RRF over weighted blending (chosen):** RRF fuses *ranks*, not scores, so there is no
need to normalise a cosine distance against a `ts_rank` value or tune a weight `α`.
`RRF_K` (default 60) only damps the tail; results are robust to it. This is the
standard hybrid recipe and stays consistent with the project's "reuse Postgres, no
dedicated vector DB" decision.

### 3. Service layer — `RetrievalService`

`search(query, k, mode="vector", filters=None)`:

- `mode="vector"` → current path (embed query → `chunk_repo.search`).
- `mode="hybrid"` → embed query **and** pass the raw text to `hybrid_search`.
- `filters` pass through in both modes — filtering is independent of ranking.
- **Empty/whitespace `query_text` in hybrid → fall back to vector-only** (there are no
  terms to match lexically).

### 4. API / schemas

`SearchRequest` and `AskRequest` gain:

- `mode: Literal["vector", "hybrid"] = "vector"`
- `filters: RetrievalFilters | None = None`

`RetrievalFilters` (Pydantic) validates the date range — `published_from >
published_to` → **422**. Response shapes are unchanged; for hybrid, `score` carries
the RRF score.

### 5. Agent tool

`semantic_search_tool` switches to `mode="hybrid"` and gains an optional
`published_after: date | None` parameter the model can set, so the agent can answer
"latest / recent" questions. It stays a plain async function → unit-testable with a
fake service, no LLM in the loop.

### 6. Config

- `RETRIEVAL_CANDIDATE_N` (default 50) — per-arm candidate pool before fusion.
- `RRF_K` (default 60) — RRF damping constant.

### 7. Error handling

- Invalid date range → 422 (schema validation).
- Empty query text in hybrid → graceful fallback to vector-only.
- No new failure modes on the read path; unknown `source_name` simply returns no rows.

## Testing

- **Pure**: RRF fusion extracted as `_reciprocal_rank_fusion(ranked_lists, k)` and
  tested with no DB — tie handling, one-arm-empty, ordering. Filter-clause building
  tested purely.
- **Service**: mode routing (vector vs hybrid) and filter pass-through via a fake repo.
- **Agent tool**: `published_after` reaches the retrieval call (fake service).
- **Not unit-tested**: the two SQL arms themselves require a live Postgres with the
  `tsvector` column; consistent with the existing suite, they are covered by the
  migration + manual verification rather than unit tests. Called out honestly.

## CI

`.github/workflows/ci.yml`, on push and PR to `main`:

1. checkout → `astral-sh/setup-uv`
2. `uv sync`
3. `uv run ruff check .`
4. `uv run ruff format --check .`
5. `uv run pytest`

The suite needs no DB, Redis, OpenAI key, or network (injected fakes + dummy env in
`tests/conftest.py`), so CI is self-contained and fast. It gates this feature on the
way in.

## Delivery

Single branch `feat/hybrid-retrieval-and-ci`, two logical commits (CI first, then
hybrid + filters), one PR — so CI validates the retrieval work as it merges.
