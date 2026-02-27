import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.services.normalization.providers.base import (
    AIProvider,
    SINGLE_PROCESS_PROMPT,
    build_process_message,
    parse_single_output,
)

logger = logging.getLogger(__name__)


class GeminiLangGraphProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._model = model
        self._llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0,
        )

    @property
    def model_id(self) -> str:
        return f"ai:gemini_langgraph:{self._model}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        user_message = build_process_message(raw_payload, source_type)
        try:
            response = await self._llm.ainvoke([
                SystemMessage(content=SINGLE_PROCESS_PROMPT),
                HumanMessage(content=user_message),
            ])
            text = str(response.content)
        except Exception as exc:
            logger.warning("GeminiLangGraph process error: %s", exc)
            return None
        return parse_single_output(text, raw_payload)
