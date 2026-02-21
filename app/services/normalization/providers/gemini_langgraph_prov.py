"""
app/services/normalization/providers/gemini_langgraph_prov.py — Gemini + LangGraph Provider
=============================================================================================
The RECOMMENDED provider for this crime news application.

Two-phase AI processing:

Phase 1 — normalize() — fast direct Gemini call:
  Input: raw RSS/REST payload
  Output: title, url, description, image_url, published_at
  No tools, no search — just extraction. Takes ~1-2 seconds.

Phase 2 — enrich() — LangGraph agent with DuckDuckGo search:
  Input: normalized article (title + description + url)
  Step 1 (search_node): DuckDuckGo searches for "{title} crime news"
  Step 2 (enrich_node): Gemini reads article + search results → outputs:
    is_crime, category, sub_category, location, region, summary, importance_score
  Total: ~3-5 seconds per article.

Why LangGraph for enrichment (not a plain API call)?
  DuckDuckGo search gives the AI real-world context:
    - How widely covered is this story? → better importance_score calibration
    - Related coverage confirms location and crime type
    - AI has factual grounding instead of just guessing from 1-2 sentences

Why DuckDuckGo (not Google/Bing/Tavily)?
  - Completely free, no API key required
  - Good enough for news queries
  - Reduces operational dependencies

LangGraph graph structure:
  START → search_node → enrich_node → END

  Each "node" is an async function that:
    1. Reads relevant fields from the shared state dict
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
    ENRICHMENT_SYSTEM_PROMPT,
    NORMALIZATION_SYSTEM_PROMPT,
    _NULL_ENRICHMENT,
    build_enrichment_message,
    build_user_message,
    parse_enrichment_output,
    parse_llm_output,
)

logger = logging.getLogger(__name__)


class _EnrichState(TypedDict):
    """The shared state object passed between LangGraph nodes.

    TypedDict gives us type safety — each node knows exactly what keys exist.
    LangGraph passes this dict through the graph, with each node adding/updating fields.

    Fields:
      article:        the normalized article — read-only, set before graph starts
      search_context: DuckDuckGo results — written by search_node, read by enrich_node
      result:         final enrichment dict — written by enrich_node, read after graph ends
    """
    article: dict          # Normalized article (title, description, url)
    search_context: str    # DuckDuckGo search results (may be empty string if search failed)
    result: dict           # Final enrichment output dict


class GeminiLangGraphProvider(AIProvider):
    """Google Gemini for normalization + LangGraph agent for enrichment.

    The enrichment agent searches the web for context before classifying the article.
    This gives better importance_score accuracy and more reliable location extraction.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._model = model

        # Create the Gemini LLM via langchain-google-genai.
        # temperature=0: deterministic output — same input → same output every time.
        # This is correct for a structured extraction task (we don't want creativity).
        self._llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,   # Gemini API key from Google AI Studio or GCP
            temperature=0,            # No randomness — consistent, reliable output
        )

        # DuckDuckGo search tool — no API key needed.
        # max_results=3: 3 search results is enough to calibrate importance_score.
        # More results = better accuracy but more tokens = slower + more expensive.
        self._search = DuckDuckGoSearchResults(max_results=3)

        # Build and compile the LangGraph enrichment graph (done once at construction).
        # Compilation locks in the graph structure — can't add nodes after this.
        self._graph = self._build_graph()

    @property
    def model_id(self) -> str:
        """Identifier stored in raw_ingestion_events for audit trail."""
        return f"ai:gemini_langgraph:{self._model}"

    # ------------------------------------------------------------------
    # AIProvider interface implementation
    # ------------------------------------------------------------------

    async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
        """Direct Gemini call to extract canonical fields from a raw payload.

        No tools, no graph — just a single LLM call.
        Uses langchain-google-genai's ainvoke() for async execution.
        Messages are passed as a list of Message objects (HumanMessage, SystemMessage).

        Returns the canonical article dict or None on failure.
        """
        user_message = build_user_message(raw_payload, source_type)
        try:
            # ainvoke() sends messages to Gemini and returns an AIMessage object
            response = await self._llm.ainvoke([
                SystemMessage(content=NORMALIZATION_SYSTEM_PROMPT),  # instructions
                HumanMessage(content=user_message),                   # the data to process
            ])
            # response.content is the text of the AI's response
            text = str(response.content)
        except Exception as exc:
            logger.error("Gemini normalize error: %s", exc)
            return None

        # parse_llm_output handles JSON parsing + Pydantic validation
        return parse_llm_output(text, raw_payload)

    async def enrich(self, article: dict) -> dict:
        """Run the LangGraph enrichment graph: search → enrich.

        Invokes the pre-built graph with the article as input.
        The graph runs search_node then enrich_node and returns the final state.

        Returns the enrichment dict or _NULL_ENRICHMENT if the graph fails.
        The outer try/except is a final safety net — any unexpected error
        still results in a safe fallback (never drops the article).
        """
        try:
            # ainvoke() runs the graph asynchronously and returns the final state
            final_state = await self._graph.ainvoke({
                "article": article,
                "search_context": "",   # will be filled by search_node
                "result": {},           # will be filled by enrich_node
            })
            # Get the result from final state, fall back to NULL if empty
            return final_state.get("result") or _NULL_ENRICHMENT
        except Exception as exc:
            logger.warning("LangGraph enrichment graph error: %s", exc)
            return _NULL_ENRICHMENT  # Fail safe — article is still saved

    # ------------------------------------------------------------------
    # LangGraph graph construction
    # ------------------------------------------------------------------

    def _build_graph(self):
        """Build and compile the two-node enrichment LangGraph.

        Graph structure:
          START → search_node → enrich_node → END

        StateGraph takes the state TypedDict so it knows the shape of the
        data flowing through the graph.

        .compile() returns a runnable graph (like a function that takes state
        and returns final state). We call this with .ainvoke() in enrich().
        """
        builder = StateGraph(_EnrichState)

        # Register nodes — each node is an async method on this class.
        # "search" and "enrich" are just labels used in add_edge() calls.
        builder.add_node("search", self._search_node)
        builder.add_node("enrich", self._enrich_node)

        # Define edges — the execution order:
        # START is a built-in LangGraph constant meaning "the beginning"
        # END is a built-in constant meaning "graph is done, return state"
        builder.add_edge(START, "search")    # first: run search
        builder.add_edge("search", "enrich") # then: run enrich
        builder.add_edge("enrich", END)      # then: done

        # Compile locks the graph structure and returns a runnable object
        return builder.compile()

    async def _search_node(self, state: _EnrichState) -> dict:
        """Node 1: Search DuckDuckGo for context about this article.

        Queries: "{title} crime news"
        Returns: {"search_context": "snippet 1... snippet 2... snippet 3..."}

        If the search fails (network error, rate limit, etc.), returns empty string.
        The next node (enrich) will still work — it just won't have search context.
        Error handling here is intentionally broad: any search failure is non-fatal.
        """
        title = state["article"].get("title", "")
        try:
            # ainvoke() searches DuckDuckGo and returns a string with results
            # The results typically include title, snippet, and URL for each result
            results = await self._search.ainvoke(f"{title} crime news")
            return {"search_context": str(results)}
        except Exception as exc:
            # Search failed — log it but don't fail the entire enrichment
            logger.warning("DuckDuckGo search failed (non-fatal): %s", exc)
            return {"search_context": ""}  # Empty context = AI enriches without web data

    async def _enrich_node(self, state: _EnrichState) -> dict:
        """Node 2: Call Gemini to produce the structured enrichment JSON.

        Receives: article dict + search_context (from search_node)
        Sends to Gemini: title + description + url + web search results
        Returns: {"result": {is_crime, category, sub_category, location, region, summary, score}}

        If Gemini returns non-JSON or invalid schema, parse_enrichment_output()
        returns _NULL_ENRICHMENT — article is still saved with NULL fields.
        """
        # build_enrichment_message creates a compact JSON payload with optional search context
        user_message = build_enrichment_message(
            state["article"],                    # the article to classify
            state.get("search_context", "")      # context from search_node (may be "")
        )
        try:
            response = await self._llm.ainvoke([
                SystemMessage(content=ENRICHMENT_SYSTEM_PROMPT),  # classification instructions
                HumanMessage(content=user_message),                # article + search context
            ])
            text = str(response.content)
            # Parse and validate the JSON — returns _NULL_ENRICHMENT on parse error
            result = parse_enrichment_output(text)
        except Exception as exc:
            logger.warning("Gemini enrich node error: %s", exc)
            result = dict(_NULL_ENRICHMENT)  # dict() creates a copy (don't modify the original)

        # Return only the state key(s) this node is updating
        return {"result": result}
