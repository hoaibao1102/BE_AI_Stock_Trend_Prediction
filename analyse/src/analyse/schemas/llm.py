from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from analyse.schemas.common import ProviderName, SourceStatus


class LLMReportPayload(BaseModel):
    provider: ProviderName
    symbol: str
    context: dict[str, Any]
    response_schema: dict[str, Any] = Field(default_factory=dict)


class LLMGenerateResult(BaseModel):
    provider: ProviderName
    model: str
    status: SourceStatus = "not_implemented"
    latency_ms: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
class LLMSystemDecisionOutput(BaseModel):
    reasons: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class LLMMarkdownOutput(BaseModel):
    content: str | None = None

    model_config = ConfigDict(extra="forbid")


class LLMReportOutput(BaseModel):
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    system_decision: LLMSystemDecisionOutput = Field(
        default_factory=LLMSystemDecisionOutput
    )
    markdown_report: LLMMarkdownOutput = Field(
        default_factory=LLMMarkdownOutput
    )
    data_quality_notes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")