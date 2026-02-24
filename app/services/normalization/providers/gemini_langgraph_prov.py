"""
app/services/normalization/providers/gemini_langgraph_prov.py — Gemini + LangGraph Provider
=============================================================================================
The RECOMMENDED provider for this crime news application.

Single-pass processing with web search context:

  process() — LangGraph agent:
    Step 1 (search_node): DuckDuckGo searches for "{article_title} crime news"
    Step 2 (process_node): Gemini receives raw_payload + search results → outputs ALL fields:
      title, url, description, image_url, published_at,
      is_crime, category, sub_category, location, region, summary, importance_score

  Total: ~2-4 seconds per article (one search + one AI call).

Why LangGraph?
  DuckDuckGo search gives the AI real-world context BEFORE processing:
    - How widely covered is this story? → better importance_score calibration
    - Related coverage confirms location and crime type
    - AI has factual grounding instead of guessing from raw text alone

Why DuckDuckGo (not Google/Bing/Tavily)?
  - Completely free, no API key required
  - Good enough for news queries
  - Reduces operational dependencies

Why a single process() call (not separate normalize + enrich)?
  - Halves the number of API calls → halves cost and latency
  - The AI sees the raw payload directly, not an intermediate normalized form
  - Simpler code path — one graph, one method

LangGraph graph structure:
  START → search_node → process_node → END

  Each "node" is an async function that:
    1. Reads relevant fields from the shared _ProcessState dict
    2. Does its work (HTTP call or AI call)
    3. Returns a dict with ONLY the state keys it wants to update

The state is typed with TypedDict so Python knows exactly what fields exist.
"""

import logging
from typing import TypedDict  # For type-safe state definition

# LangChain + LangGraph imports
from langchain_community.tools import DuckDuckGoSearchResults  # Free web search tool
from langchain_core.messages import HumanMessage, SystemMessage  # Message types for LLM
from langchain_google_genai import ChatGoogleGenerativeAI  # Native Gemini integration
from langgraph.graph import END, START, StateGraph  # Graph builder components

from app.services.normalization.providers.base import (
    AIProvider,
    COMBINED_PROCESS_PROMPT,
    POST_PROCESS_PROMPT,
    build_post_process_message,
    build_process_message,
    parse_combined_output,
    parse_post_process_output,
)

logger = logging.getLogger(__name__)


class _ProcessState(TypedDict):
    """The shared state object passed between LangGraph nodes.

    TypedDict gives us type safety — each node knows exactly what keys exist.
    LangGraph passes this dict through the graph; each node returns a partial dict
    with only the keys it updated (LangGraph merges these updates into the state).

    Fields:
      raw_payload:    the raw RSS/REST item — set before graph starts, read-only
      source_type:    "rss" or "rest" — helps AI interpret the payload structure
      search_context: DuckDuckGo search results — written by search_node, read by process_node
      result:         final complete article dict — written by process_node, read after graph ends
    """
    raw_payload: dict       # Raw article data from the fetcher
    source_type: str        # "rss" or "rest"
    search_context: str     # DuckDuckGo results (empty string if search failed)
    result: dict | None     # Final article dict (None if processing failed)


class GeminiLangGraphProvider(AIProvider):
    """Google Gemini + LangGraph agent for combined article processing.

    The LangGraph agent searches DuckDuckGo BEFORE calling Gemini, giving the
    AI real-world context for better importance scoring and location extraction.
    One combined call (not separate normalize + enrich) keeps API costs low.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._model = model

        # ChatGoogleGenerativeAI: native Gemini integration via langchain-google-genai.
        # temperature=0: deterministic output — same input → same output every time.
        # This is correct for structured extraction (we don't want creative variation).
        self._llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,   # Gemini API key from Google AI Studio or GCP
            temperature=0,            # No randomness — consistent, reliable output
        )

        # DuckDuckGo search tool — no API key needed, completely free.
        # max_results=3: 3 search results is sufficient to calibrate importance_score.
        # More results = better accuracy but more tokens = slower + more expensive.
        self._search = DuckDuckGoSearchResults(max_results=3)

        # Build and compile the LangGraph processing graph (done once at construction).
        # Compilation locks in the graph structure — nodes/edges can't change after this.
        self._graph = self._build_graph()

    @property
    def model_id(self) -> str:
        """Identifier stored in raw_ingestion_events for audit trail.
        Example: "ai:gemini_langgraph:gemini-2.0-flash"
        """
        return f"ai:gemini_langgraph:{self._model}"

    # ------------------------------------------------------------------
    # AIProvider interface implementation
    # ------------------------------------------------------------------

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        """Run the LangGraph graph: search_node → process_node.

        Invokes the pre-built graph with the raw payload as input.
        The graph searches DuckDuckGo, then sends raw data + search context to Gemini.
        Returns the complete article dict or None if the graph fails.

        The outer try/except is a final safety net — any unexpected error
        (graph compilation issues, unexpected state shape, etc.) returns None
        safely, which causes IngestionService to drop this article.
        """
        try:
            # ainvoke() runs the graph asynchronously and returns the FINAL state dict
            final_state = await self._graph.ainvoke({
                "raw_payload": raw_payload,
                "source_type": source_type,
                "search_context": "",   # filled by search_node
                "result": None,         # filled by process_node
            })
            # Return the result dict from the final state (None if processing failed)
            return final_state.get("result")
        except Exception as exc:
            logger.warning("LangGraph process graph error: %s", exc)
            return None  # Fail safe — caller drops this article

    # ------------------------------------------------------------------
    # LangGraph graph construction
    # ------------------------------------------------------------------

    def _build_graph(self):
        """Build and compile the two-node LangGraph processing graph.

        Graph structure:
          START → search_node → process_node → END

        StateGraph takes the state TypedDict so it knows the shape of the
        data flowing through the graph.

        .compile() returns a runnable graph object. We call this with
        .ainvoke() in process() to execute the full graph.
        """
        builder = StateGraph(_ProcessState)

        # Register nodes — each node is an async method on this class.
        # "search" and "process" are just labels used in add_edge() calls.
        builder.add_node("search", self._search_node)
        builder.add_node("process", self._process_node)

        # Define execution order:
        # START → search (DuckDuckGo lookup) → process (Gemini call) → END
        builder.add_edge(START, "search")
        builder.add_edge("search", "process")
        builder.add_edge("process", END)

        # Compile: locks the graph and returns a runnable object
        return builder.compile()

    async def _search_node(self, state: _ProcessState) -> dict:
        """Node 1: Search DuckDuckGo for context about this raw article.

        Extracts a candidate title from the raw payload using common field names.
        Queries DuckDuckGo: "{title} crime news"

        Returns: {"search_context": "snippet 1... snippet 2... snippet 3..."}

        If the search fails (network error, rate limit, DuckDuckGo blocks us),
        returns an empty string. The next node still processes the article,
        just without web context. Search failure is NEVER fatal — at worst
        we get a slightly less accurate importance_score.
        """
        raw = state["raw_payload"]
        # Try common field names where a title/headline might appear in RSS or REST data
        title = (
            raw.get("title") or
            raw.get("headline") or
            raw.get("name") or
            raw.get("subject") or
            ""
        )
        # Fallback: use the first 100 chars of the payload as a string
        if not title:
            title = str(raw)[:100]

        try:
            # ainvoke() sends the query to DuckDuckGo and returns a formatted string
            # with results (each result has: title, snippet, URL)
            results = await self._search.ainvoke(f"{title} crime news")
            return {"search_context": str(results)}
        except Exception as exc:
            # Search failed — log it but DO NOT fail the entire ingestion
            logger.warning("DuckDuckGo search failed (non-fatal): %s", exc)
            return {"search_context": ""}  # Empty context = AI processes without web data

    async def _process_node(self, state: _ProcessState) -> dict:
        """Node 2: Call Gemini to extract and classify the article in one shot.

        Receives: raw_payload + search_context (from search_node)
        Sends to Gemini: source_type + full raw payload + web search results
        Returns: {"result": complete_article_dict_or_None}

        The AI outputs ALL fields in one response:
          basic: title, url, description, image_url, published_at
          enrichment: is_crime, category, sub_category, location, region, summary, score

        If Gemini returns non-JSON or invalid output, parse_combined_output()
        returns None and the article is dropped (no partial saves).
        """
        # build_process_message creates the JSON payload the AI will process
        user_message = build_process_message(
            state["raw_payload"],                 # the raw article data
            state["source_type"],                 # "rss" or "rest"
            state.get("search_context", ""),      # DuckDuckGo results (may be "")
        )
        try:
            response = await self._llm.ainvoke([
                SystemMessage(content=COMBINED_PROCESS_PROMPT),  # extraction + classification rules
                HumanMessage(content=user_message),               # raw data + search context
            ])
            text = str(response.content)
            # parse_combined_output: strips fences, parses JSON, validates, returns dict or None
            result = parse_combined_output(text, state["raw_payload"])
        except Exception as exc:
            logger.warning("Gemini process node error: %s", exc)
            result = None

        # Return only the state key(s) this node is updating
        return {"result": result}

    # ------------------------------------------------------------------
    # STAGE 2: Post-processing with optional web search context
    # ------------------------------------------------------------------

    async def post_process(self, filter_article: dict, search_context: str = "") -> dict | None:
        """STAGE 2: Rewrite and score a crime article that passed stage 1.

        If search_context is empty, we run a quick DuckDuckGo search on the
        article title to discover reference URLs and calibrate the imp_score.
        Then we call Gemini with POST_PROCESS_PROMPT.
        """
        # Enrich search context if not already provided
        if not search_context:
            title = filter_article.get("title", "")
            if title:
                try:
                    results = await self._search.ainvoke(f"{title} crime news")
                    search_context = str(results)
                except Exception as exc:
                    logger.warning("DuckDuckGo post_process search failed (non-fatal): %s", exc)
                    search_context = ""

        user_message = build_post_process_message(filter_article, search_context)
        try:
            response = await self._llm.ainvoke([
                SystemMessage(content=POST_PROCESS_PROMPT),
                HumanMessage(content=user_message),
            ])
            text = str(response.content)
        except Exception as exc:
            logger.warning("Gemini post_process error: %s", exc)
            return None
        return parse_post_process_output(text)
