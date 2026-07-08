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


class LLMActionItemOutput(BaseModel):
    action: str = Field(default="", description="Hành động theo dõi định tính, không phải lệnh mua/bán.")
    condition: str = Field(default="", description="Điều kiện kích hoạt hoặc điều kiện xác nhận.")
    price_zone: float | str | None = Field(default=None, description="Chỉ dùng nếu có nguồn/cách tính rõ; nếu thiếu thì null.")
    price_zone_note: str = Field(default="", description="Ghi chú định tính về vùng quan sát nếu thiếu vùng giá đáng tin cậy.")
    position_size_note: str = Field(default="", description="Ghi chú tỷ trọng mô phỏng theo cấu hình, không cá nhân hóa.")
    risk_note: str = Field(default="", description="Ghi chú rủi ro và disclaimer không phải khuyến nghị mua/bán.")
    source_basis: str = Field(default="", description="Nguồn/cơ sở dữ liệu hoặc evidence dùng để tạo item.")

    model_config = ConfigDict(extra="allow")


class LLMActionPlanOutput(BaseModel):
    short_term: list[LLMActionItemOutput] = Field(default_factory=list, json_schema_extra={"minItems": 2})
    medium_term: list[LLMActionItemOutput] = Field(default_factory=list, json_schema_extra={"minItems": 2})
    watch_points: list[LLMActionItemOutput] = Field(default_factory=list, json_schema_extra={"minItems": 3})
    risk_management: list[LLMActionItemOutput] = Field(default_factory=list, json_schema_extra={"minItems": 3})

    model_config = ConfigDict(extra="forbid")


class LLMScenarioOutput(BaseModel):
    name: str | None = None
    scenario: str | None = None
    probability_pct: int | None = None
    time_horizon: str | None = None
    condition: str | None = None
    expected_behavior: str | None = None
    response: str | None = None
    supporting_signals: list[str] = Field(default_factory=list)
    invalidation_signals: list[str] = Field(default_factory=list)
    risk: str | None = None
    risk_note: str | None = None

    model_config = ConfigDict(extra="allow")


class LLMChecklistOutput(BaseModel):
    label: str = ""
    note: str | None = None
    status: str = "pending"
    source_basis: str = "Dữ liệu hiện có"

    model_config = ConfigDict(extra="allow")


class LLMEvidenceOutput(BaseModel):
    metric_name: str = Field(..., description="Tên chỉ số/số liệu, VD 'P/E', 'Doanh thu Q1/2026'")
    value: float | str = Field(..., description="Giá trị (số hoặc chuỗi format sẵn)")
    unit: str | None = Field(default=None, description="Đơn vị: VND, %, tỷ VND, cổ phiếu...")
    source: str = Field(..., description="Nguồn gốc của số liệu")
    source_url: str | None = Field(default=None, description="URL bài báo gốc")
    published_at: str | None = Field(default=None, description="ISO 8601 thời điểm của số liệu/bài báo")
    note: str | None = Field(default=None, description="Ghi chú thêm")

    model_config = ConfigDict(extra="allow")


class LLMReportOutput(BaseModel):
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    system_decision: LLMSystemDecisionOutput = Field(default_factory=LLMSystemDecisionOutput)
    markdown_report: LLMMarkdownOutput = Field(default_factory=LLMMarkdownOutput)
    data_quality_notes: list[str] = Field(default_factory=list)
    executive_forecast: dict[str, Any] = Field(default_factory=dict)
    quantitative_signal_summary: dict[str, Any] = Field(default_factory=dict)
    action_plan: LLMActionPlanOutput = Field(default_factory=LLMActionPlanOutput)
    scenarios: list[LLMScenarioOutput] = Field(default_factory=list, json_schema_extra={"minItems": 3, "maxItems": 3})
    risk_map: list[dict[str, Any] | str] = Field(default_factory=list)
    checklist: list[LLMChecklistOutput] = Field(default_factory=list, json_schema_extra={"minItems": 5})
    evidence_table: list[dict[str, Any]] = Field(default_factory=list)
    evidence_pool: list[LLMEvidenceOutput] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")
