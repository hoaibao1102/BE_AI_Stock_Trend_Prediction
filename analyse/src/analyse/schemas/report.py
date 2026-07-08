from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from analyse.schemas.common import ProviderName, SourceStatus
from analyse.schemas.stock import AnalysisOptions


class AnalyseOneReportRequest(BaseModel):
    provider: ProviderName | None = None
    model: str | None = None
    symbol: str
    scope_exchange: str = Field(default="HOSE", validation_alias=AliasChoices("scopeExchange", "exchange", "scope_exchange"), serialization_alias="scopeExchange")
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    force_refresh: bool = Field(default=False, alias="forceRefresh")

    model_config = ConfigDict(populate_by_name=True)


class ProviderMetadata(BaseModel):
    name: ProviderName
    model: str
    status: SourceStatus = "not_implemented"
    latency_ms: int = 0


class DataSourceStatus(BaseModel):
    name: str
    type: str
    status: SourceStatus
    category: str | None = None
    status_label: str | None = None
    summary: str | None = None
    detail: str | None = None
    source_type: str | None = None
    debug_detail: str | None = None
    evidence_count: int | None = None
    last_crawled_at: str | None = None


class MarkdownReport(BaseModel):
    available: bool = False
    output_path: str | None = None
    content: str | None = None


class HtmlReport(BaseModel):
    available: bool = False
    output_path: str | None = None
    content: str | None = None
    template_name: str | None = None


class ReportData(BaseModel):
    history_id: str | None = Field(default=None, exclude=True)
    report_id: str
    generated_at: str
    symbol: str
    company: str | None = None
    scope_exchange: str = "HOSE"
    language: str = "vi"
    summary_schema_version: str = "1.0"
    analysis_status: str = "success"
    history_status: str = "disabled"
    source_status: str = "success"
    report_status: str = "success"
    provider: ProviderMetadata
    data_sources: list[DataSourceStatus] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    markdown_report: MarkdownReport = Field(default_factory=MarkdownReport)
    html_report: HtmlReport = Field(default_factory=HtmlReport)
    warnings: list[str] = Field(default_factory=list)


class ReportGenerateResponse(BaseModel):
    code: int = 200
    message: str = "Tạo dữ liệu report thành công"
    data: ReportData
