from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from analyse.repositories.portfolio_daily_advice_repository import PortfolioDailyAdviceRepository
from analyse.schemas.holdings_advice import HoldingAdviceItem, HoldingsAdviceRequest
from analyse.services.holdings_advice_service import HoldingsAdviceService
from analyse.services.user_identity_service import CurrentUserIdentity


@pytest.mark.asyncio
async def test_holdings_advice_daily_cache_hit_skips_llm(tmp_path: Path):
    advice_dir = tmp_path / "portfolio_daily_advice"
    repo = PortfolioDailyAdviceRepository(
        MagicMock(
            analyse_timezone="Asia/Ho_Chi_Minh",
            portfolio_daily_advice_dir=str(advice_dir),
        )
    )
    advice_date = repo.advice_date_str()
    cached_advice = {
        "symbol": "HPG",
        "exchange": "HOSE",
        "decision": "HOLD",
        "pnl_signal": "PROFIT_HOLD",
        "source": "generated",
        "reasoning": "Cached advice for today.",
        "reasoningSkeleton": {
            "portfolio_fit": "Vị thế ổn.",
            "financial_health": "Tài chính ổn.",
            "valuation_peer": "Định giá hợp lý.",
            "market_momentum": "Thị trường ổn.",
            "action_plan": "Giữ nguyên.",
            "criteria": [],
            "evidencePool": [],
        },
    }
    repo.save(
        user_id="user-123",
        symbol="HPG",
        advice=cached_advice,
        advice_date=advice_date,
        source="generated",
    )

    mock_report_service = AsyncMock()
    mock_report_service.analyse_one_report.side_effect = RuntimeError("LLM MUST NOT BE CALLED")

    mock_user_identity = AsyncMock()
    mock_user_identity.resolve_current_user.return_value = CurrentUserIdentity(
        mongo_user_id="user-123",
        email="user@test.com",
    )

    service = HoldingsAdviceService(
        settings=MagicMock(
            analyse_timezone="Asia/Ho_Chi_Minh",
            enable_external_research=False,
            portfolio_advice_concurrency=2,
            portfolio_daily_advice_dir=str(advice_dir),
        ),
        backend_client=AsyncMock(),
        report_service=mock_report_service,
        history_service=AsyncMock(),
        user_identity_service=mock_user_identity,
        research_service=AsyncMock(),
        daily_advice_repository=repo,
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
                status="PROFIT",
            )
        ]
    )

    response = await service.generate_advice(request, user_token="test-token")

    assert response["code"] == 200
    assert response["success"] is True
    assert response["data"]["cached_count"] == 1
    assert response["data"]["generated_count"] == 0
    assert response["data"]["advice"][0]["source"] == "cache"
    mock_report_service.analyse_one_report.assert_not_called()

    saved = json.loads(
        (advice_dir / "user-123" / advice_date / "HPG.json").read_text(encoding="utf-8")
    )
    assert saved["symbol"] == "HPG"
    assert saved["advice_date"] == advice_date
