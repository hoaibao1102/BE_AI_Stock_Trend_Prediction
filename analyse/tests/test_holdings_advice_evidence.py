from __future__ import annotations

import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock, MagicMock

from analyse.services.holdings_advice_service import HoldingsAdviceService
from analyse.schemas.holdings_advice import HoldingAdviceItem, HoldingAdviceEvidence
from analyse.schemas.research import ExternalResearchContext, ResearchItem


def test_holding_advice_evidence_validator():
    # News source without url must raise validation error
    with pytest.raises(ValidationError):
        HoldingAdviceEvidence(
            metric_name="Tin hot",
            value="Nội dung tin",
            source="cafef_news",
            source_url=None
        )

    # Price source without url is ok
    ev = HoldingAdviceEvidence(
        metric_name="Giá đóng cửa",
        value=28000,
        source="backend_price",
        source_url=None
    )
    assert ev.metric_name == "Giá đóng cửa"
    assert ev.source_url is None


@pytest.mark.asyncio
async def test_evidence_collection_from_3_sources():
    mock_settings = MagicMock()
    mock_settings.analyse_timezone = "Asia/Ho_Chi_Minh"
    mock_settings.enable_external_research = True

    # Nguồn 1 mock: Stock chart 7d
    mock_backend = AsyncMock()
    mock_backend.get_stock_chart.return_value = {
        "data": [
            {"time": "2026-07-01", "close": 100.0, "volume": 1000},
            {"time": "2026-07-02", "close": 105.0, "volume": 1100}
        ]
    }

    # Nguồn 2: report_json (BCTC & latest_market)
    report_json = {
        "data": {
            "summary": {
                "latest_market": {
                    "pe": 12.5,
                    "pb": 1.8,
                },
                "bctc_3q": {
                    "periods": [
                        {
                            "quarter": 1,
                            "year": 2026,
                            "revenue": 10000000.0,
                            "profit_after_tax": 1500000.0
                        }
                    ]
                }
            }
        }
    }

    # Nguồn 3 mock: External Research (news with score >= 0.4 and age <= 14 days)
    mock_research = AsyncMock()
    mock_research.search.return_value = ExternalResearchContext(
        enabled=True,
        status="success",
        items=[
            ResearchItem(
                source="CafeF",
                type="news",
                title="HPG báo lãi lớn Q1",
                url="https://cafef.vn/hpg-lai-lon.html",
                published_at="2026-07-05T09:00:00Z",
                snippet="Lợi nhuận HPG tăng 40%...",
                relevance_score=0.9
            ),
            # Item with low relevance score (should be filtered out)
            ResearchItem(
                source="Vietstock",
                type="news",
                title="Tin tặc tấn công",
                url="https://vietstock.vn/hack.html",
                published_at="2026-07-06T09:00:00Z",
                snippet="Không liên quan lắm",
                relevance_score=0.1
            ),
            # Item too old (should be filtered out)
            ResearchItem(
                source="Vietstock",
                type="news",
                title="Tin từ năm ngoái",
                url="https://vietstock.vn/old.html",
                published_at="2025-01-01T09:00:00Z",
                snippet="Cũ kỹ",
                relevance_score=0.9
            )
        ]
    )

    service = HoldingsAdviceService(
        settings=mock_settings,
        backend_client=mock_backend,
        report_service=AsyncMock(),
        history_service=AsyncMock(),
        user_identity_service=AsyncMock(),
        research_service=mock_research
    )

    item = HoldingAdviceItem(
        symbol="HPG",
        exchange="HOSE",
        average_cost=25000,
        quantity=1000,
        unrealized_pnl=5000000,
        unrealized_pnl_pct=20.0,
        status="PROFIT"
    )

    # Execute evidence collection
    evidence = await service._collect_evidence(
        symbol="HPG",
        exchange="HOSE",
        item=item,
        report_json=report_json,
        user_token="test-token"
    )

    # Assertions
    sources = [ev.source for ev in evidence]
    metrics = [ev.metric_name for ev in evidence]

    # Verify chart price source
    assert "backend_price" in sources
    assert "Giá cao nhất 7 ngày" in metrics
    assert "Giá thấp nhất 7 ngày" in metrics

    # Verify BCTC/Market source
    assert "history_bctc" in sources
    assert "history_market" in sources
    assert "Doanh thu Q1/2026" in metrics
    assert "P/E" in metrics

    # Verify News source
    assert "cafef_news" in sources
    assert "Tin tức: HPG báo lãi lớn Q1" in metrics

    # Verify low relevance and old news were filtered out
    assert "vietstock_news" not in sources
    assert "Tin tức: Tin tặc tấn công" not in metrics
    assert "Tin tức: Tin từ năm ngoái" not in metrics
