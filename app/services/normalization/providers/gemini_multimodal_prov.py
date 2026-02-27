import logging
from typing import Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.services.normalization.providers.base import AIProvider
from app.services.source_normalizer import parse_date

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------

_SubCat = Literal[
    "murder", "theft", "fraud", "cybercrime", "terrorism",
    "corruption", "drugs", "violence", "trafficking", "other",
]
class SingleClassification(BaseModel):
    """Structured output from a single Gemini call: classify + extract + rewrite."""

    is_crime: bool = Field(
        description="True if the article is PRIMARILY about criminal activity."
    )
    title: str = Field(
        default="",
        description="Original headline extracted from the article (required when is_crime=true).",
    )
    rewritten_title: str = Field(
        default="",
        description=(
            "Headline rephrased in your own words. Max 15 words, active voice. "
            "Include location if known. Do NOT copy source verbatim."
        ),
    )
    url: str | None = Field(
        default=None,
        description="Canonical article URL (absolute HTTP/HTTPS). null if not found.",
    )
    description: str | None = Field(
        default=None,
        description="Original source text, 1-3 sentences (clean HTML). null if absent.",
    )
    rewritten_description: str = Field(
        default="",
        description=(
            "3-5 sentence news card description in your own words. "
            "Cover: what happened, who is involved, where, key context. "
            "Do NOT copy source text verbatim."
        ),
    )
    image_url: str | None = Field(
        default=None,
        description="Thumbnail image URL (absolute HTTP/HTTPS). null if not found.",
    )
    published_at: str | None = Field(
        default=None,
        description="Publication datetime in ISO 8601 UTC format. null if unknown.",
    )
    sub_category_ids: list[_SubCat] = Field(
        default=[],
        description=(
            "ALL applicable crime sub-types (multi-label). "
            "Example: kidnapping-for-ransom → ['violence', 'trafficking']. "
            "Empty list for non-crime articles."
        ),
    )
    location: str | None = Field(
        default=None,
        description="City and country where the crime occurred, e.g. 'Mumbai, India'. null if unknown.",
    )
    imp_score: int = Field(
        default=50,
        ge=1,
        le=100,
        description=(
            "Importance score 1-100. "
            "1-20: hyperlocal/minor. 21-40: local/notable. "
            "41-60: regional/significant. 61-80: national/high-impact. "
            "81-100: international/breaking."
        ),
    )


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class ProcessState(TypedDict):
    raw_payload: dict
    source_type: str
    candidate_title: str
    candidate_image_url: str | None
    result: dict | None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SINGLE_CLASSIFY_SYSTEM_PROMPT = """\
You are a crime news processing engine for a real-time crime news aggregation platform.
You receive a raw news article payload (RSS or REST API JSON). If a news image is provided
alongside the text, use visual cues to help confirm the crime type.

STEP 1 — Crime check:
Set is_crime=true ONLY if the article's PRIMARY subject is criminal activity.
Accidents, disasters, politics without crime → is_crime=false.
If is_crime=false: leave all other fields at their defaults.

STEP 2 (only if is_crime=true):
Extract, classify, AND produce publication-ready content in one pass.
- title: original headline from the source — do NOT rephrase.
- rewritten_title: rephrase in your own words (max 15 words, active voice, include location).
- description: original source text as-is (1-3 sentences, clean HTML tags).
- rewritten_description: 3-5 sentences in your own words (what, who, where, context).
- sub_category_ids: ALL applicable crime types (multi-label list).
- location: prefer specific city + state/country over vague regions.
- imp_score: calibrate based on crime severity, victim count, geographic scope, official involvement.

Return a complete, valid JSON response matching the required schema."""


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------

class GeminiMultimodalLangGraphProvider(AIProvider):
    """
    Gemini Flash multimodal provider with a single LangGraph graph.

    Graph: extract_node (lightweight) → classify_node (Gemini structured output)

    Key capabilities:
      • Multimodal classification — passes article image to Gemini when available
      • Structured output — with_structured_output(Pydantic) → no JSON parsing
      • Single AI call — extracts, classifies, rewrites, and scores in one pass
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
    ) -> None:
        self._model_name = model

        self._llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0,
        )

        self._classify_llm = self._llm.with_structured_output(
            SingleClassification, method="json_schema"
        )

        self._graph = self._build_graph()

    @property
    def model_id(self) -> str:
        return f"ai:gemini_multimodal:{self._model_name}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        try:
            final_state: ProcessState = await self._graph.ainvoke({
                "raw_payload": raw_payload,
                "source_type": source_type,
                "candidate_title": "",
                "candidate_image_url": None,
                "result": None,
            })
            return final_state.get("result")
        except Exception as exc:
            logger.warning("GeminiMultimodal graph error: %s", exc)
            return None

    def _build_graph(self):
        builder = StateGraph(ProcessState)
        builder.add_node("extract", self._extract_node)
        builder.add_node("classify", self._classify_node)

        builder.add_edge(START, "extract")
        builder.add_edge("extract", "classify")
        builder.add_edge("classify", END)

        return builder.compile()

    async def _extract_node(self, state: ProcessState) -> dict:
        """Lightweight field extraction without AI — provides candidate title and image."""
        raw = state["raw_payload"]

        title = (
            raw.get("title")
            or raw.get("headline")
            or raw.get("name")
            or raw.get("subject")
            or ""
        )
        if not title:
            title = str(raw)[:120]

        image_url: str | None = None
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

    async def _classify_node(self, state: ProcessState) -> dict:
        """Single Gemini call: classify + extract + rewrite + score."""
        import json as _json

        raw = state["raw_payload"]
        source_type = state["source_type"]
        image_url = state.get("candidate_image_url")

        user_text_parts = [
            f"Source type: {source_type}",
            "",
            "Raw article payload:",
            _json.dumps(raw, default=str, indent=2),
        ]
        user_text = "\n".join(user_text_parts)

        content: list = [{"type": "text", "text": user_text}]
        if image_url and image_url.startswith(("http://", "https://")):
            content.append({
                "type": "image_url",
                "image_url": {"url": image_url},
            })
            logger.debug("classify_node: multimodal — image: %s", image_url[:80])

        try:
            classification: SingleClassification = await self._classify_llm.ainvoke([
                SystemMessage(content=_SINGLE_CLASSIFY_SYSTEM_PROMPT),
                HumanMessage(content=content),
            ])
        except Exception as exc:
            logger.warning("classify_node Gemini error: %s", exc)
            return {"result": None}

        if not classification.is_crime:
            return {"result": {"is_crime": False}}

        if not classification.title:
            logger.warning("classify_node: crime article has no title — dropping")
            return {"result": None}

        published_at = parse_date(classification.published_at) if classification.published_at else None

        url = classification.url
        if not url:
            fallback = raw.get("link") or raw.get("url") or ""
            if isinstance(fallback, str) and fallback.startswith(("http://", "https://")):
                url = fallback

        sub_category_ids = [str(s) for s in classification.sub_category_ids]

        result = {
            "is_crime": True,
            "title": classification.title,
            "rewritten_title": classification.rewritten_title,
            "url": url or "",
            "description": classification.description,
            "rewritten_description": classification.rewritten_description,
            "image_url": classification.image_url or image_url,
            "published_at": published_at,
            "raw_payload": raw,
            "sub_category": sub_category_ids[0] if sub_category_ids else None,
            "sub_category_ids": sub_category_ids,
            "location": classification.location,
            "imp_score": classification.imp_score,
        }

        return {"result": result}
