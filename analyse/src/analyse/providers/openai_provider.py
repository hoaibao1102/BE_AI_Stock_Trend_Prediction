from __future__ import annotations

from time import perf_counter
from typing import Any

from openai import AsyncOpenAI

from analyse.config.settings import Settings, get_settings
from analyse.prompts.report_prompts import build_report_prompt
from analyse.providers.base import BaseLLMProvider
from analyse.schemas.llm import (
    LLMGenerateResult,
    LLMReportOutput,
)


class OpenAIProvider(BaseLLMProvider):
    provider_name = "openai"

    def __init__(
        self,
        settings: Settings | None = None,
        client: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.openai_model
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.settings.openai_api_key,
                timeout=self.settings.openai_timeout_ms / 1000,
                max_retries=2,
            )

        return self._client

    async def generate_report_json(
        self,
        payload: dict[str, Any],
        schema: dict[str, Any] | None = None,
    ) -> LLMGenerateResult:
        if not self.settings.openai_enabled:
            return LLMGenerateResult(
                provider="openai",
                model=self.model,
                status="disabled",
                warnings=["OpenAI provider đang bị tắt."],
            )

        if (
            not self.settings.openai_api_key
            and self._client is None
        ):
            return LLMGenerateResult(
                provider="openai",
                model=self.model,
                status="failed",
                warnings=["Thiếu cấu hình OPENAI_API_KEY."],
            )

        started_at = perf_counter()

        try:
            prompt = build_report_prompt(
                context=payload,
                schema=schema,
            )

            client = self._get_client()

            response = await client.responses.parse(
                model=self.model,
                input=prompt,
                text_format=LLMReportOutput,
                max_output_tokens=(
                    self.settings.openai_max_output_tokens
                ),
                temperature=self.settings.openai_temperature,
            )

            parsed = response.output_parsed

            if parsed is None:
                latency_ms = int(
                    (perf_counter() - started_at) * 1000
                )

                return LLMGenerateResult(
                    provider="openai",
                    model=self.model,
                    status="failed",
                    latency_ms=latency_ms,
                    warnings=[
                        "OpenAI không trả về structured output."
                    ],
                )

            validated = LLMReportOutput.model_validate(parsed)

            latency_ms = int(
                (perf_counter() - started_at) * 1000
            )

            return LLMGenerateResult(
                provider="openai",
                model=self.model,
                status="success",
                latency_ms=latency_ms,
                data=validated.model_dump(),
                warnings=[],
            )

        except Exception as exc:
            latency_ms = int(
                (perf_counter() - started_at) * 1000
            )

            return LLMGenerateResult(
                provider="openai",
                model=self.model,
                status="failed",
                latency_ms=latency_ms,
                warnings=[
                    "Không thể tạo phân tích bằng OpenAI: "
                    f"{type(exc).__name__}"
                ],
            )