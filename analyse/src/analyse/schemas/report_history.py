from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReportHistoryFilters(BaseModel):
    symbol: str | None = None
    exchange: str | None = None
    provider: str | None = None
    model: str | None = None
    from_date: datetime | None = Field(default=None, alias="fromDate")
    to_date: datetime | None = Field(default=None, alias="toDate")
    page: int = 1
    limit: int = 20

    model_config = ConfigDict(populate_by_name=True)


class ReportHistoryListItem(BaseModel):
    id: str
    report_id: str
    symbol: str
    exchange: str
    company: str | None = None
    company_name: str | None = None
    provider: str
    model: str
    total_score: float | None = None
    score: float | None = None
    risk_score: float | None = None
    risk_level: str | None = None
    data_confidence: float | None = None
    decision_label: str | None = None
    status: str | None = None
    created_at: datetime
    generated_at: datetime | None = None


class ReportHistoryListData(BaseModel):
    items: list[ReportHistoryListItem]
    page: int
    limit: int
    total: int
    total_pages: int = 1


class ReportHistoryDetailData(BaseModel):
    id: str
    report_id: str
    report_json: dict[str, Any]

class ReportHistoryCompareQuery(BaseModel):
 
    symbol: str
    exchange: str | None = None
    baseline_history_id: str | None = Field(default=None, alias="baselineHistoryId")
    latest_history_id: str | None = Field(default=None, alias="latestHistoryId")
 
    model_config = ConfigDict(populate_by_name=True)
 
 
class ReportHistoryCompareItem(BaseModel):
 
    id: str
    report_id: str
    created_at: datetime
    provider: str
    model: str
    total_score: float | None = None
    risk_score: float | None = None
    data_confidence: float | None = None
    decision_label: str | None = None
 
 
class ReportHistoryCompareData(BaseModel):
 
    symbol: str
    exchange: str
    baseline: ReportHistoryCompareItem
    latest: ReportHistoryCompareItem
    score_delta: float | None = None
    risk_delta: float | None = None
    confidence_delta: float | None = None
    trend: str  # IMPROVING | WORSENING | SIDEWAYS
    trend_label: str  # "Cải thiện" | "Xấu đi" | "Đi ngang"
    recommendation: str  # BUY | SELL | HOLD | WATCH
    recommendation_label: str  # "Mua" | "Bán" | "Giữ" | "Theo dõi"
    reasons: list[str] = Field(default_factory=list)
    is_reference_only: bool = True