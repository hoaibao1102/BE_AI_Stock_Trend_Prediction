from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from analyse.services.holdings_advice_service import HoldingsAdviceService
from analyse.schemas.holdings_advice import HoldingAdviceItem, HoldingsAdviceRequest
from analyse.services.user_identity_service import CurrentUserIdentity


class FakeReportHistoryListItem:
    def __init__(self, id, symbol, exchange, decision_label, created_at):
        self.id = id
        self.symbol = symbol
        self.exchange = exchange
        self.decision_label = decision_label
        self.created_at = created_at
        self.total_score = 75.0
        self.risk_score = 30.0
        self.data_confidence = 90.0


class FakeReportHistoryDetailData:
    def __init__(self, id, report_id, report_json):
        self.id = id
        self.report_id = report_id
        self.report_json = report_json


@pytest.mark.asyncio
async def test_holdings_advice_cache_hit_flow():
    # 1. Setup mock dependencies
    mock_settings = MagicMock()
    mock_settings.analyse_timezone = "Asia/Ho_Chi_Minh"
    mock_settings.enable_external_research = False

    mock_backend = AsyncMock()
    # Mock stock chart for 7d source
    mock_backend.get_stock_chart.return_value = {
        "data": [
            {"time": "2026-07-01", "close": 100.0, "volume": 1000},
            {"time": "2026-07-07", "close": 110.0, "volume": 1200}
        ]
    }

    # Mock user identity
    mock_user_identity = AsyncMock()
    mock_user_identity.resolve_current_user.return_value = CurrentUserIdentity(
        mongo_user_id="user-123", email="user@test.com"
    )

    # Mock history service list and detail
    mock_history = AsyncMock()
    cache_item = FakeReportHistoryListItem("hist-1", "HPG", "HOSE", "BUY", datetime.now(timezone.utc))
    list_data = MagicMock()
    list_data.total = 1
    list_data.items = [cache_item]
    mock_history.list_history.return_value = list_data

    # Mock full JSON inside history detail
    mock_report_json = {
        "data": {
            "report_id": "report-999",
            "symbol": "HPG",
            "scope_exchange": "HOSE",
            "summary": {
                "system_decision": {
                    "status": "BUY",
                    "reasons": [
                        "VỊ THẾ: Vùng giá hợp lý.",
                        "SỨC KHỎE TÀI CHÍNH: Doanh thu ổn định.",
                        "ĐỊNH GIÁ & ĐỐI THỦ: P/E thấp.",
                        "XU HƯỚNG & THỊ TRƯỜNG: VN-Index uptrend.",
                        "NGUYÊN TẮC HÀNH ĐỘNG: Mua tích lũy."
                    ]
                },
                "scores": {
                    "overall_score": 75.0,
                    "risk_score": 30.0,
                    "score_confidence_normalized": 0.9
                },
                "bctc_3q": {
                    "periods": [
                        {
                            "quarter": 1,
                            "year": 2026,
                            "revenue": 15000000.0,
                            "profit_after_tax": 2500000.0
                        }
                    ]
                }
            }
        }
    }
    detail_data = FakeReportHistoryDetailData("hist-1", "report-999", mock_report_json)
    mock_history.get_history_detail.return_value = detail_data

    # If LLM report service is called, it should raise exception (mock cache hit guarantees no LLM call)
    mock_report_service = AsyncMock()
    mock_report_service.analyse_one_report.side_effect = RuntimeError("LLM MUST NOT BE CALLED ON CACHE HIT!")

    # Instantiate HoldingsAdviceService
    service = HoldingsAdviceService(
        settings=mock_settings,
        backend_client=mock_backend,
        report_service=mock_report_service,
        history_service=mock_history,
        user_identity_service=mock_user_identity,
        research_service=AsyncMock()
    )

    request = HoldingsAdviceRequest(
        items=[
            HoldingAdviceItem(
                symbol="HPG",
                exchange="HOSE",
                average_cost=25000,
                quantity=1000,
                unrealized_pnl=5000000,
                unrealized_pnl_pct=20.0,
                status="PROFIT"
            )
        ]
    )

    # 2. Execute
    response = await service.generate_advice(request, user_token="test-token")

    # 3. Assertions
    assert response["code"] == 200
    assert response["success"] is True
    assert response["data"]["cached_count"] == 1
    
    advice = response["data"]["advice"][0]
    assert advice["symbol"] == "HPG"
    assert advice["source"] == "cache"
    assert advice["reportId"] == "report-999"
    assert advice["decision"] == "BUY"
    
    # Verify structured reasoning
    skeleton = advice["reasoningSkeleton"]
    assert skeleton["portfolio_fit"] == "VỊ THẾ: Vùng giá hợp lý."
    assert len(skeleton["criteria"]) == 5
    
    # Check that we collected evidence
    assert len(skeleton["evidencePool"]) > 0
    # Price highest/lowest from 7d chart must exist
    metrics = [ev["metric_name"] for ev in skeleton["evidencePool"]]
    assert "Giá cao nhất 7 ngày" in metrics
    assert "Giá thấp nhất 7 ngày" in metrics
