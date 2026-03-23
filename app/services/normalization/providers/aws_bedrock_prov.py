import json
import logging
import asyncio
import boto3

from app.core.config import settings

from app.services.normalization.providers.base import (
    AIProvider,
    SINGLE_PROCESS_PROMPT,
    build_process_message,
    parse_single_output,
)

logger = logging.getLogger(__name__)


class BedrockProvider(AIProvider):
    """
    AWS Bedrock provider using Anthropic Claude models
    Compatible with existing AIProvider interface
    """

    def __init__(self, model: str, region: str | None = None) -> None:

        self._model = model

        self._client = boto3.client(
          "bedrock-runtime",
          aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
          aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
          region_name=settings.AWS_DEFAULT_REGION,
        )

        self._provider_label = "bedrock"

        logger.info(
          "BedrockProvider initialized with model=%s region=%s",
          self._model,
          settings.AWS_DEFAULT_REGION,
        )


    @property
    def model_id(self) -> str:
        return f"ai:{self._provider_label}:{self._model}"


    async def process(
      self,
      raw_payload: dict,
      source_type: str
    ) -> dict | None:

      user_message = build_process_message(raw_payload, source_type)

      # Llama 3 expects prompt format, not messages format
      prompt = f"""
      <|begin_of_text|>
      <|start_header_id|>system<|end_header_id|>
      {SINGLE_PROCESS_PROMPT}
      <|eot_id|>

      <|start_header_id|>user<|end_header_id|>
      {user_message}
      <|eot_id|>

      <|start_header_id|>assistant<|end_header_id|>
      """

      body = {
          "prompt": prompt,
          "max_gen_len": 2048,
          "temperature": 0,
      }
      # LOG 1 → confirms provider is being used
      logger.info(
          "BEDROCK CALL → model=%s | source_type=%s",
          self._model,
          source_type
      )

      try:
        response = await asyncio.to_thread(
          self._client.invoke_model,
          modelId=self._model,
          body=json.dumps(body),
          contentType="application/json",
          accept="application/json",
        )

        # LOG 2 → confirms API call success
        logger.info("BEDROCK RESPONSE received")

        result = json.loads(
          response["body"].read()
        )

        # LOG 3 → shows token usage & stop reason
        logger.info(
            "BEDROCK RESULT → stop_reason=%s | tokens=%s",
            result.get("stop_reason"),
            result.get("generation_token_count"),
        )

        text = result.get("generation", "")

        # LOG 4 → preview small part of output
        logger.info(
            "BEDROCK OUTPUT PREVIEW → %.120s",
            text.replace("\n", " ")
        )

        if not text:
            logger.warning("BEDROCK returned EMPTY text")

      except Exception as exc:
        logger.error("Bedrock provider error: %s", exc)
        return None

      return parse_single_output(text, raw_payload)