from __future__ import annotations

import json
from analyse.services.holdings_advice_service import HoldingsAdviceService
from analyse.schemas.holdings_advice import HoldingAdviceItem


class MockCacheRow:
    def __init__(self, report_id, decision_label, created_at, report_json):
        self.report_id = report_id
        self.decision_label = decision_label
        self.created_at = created_at
        self.report_json = report_json
        self.total_score = 65.0
        self.risk_score = 49.0
        self.data_confidence = 85.0


def test_holdings_advice_units_and_report_id_population():
    service = HoldingsAdviceService()

    # Define mock item
    item = HoldingAdviceItem(
        symbol="FPT",
        exchange="HOSE",
        average_cost=60000,
        quantity=1000,
        unrealized_pnl=13200000,
        unrealized_pnl_pct=22.0,
        status="PROFIT",
    )

    # 1. Test build from report (LLM generated path)
    mock_report = {
        "code": 200,
        "success": True,
        "data": {
            "report_id": "test-report-llm-123",
            "generated_at": "2026-07-07T13:50:06Z",
            "summary": {
                "system_decision": {
                    "status": "HOLD",
                    "reasons": []
                },
                "scores": {
                    "overall_score": 65.0,
                    "risk_score": 49.0,
                    "data_confidence": 0.85
                },
                "bctc_3q": {
                    "periods": [
                        {
                            "period": "Q1/2026",
                            "year": 2026,
                            "quarter": 1,
                            "revenue": 12480000.0,
                            "profit_after_tax": 1970300.0
                        }
                    ]
                }
            }
        }
    }

    result = service._build_from_report(item, mock_report, source="generated")
    
    assert result.report_id == "test-report-llm-123"
    assert result.reasoning_skeleton is not None
    # Revenue: 12480000 / 1000 = 12480.0
    # Profit: 1970300 / 1000 = 1970.3
    assert "doanh thu 12,480.0 tỷ đồng" in result.reasoning_skeleton.financial_health
    assert "LNST 1,970.3 tỷ đồng" in result.reasoning_skeleton.financial_health

    # 2. Test build from cache row (cached path)
    mock_report_json = json.dumps(mock_report)
    cache_row = MockCacheRow(
        report_id="test-report-cached-999",
        decision_label="HOLD",
        created_at=None,
        report_json=mock_report_json
    )

    result_cached = service._build_from_cache(item, cache_row)
    
    assert result_cached.report_id == "test-report-cached-999"
    assert result_cached.reasoning_skeleton is not None
    assert "doanh thu 12,480.0 tỷ đồng" in result_cached.reasoning_skeleton.financial_health
    assert "LNST 1,970.3 tỷ đồng" in result_cached.reasoning_skeleton.financial_health
