"""
app/services/normalization/providers/gemini_multimodal_prov.py
==============================================================
Multi-node LangGraph provider using Gemini with multimodal support.

Architecture: TWO separate LangGraph graphs, one per pipeline stage.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GRAPH 1 — FILTER  (called from process())
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
START
  → extract_node      — lightweight dict traversal: candidate title/image/URL
  → search_node       — DuckDuckGo news search for crime context (list format)
  → classify_node     — Gemini multimodal structured output:
                          • passes image_url to Gemini if available (MULTIMODAL)
                          • uses with_structured_output(FilterClassification)
                          • no manual JSON parsing — Pydantic directly
END
Output: complete article dict compatible with ingestion_service

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GRAPH 2 — POST-PROCESS  (called from post_process())
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
START
  → multi_search_node — 2 concurrent DuckDuckGo searches (different queries)
                        → reference_urls extracted directly (no hallucination risk)
  → rewrite_rank_node — Gemini structured output:
                          • rewrites title + description
                          • calculates imp_score 1-100 from search breadth + severity
END
Output: {rewritten_title, rewritten_description, reference_urls, imp_score}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why multimodal?
  News images carry information: a crime scene photo vs. a political rally image
  immediately signals the nature of the story. Gemini Flash 2.0 processes image
  URLs directly — no base64 encoding needed. When image_url is present in the
  raw article, we include it in the classify call for better accuracy.

Why with_structured_output?
  Replaces manual JSON parsing + Pydantic validation. The Gemini SDK enforces
  the JSON schema at generation time → zero parse failures, no code-fence stripping,
  no missing-key errors. Each node gets a typed Pydantic model back, not raw text.

Why two graphs?
  Filter runs on ALL articles (cheap — skip non-crime fast).
  Post-process runs ONLY on crime articles (expensive enrichment).
  Separate graphs keep each stage independently testable and replaceable.
"""

import asyncio
import logging
import re
from typing import Annotated, Literal, TypedDict

from langchain_community.tools import DuckDuckGoSearchResults
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, field_validator

from app.services.normalization.providers.base import (
    AIProvider,
    _strip_code_fences,
)
from app.services.source_normalizer import parse_date

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured output schemas (used with llm.with_structured_output)
# ---------------------------------------------------------------------------

_SubCat = Literal[
    "murder", "theft", "fraud", "cybercrime", "terrorism",
    "corruption", "drugs", "violence", "trafficking", "other",
]
_Category = Literal[
    "crime", "politics", "technology", "business", "science",
    "health", "sports", "entertainment", "world", "environment", "other",
]
_Region = Literal[
    "South Asia", "Southeast Asia", "East Asia", "Central Asia",
    "Middle East", "Europe", "North America", "Latin America",
    "Africa", "Oceania", "Unknown",
]


class FilterClassification(BaseModel):
    """Structured output from the classify_node.

    Gemini fills this schema via with_structured_output(method='json_schema').
    Enum-constrained fields prevent hallucinated values without post-processing.
    """

    # ── Extraction fields (AI fills from raw payload) ──────────────────────
    title: str = Field(
        description="Clean, plain-text headline extracted from the article (required)."
    )
    url: str | None = Field(
        default=None,
        description="Canonical article URL (absolute HTTP/HTTPS). null if not found.",
    )
    description: str | None = Field(
        default=None,
        description="1-3 sentence factual summary of the article. null if insufficient content.",
    )
    image_url: str | None = Field(
        default=None,
        description="Thumbnail image URL (absolute HTTP/HTTPS). null if not found.",
    )
    published_at: str | None = Field(
        default=None,
        description="Publication datetime in ISO 8601 UTC format e.g. '2024-01-15T10:30:00Z'. null if unknown.",
    )

    # ── Classification fields ───────────────────────────────────────────────
    is_crime: bool = Field(
        description="True if the article is PRIMARILY about criminal activity."
    )
    category: _Category = Field(
        default="other",
        description="Primary news category. Use 'crime' when is_crime=true.",
    )
    sub_category_ids: list[_SubCat] = Field(
        default=[],
        description=(
            "All applicable crime sub-types (MULTI-LABEL). "
            "Example: a kidnapping-for-ransom → ['violence', 'fraud']. "
            "Empty list for non-crime articles."
        ),
    )
    location: str | None = Field(
        default=None,
        description="City and country where the crime occurred, e.g. 'Mumbai, India'. null if unknown.",
    )
    region: _Region = Field(
        default="Unknown",
        description="Broad geographic region of the incident.",
    )
    importance_score: int = Field(
        default=5,
        ge=1,
        le=10,
        description=(
            "Quick importance estimate 1-10. "
            "1-3=local/minor, 4-6=regional, 7-8=national, 9-10=international/breaking."
        ),
    )


class PostProcessResult(BaseModel):
    """Structured output from the rewrite_rank_node.

    Combines rewriting + importance scoring in one AI call to save a round-trip.
    """

    rewritten_title: str = Field(
        description=(
            "Rewritten headline: clear, factual, active voice, max 15 words. "
            "Include location if known. Do NOT sensationalise."
        )
    )
    rewritten_description: str = Field(
        description=(
            "2-3 sentence news card summary: what happened, who is involved, where. "
            "Factual only, no speculation."
        )
    )
    imp_score: int = Field(
        ge=1,
        le=100,
        description=(
            "Importance score 1-100. "
            "1-20: hyperlocal/minor. 21-40: local/notable. "
            "41-60: regional/significant. 61-80: national/high-impact. "
            "81-100: international/breaking. "
            "Calibrate using web_search_context: more coverage = higher score."
        ),
    )
    ranking_notes: str | None = Field(
        default=None,
        description="1 sentence explanation of why this imp_score was chosen (for audit).",
    )


# ---------------------------------------------------------------------------
# Graph states  (TypedDict — LangGraph passes these between nodes)
# ---------------------------------------------------------------------------

class FilterState(TypedDict):
    """Shared state flowing through the filter graph."""

    # ── Inputs ──────────────────────────────────────────────────────────────
    raw_payload: dict       # Raw RSS/REST payload — set before graph starts
    source_type: str        # "rss" or "rest" — helps extraction heuristics

    # ── Set by extract_node ─────────────────────────────────────────────────
    candidate_title: str            # Best-guess title without AI
    candidate_image_url: str | None # Best-guess image URL without AI

    # ── Set by search_node ──────────────────────────────────────────────────
    search_context: str             # Combined DuckDuckGo snippets (text for Gemini)
    search_urls: list[str]          # URLs found by search (for potential reference use)

    # ── Set by classify_node ─────────────────────────────────────────────────
    classification: FilterClassification | None  # Structured Gemini output

    # ── Final result ─────────────────────────────────────────────────────────
    result: dict | None             # ingestion_service-compatible dict


class PostProcessState(TypedDict):
    """Shared state flowing through the post-process graph."""

    # ── Inputs ──────────────────────────────────────────────────────────────
    filter_article: dict    # Stage 1 result dict

    # ── Set by multi_search_node ─────────────────────────────────────────────
    search_context: str     # Combined snippets from multiple search queries
    reference_urls: list[str]   # Deduplicated reference URLs extracted from results

    # ── Set by rewrite_rank_node ─────────────────────────────────────────────
    rewrite_result: PostProcessResult | None

    # ── Final result ─────────────────────────────────────────────────────────
    result: dict | None


# ---------------------------------------------------------------------------
# System prompt templates
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = """\
You are a crime news classification engine for a real-time crime news aggregator.

You receive a raw news article payload (RSS entry or REST API JSON) along with optional
web search context. Your task: extract article fields AND classify the crime content.

If a news image is provided alongside the text, use visual cues to confirm the crime type
(e.g. police tape = violent crime scene, court building = legal case, fire = arson).

Classification rules:
- is_crime: true ONLY if the article's PRIMARY subject is criminal activity.
  (Accidents, disasters, politics without crime → is_crime=false)
- sub_category_ids: pick ALL that apply (multi-label). Most articles: 1-2 types.
  Do NOT list "other" unless none of the specific types fit.
- location: prefer specific city + state/country over vague regions.
- importance_score: calibrate using the provided web search context.
  Wider news coverage = higher score.

Return a complete, valid JSON response matching the required schema."""

_REWRITE_SYSTEM_PROMPT = """\
You are a senior crime news editor for a real-time news platform.

You receive a classified crime article and web search context (related news coverage).
Your tasks:
1. Rewrite the headline to be clear, factual, and publication-ready (active voice, max 15 words).
2. Write a 2-3 sentence news card description: what happened, who, where, when (if known).
3. Assign an importance score 1-100 based on:
   - Crime severity (murder/terrorism > theft/fraud > minor incidents)
   - Number of victims / public impact
   - Seniority of persons involved (public officials = higher)
   - Geographic scope (national > regional > local)
   - Media coverage breadth (use web_search_context — more sources = higher score)

Rules:
- Do NOT invent facts. If uncertain, use "allegedly" or "reportedly".
- Do NOT sensationalise. Be objective and precise.
- ranking_notes: 1 sentence explaining your imp_score choice (for audit trail).

Return a complete, valid JSON response matching the required schema."""


# ---------------------------------------------------------------------------
# Main provider class
# ---------------------------------------------------------------------------

class GeminiMultimodalLangGraphProvider(AIProvider):
    """
    Gemini Flash multimodal provider with dedicated LangGraph graphs per pipeline stage.

    Stage 1 (process)     — 3-node filter graph: extract → search → classify
    Stage 2 (post_process) — 2-node post-process graph: multi_search → rewrite+rank

    Key capabilities:
      • Multimodal classification — passes article image to Gemini when available
      • Structured output — with_structured_output(Pydantic) → no JSON parsing
      • Multi-label categories — sub_category_ids is a list, not a single field
      • Concurrent search — two DuckDuckGo queries run in parallel for post-process
      • Reference URL extraction — pulled directly from search results (no hallucination)
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        search_max_results: int = 4,
    ) -> None:
        self._model_name = model
        self._search_max_results = search_max_results

        # Base LLM — temperature=0 for deterministic structured output
        self._llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0,
        )

        # Structured-output runnables (compiled once, reused for all calls)
        # method='json_schema': Gemini enforces the schema at generation time
        self._classify_llm = self._llm.with_structured_output(
            FilterClassification, method="json_schema"
        )
        self._rewrite_llm = self._llm.with_structured_output(
            PostProcessResult, method="json_schema"
        )

        # DuckDuckGo search tool (output_format='list' → structured dicts)
        self._search_tool = DuckDuckGoSearchResults(
            max_results=search_max_results,
            output_format="list",
        )

        # Build and compile both LangGraph graphs once at init
        self._filter_graph = self._build_filter_graph()
        self._post_process_graph = self._build_post_process_graph()

    # ── AIProvider interface ─────────────────────────────────────────────────

    @property
    def model_id(self) -> str:
        return f"ai:gemini_multimodal:{self._model_name}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        """STAGE 1: Run the 3-node filter graph on one raw article.

        Graph: extract_node → search_node → classify_node
        Returns the complete article dict or None on failure.
        """
        try:
            final_state: FilterState = await self._filter_graph.ainvoke({
                "raw_payload": raw_payload,
                "source_type": source_type,
                "candidate_title": "",
                "candidate_image_url": None,
                "search_context": "",
                "search_urls": [],
                "classification": None,
                "result": None,
            })
            return final_state.get("result")
        except Exception as exc:
            logger.warning("GeminiMultimodal filter graph error: %s", exc)
            return None

    async def post_process(
        self, filter_article: dict, search_context: str = ""
    ) -> dict | None:
        """STAGE 2: Run the 2-node post-process graph on a crime article.

        Graph: multi_search_node → rewrite_rank_node
        Returns {rewritten_title, rewritten_description, reference_urls, imp_score}.
        """
        try:
            final_state: PostProcessState = await self._post_process_graph.ainvoke({
                "filter_article": filter_article,
                "search_context": search_context,   # may be pre-populated by caller
                "reference_urls": [],
                "rewrite_result": None,
                "result": None,
            })
            return final_state.get("result")
        except Exception as exc:
            logger.warning("GeminiMultimodal post-process graph error: %s", exc)
            return None

    # ── Filter graph construction ────────────────────────────────────────────

    def _build_filter_graph(self):
        """Build and compile the 3-node article filter graph.

        extract → search → classify → END
        """
        builder = StateGraph(FilterState)
        builder.add_node("extract", self._extract_node)
        builder.add_node("search", self._search_node)
        builder.add_node("classify", self._classify_node)

        builder.add_edge(START, "extract")
        builder.add_edge("extract", "search")
        builder.add_edge("search", "classify")
        builder.add_edge("classify", END)

        return builder.compile()

    async def _extract_node(self, state: FilterState) -> dict:
        """Node 1: Lightweight field extraction without AI.

        Traverses the raw_payload dict looking for common field names used by
        RSS feeds (feedparser keys) and REST APIs. No network calls, no AI.
        This provides a candidate title for the search query.

        Returns updates to: candidate_title, candidate_image_url
        """
        raw = state["raw_payload"]

        # Title: try common field names in order of reliability
        title = (
            raw.get("title")
            or raw.get("headline")
            or raw.get("name")
            or raw.get("subject")
            or ""
        )
        # Last resort: first 120 chars of the payload as a string
        if not title:
            title = str(raw)[:120]

        # Image URL: try common patterns
        image_url: str | None = None
        # RSS feedparser stores media in media_content list
        media_content = raw.get("media_content") or []
        if isinstance(media_content, list) and media_content:
            image_url = media_content[0].get("url")
        if not image_url:
            for field in ("image_url", "image", "thumbnail", "urlToImage", "jetpack_featured_media_url"):
                v = raw.get(field)
                if isinstance(v, str) and v.startswith(("http://", "https://")):
                    image_url = v
                    break

        return {"candidate_title": str(title), "candidate_image_url": image_url}

    async def _search_node(self, state: FilterState) -> dict:
        """Node 2: DuckDuckGo news search for crime context.

        Uses the candidate_title extracted by extract_node.
        Returns structured search results as:
          - search_context: plain text snippets for Gemini
          - search_urls: URL list (may feed reference_urls later)

        Failure is non-fatal — empty context means Gemini works without web data.
        """
        title = state.get("candidate_title", "")
        if not title:
            return {"search_context": "", "search_urls": []}

        query = f"{title} crime news"
        try:
            results = await self._search_tool.ainvoke(query)
        except Exception as exc:
            logger.warning("Filter search_node failed (non-fatal): %s", exc)
            return {"search_context": "", "search_urls": []}

        if not isinstance(results, list):
            return {"search_context": "", "search_urls": []}

        snippets: list[str] = []
        urls: list[str] = []
        for item in results:
            if isinstance(item, dict):
                snippet = item.get("snippet", "")
                link = item.get("link", "")
                if snippet:
                    snippets.append(snippet)
                if link and link.startswith(("http://", "https://")):
                    urls.append(link)

        return {
            "search_context": "\n\n".join(snippets),
            "search_urls": urls,
        }

    async def _classify_node(self, state: FilterState) -> dict:
        """Node 3: Gemini multimodal classification with structured output.

        Builds a HumanMessage that optionally includes the article's image
        (MULTIMODAL mode when image_url is available — Gemini processes both
        text and image together for more accurate crime classification).

        Uses with_structured_output(FilterClassification) → no JSON parsing needed.
        Failure returns result=None → article is dropped by ingestion_service.
        """
        raw = state["raw_payload"]
        source_type = state["source_type"]
        search_context = state.get("search_context", "")
        image_url = state.get("candidate_image_url")

        # Build the text payload the AI will reason over
        import json as _json
        user_text_parts = [
            f"Source type: {source_type}",
            "",
            "Raw article payload:",
            _json.dumps(raw, default=str, indent=2),
        ]
        if search_context:
            user_text_parts += ["", "Web search context (related news):", search_context]

        user_text = "\n".join(user_text_parts)

        # Build message content — multimodal if image available
        content: list = [{"type": "text", "text": user_text}]

        if image_url and image_url.startswith(("http://", "https://")):
            # Include the article's image — Gemini will use visual cues
            # to confirm crime type (e.g. police scene, court, weapons, etc.)
            content.append({
                "type": "image_url",
                "image_url": {"url": image_url},
            })
            logger.debug("classify_node: multimodal mode — image included: %s", image_url[:80])

        try:
            classification: FilterClassification = await self._classify_llm.ainvoke([
                SystemMessage(content=_CLASSIFY_SYSTEM_PROMPT),
                HumanMessage(content=content),
            ])
        except Exception as exc:
            logger.warning("classify_node Gemini error: %s", exc)
            return {"classification": None, "result": None}

        if not classification.title:
            logger.warning("classify_node: empty title returned — dropping article")
            return {"classification": None, "result": None}

        # Build the result dict expected by ingestion_service
        published_at = parse_date(classification.published_at) if classification.published_at else None

        result = {
            "title": classification.title,
            "url": classification.url or "",
            "description": classification.description,
            "image_url": classification.image_url or image_url,  # AI may find a better one
            "published_at": published_at,
            "raw_payload": raw,
            "is_crime": classification.is_crime,
            "category": classification.category,
            "sub_category": classification.sub_category_ids[0] if classification.sub_category_ids else None,
            "sub_category_ids": list(classification.sub_category_ids),
            "location": classification.location,
            "region": classification.region,
            "summary": classification.description,
            "importance_score": classification.importance_score,
        }

        return {"classification": classification, "result": result}

    # ── Post-process graph construction ─────────────────────────────────────

    def _build_post_process_graph(self):
        """Build and compile the 2-node post-process graph.

        multi_search → rewrite_rank → END
        """
        builder = StateGraph(PostProcessState)
        builder.add_node("multi_search", self._multi_search_node)
        builder.add_node("rewrite_rank", self._rewrite_rank_node)

        builder.add_edge(START, "multi_search")
        builder.add_edge("multi_search", "rewrite_rank")
        builder.add_edge("rewrite_rank", END)

        return builder.compile()

    async def _multi_search_node(self, state: PostProcessState) -> dict:
        """Node 1: Run 2 concurrent DuckDuckGo searches for related news.

        Queries:
          1. "{title} {crime_type} news"   — exact story coverage
          2. "{location} {crime_type}"     — location + crime type context (if location known)

        Reference URLs are extracted directly from search results — no AI involved,
        so there's zero hallucination risk for URLs.

        Pre-populated search_context from the caller is kept and extended.
        """
        article = state["filter_article"]
        title = article.get("title", "")
        location = article.get("location", "") or ""
        sub_cats = article.get("sub_category_ids", [])
        crime_type = sub_cats[0] if sub_cats else "crime"

        # Build targeted queries
        queries = [f"{title} {crime_type} news"]
        if location:
            queries.append(f"{location} {crime_type} crime")

        # Run all searches concurrently
        async def _one_search(q: str) -> list[dict]:
            try:
                result = await self._search_tool.ainvoke(q)
                return result if isinstance(result, list) else []
            except Exception as exc:
                logger.warning("post_process search failed for %r: %s", q[:60], exc)
                return []

        all_results_nested = await asyncio.gather(
            *[_one_search(q) for q in queries],
            return_exceptions=True,
        )

        # Flatten, deduplicate URLs, collect snippets
        seen_urls: set[str] = set()
        reference_urls: list[str] = []
        snippets: list[str] = []

        for result_set in all_results_nested:
            if isinstance(result_set, Exception):
                continue
            for item in result_set:
                if not isinstance(item, dict):
                    continue
                link = item.get("link", "")
                snippet = item.get("snippet", "")
                if link and link.startswith(("http://", "https://")) and link not in seen_urls:
                    seen_urls.add(link)
                    reference_urls.append(link)
                if snippet:
                    snippets.append(snippet)

        # Prepend any context passed in by the caller
        existing = state.get("search_context", "")
        combined_context = "\n\n".join(
            filter(None, [existing] + snippets[:6])
        )

        logger.debug(
            "post_process multi_search: %d reference URLs, %d snippet(s)",
            len(reference_urls), len(snippets),
        )

        return {
            "search_context": combined_context,
            "reference_urls": reference_urls[:5],   # cap at 5
        }

    async def _rewrite_rank_node(self, state: PostProcessState) -> dict:
        """Node 2: Gemini call to rewrite article + assign importance score.

        Sends the filter article + web search context to Gemini.
        Uses with_structured_output(PostProcessResult) for reliable output.

        On failure: returns result=None → ingestion_service uses stage-1 data.
        """
        article = state["filter_article"]
        search_context = state.get("search_context", "")
        reference_urls = state.get("reference_urls", [])

        import json as _json

        user_parts = [
            "Article to rewrite and score:",
            _json.dumps(
                {
                    "title": article.get("title", ""),
                    "description": article.get("description") or article.get("summary", ""),
                    "url": article.get("url", ""),
                    "crime_types": article.get("sub_category_ids", []),
                    "location": article.get("location"),
                    "region": article.get("region"),
                    "importance_score_stage1": article.get("importance_score"),
                },
                indent=2,
            ),
        ]
        if search_context:
            user_parts += ["", "Web search context (related news):", search_context]

        user_text = "\n".join(user_parts)

        try:
            rewrite_result: PostProcessResult = await self._rewrite_llm.ainvoke([
                SystemMessage(content=_REWRITE_SYSTEM_PROMPT),
                HumanMessage(content=user_text),
            ])
        except Exception as exc:
            logger.warning("rewrite_rank_node Gemini error: %s", exc)
            return {"rewrite_result": None, "result": None}

        result = {
            "rewritten_title": rewrite_result.rewritten_title,
            "rewritten_description": rewrite_result.rewritten_description,
            "reference_urls": reference_urls,   # from search, not from AI
            "imp_score": rewrite_result.imp_score,
        }

        logger.debug(
            "rewrite_rank_node: imp_score=%d title=%r reason=%r",
            rewrite_result.imp_score,
            rewrite_result.rewritten_title[:60],
            (rewrite_result.ranking_notes or "")[:80],
        )

        return {"rewrite_result": rewrite_result, "result": result}
