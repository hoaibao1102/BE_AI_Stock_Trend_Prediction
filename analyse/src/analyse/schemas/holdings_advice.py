"""
Pydantic schemas cho Holdings Advice feature.
POST /api/ai-reports/holdings-advice
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Nguồn evidence — khớp với 3 nguồn dữ liệu trong plan:
#   backend_price  → 7 ngày giá từ Backend API (get_stock_chart 7d)
#   history_*      → report_json.summary đã lưu trong ngày (analyse history)
#   *_news         → external research (CafeF / Vietstock / Google News RSS)
EvidenceSource = Literal[
    "backend_price",
    "history_bctc",
    "history_market",
    "history_peer",
    "history_hose",
    "cafef_news",
    "vietstock_news",
    "google_news",
]

# Các nguồn news BẮT BUỘC phải có source_url để FE mở bài báo gốc.
_NEWS_SOURCES = {"cafef_news", "vietstock_news", "google_news"}



class HoldingAdviceItem(BaseModel):
    """Một mã cổ phiếu trong holdings kèm thông tin P&L."""

    symbol: str
    exchange: str = Field(default="HOSE")
    company_name: str | None = None
    average_cost: float = Field(..., description="Giá vốn trung bình (VND/cổ phiếu)")
    quantity: int = Field(..., description="Số lượng cổ phiếu đang nắm giữ")
    close_price: float | None = Field(default=None, description="Giá đóng cửa hiện tại")
    market_value: float | None = Field(default=None, description="Giá trị thị trường hiện tại")
    cost: float | None = Field(default=None, description="Tổng vốn đầu tư")
    unrealized_pnl: float | None = Field(default=None, description="Lãi/lỗ chưa thực hiện (VND)")
    unrealized_pnl_pct: float | None = Field(
        default=None, alias="unrealizedPnlPct", description="% lãi/lỗ"
    )
    status: Literal["PROFIT", "LOSS"] | None = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class HoldingsAdviceRequest(BaseModel):
    """Request body cho POST /api/ai-reports/holdings-advice."""

    items: list[HoldingAdviceItem] = Field(
        ..., description="Danh sách holdings cần phân tích"
    )
    force_refresh: bool = Field(
        default=False,
        alias="forceRefresh",
        description="Bỏ qua same-day cache, tạo lại báo cáo mới (mặc định: False)",
    )

    model_config = ConfigDict(populate_by_name=True)


class HoldingAdviceEvidence(BaseModel):
    """
    Một số liệu/bằng chứng cụ thể dùng để giải thích quyết định đầu tư.

    Bắt buộc có `value` cụ thể (số hoặc chuỗi chứa số) — không chấp nhận evidence chung chung.
    Với các nguồn tin tức (*_news), `source_url` là BẮT BUỘC để FE hiển thị link bài báo gốc.
    """

    metric_name: str = Field(..., description="Tên chỉ số/số liệu, VD 'P/E', 'Doanh thu Q1/2026'")
    value: float | str | None = Field(default=None, description="Giá trị (số hoặc chuỗi format sẵn)")
    unit: str | None = Field(default=None, description="Đơn vị: VND, %, tỷ VND, cổ phiếu...")
    source: EvidenceSource = Field(..., description="Nguồn gốc của số liệu")
    source_url: str | None = Field(
        default=None,
        alias="sourceUrl",
        description="URL bài báo gốc — BẮT BUỘC khi source là *_news",
    )
    published_at: str | None = Field(
        default=None,
        alias="publishedAt",
        description="ISO 8601 thời điểm của số liệu/bài báo",
    )
    note: str | None = Field(default=None, description="Ghi chú thêm (kỳ báo cáo, kỳ so sánh...)")

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _require_url_for_news(self) -> HoldingAdviceEvidence:
        if self.source in _NEWS_SOURCES and not (self.source_url or "").strip():
            raise ValueError(
                f"Evidence từ nguồn '{self.source}' bắt buộc phải có source_url (link bài báo)."
            )
        return self


class HoldingAdviceCriterion(BaseModel):
    """Một tiêu chí giải thích, kèm danh sách evidence hỗ trợ."""

    title: str = Field(..., description="Tên tiêu chí, VD 'Vị thế giá vốn'")
    verdict: str = Field(..., description="Kết luận 1-2 câu có số liệu cụ thể")
    evidence: list[HoldingAdviceEvidence] = Field(
        default_factory=list, description="Evidence hỗ trợ tiêu chí này (tối đa 5)"
    )


class HoldingAdviceReasoning(BaseModel):
    """Cấu trúc giải thích quyết định đầu tư phân rã theo 5 tiêu chí rõ ràng."""

    portfolio_fit: str = Field(..., description="1. Đánh giá vị thế mua & lãi/lỗ hiện tại.")
    financial_health: str = Field(..., description="2. Đánh giá tăng trưởng doanh thu/lợi nhuận gần đây từ BCTC.")
    valuation_peer: str = Field(..., description="3. So sánh P/E, P/B định giá tương quan trong ngành.")
    market_momentum: str = Field(..., description="4. Xu hướng kỹ thuật ngắn hạn & bối cảnh thị trường VN-Index.")
    action_plan: str = Field(..., description="5. Kế hoạch hành động cụ thể kèm vùng giá target/stop-loss.")

    # Structured version (thêm mới) — song song với 5 field text ở trên để backward compat.
    # criteria[] có đúng 5 phần tử, thứ tự cố định khớp 5 field trên.
    criteria: list[HoldingAdviceCriterion] = Field(
        default_factory=list,
        description="Giải thích structured 5 tiêu chí kèm evidence có số liệu + nguồn",
    )
    evidence_pool: list[HoldingAdviceEvidence] = Field(
        default_factory=list,
        alias="evidencePool",
        description="Toàn bộ evidence đã gom & dedupe, cho FE dễ quét nhanh",
    )

    model_config = ConfigDict(populate_by_name=True)


class HoldingAdviceResult(BaseModel):
    """Kết quả khuyến nghị cho một mã cổ phiếu."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    symbol: str
    exchange: str
    company_name: str | None = None

    # P&L snapshot (echo lại từ request để FE dùng trực tiếp)
    average_cost: float | None = None
    quantity: int | None = None
    close_price: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    status: str | None = None

    # AI output
    decision: str | None = Field(
        default=None, description="BUY / SELL / HOLD từ AI hoặc compare_history"
    )
    pnl_signal: str | None = Field(
        default=None,
        description=(
            "Rule-based signal: STRONG_PROFIT_HOLD / PROFIT_HOLD / NEUTRAL / "
            "LOSS_WATCH / LOSS_REVIEW"
        ),
    )
    total_score: float | None = None
    risk_score: float | None = None
    data_confidence: float | None = None
    reasoning: str | None = Field(
        default=None, description="Tóm tắt lý do khuyến nghị (định dạng text tự do/legacy)"
    )
    reasoning_skeleton: HoldingAdviceReasoning | None = Field(
        default=None, alias="reasoningSkeleton", description="Giải thích chi tiết theo cấu trúc 5 tiêu chí chuẩn hóa"
    )

    # Metadata
    source: Literal["cache", "generated", "fallback"] = "fallback"
    report_id: str | None = Field(
        default=None, alias="reportId", description="ID của báo cáo phân tích chi tiết liên quan"
    )
    analysed_at: str | None = Field(
        default=None, description="ISO 8601 thời điểm báo cáo được tạo/lấy từ cache"
    )
    error: str | None = Field(
        default=None, description="Thông báo lỗi nếu phân tích thất bại (graceful degradation)"
    )


class HoldingsAdviceResponse(BaseModel):
    """Response data cho POST /api/ai-reports/holdings-advice."""

    generated_at: str
    advice: list[HoldingAdviceResult]
    total_items: int
    cached_count: int = 0
    generated_count: int = 0
    fallback_count: int = 0
