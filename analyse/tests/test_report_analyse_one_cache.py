from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from analyse.services.report_service import ReportService
from analyse.schemas.report import AnalyseOneReportRequest
from analyse.services.user_identity_service import CurrentUserIdentity


class FakeReportHistoryListItem:
    def __init__(self, id, symbol, exchange, created_at):
        self.id = id
        self.symbol = symbol
        self.exchange = exchange
        self.created_at = created_at


class FakeReportHistoryDetailData:
    def __init__(self, id, report_id, report_json):
        self.id = id
        self.report_id = report_id
        self.report_json = report_json


@pytest.mark.asyncio
async def test_analyse_one_report_cache_hit():
    # 1. Setup mock dependencies
    mock_settings = MagicMock()
    mock_settings.enable_ai_report_history = True
    mock_settings.default_llm_provider = "openai"

    mock_backend = AsyncMock()
    mock_user_identity = AsyncMock()
    mock_user_identity.resolve_current_user.return_value = CurrentUserIdentity(
        mongo_user_id="user-123", email="user@test.com"
    )

    mock_history = AsyncMock()
    
    # Mock history list: return 1 cache item created recently
    cache_item = FakeReportHistoryListItem("hist-1", "HPG", "HOSE", datetime.now(timezone.utc))
    list_data = MagicMock()
    list_data.total = 1
    list_data.items = [cache_item]
    mock_history.list_history.return_value = list_data

    # Mock detailed cached report json
    mock_cached_report = {
        "code": 200,
        "success": True,
        "data": {
            "report_id": "report-cached-999",
            "symbol": "HPG",
            "scope_exchange": "HOSE",
            "summary": {
                "system_decision": {"status": "BUY", "reasons": ["Lý do cache"]}
            }
        }
    }
    detail_data = FakeReportHistoryDetailData("hist-1", "report-cached-999", mock_cached_report)
    mock_history.get_history_detail.return_value = detail_data

    # Instantiate ReportService
    service = ReportService(
        settings=mock_settings,
        backend_client=mock_backend,
        research_service=AsyncMock(),
        user_identity_service=mock_user_identity,
        history_service=mock_history
    )

    # Mock other backend dependencies that would be called if cache MISS
    service._history_storage_available = MagicMock(return_value=True)
    
    # If the service tries to fetch from watchlist or backend client, we fail the test (verifying cache reuse bypassed them)
    service.backend_client.get_watchlists.side_effect = RuntimeError("Watchlist fetched! Cache miss!")

    payload = AnalyseOneReportRequest(
        symbol="HPG",
        scopeExchange="HOSE",
        forceRefresh=False
    )

    # 2. Execute
    response = await service.analyse_one_report(payload, user_token="test-token")

    # 3. Assertions
    assert response["code"] == 200
    assert response["success"] is True
    assert response["data"]["report_id"] == "report-cached-999"
    assert response["data"]["summary"]["system_decision"]["status"] == "BUY"
