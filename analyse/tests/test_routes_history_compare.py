from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analyse.api import dependencies
from analyse.api.routes import router
from analyse.schemas.report_history import (
    ReportHistoryCompareData,
    ReportHistoryCompareItem,
)
from analyse.services.ai_report_history_service import (
    AiReportHistoryCompareInsufficientDataError,
    AiReportHistoryDisabledError,
    AiReportHistoryNotFoundError,
    AiReportHistoryServiceError,
)
from analyse.services.user_identity_service import CurrentUserIdentity


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _fake_current_user() -> CurrentUserIdentity:
    return CurrentUserIdentity(mongo_user_id="user-1", email="user@example.com")


def _fake_compare_data() -> ReportHistoryCompareData:
    return ReportHistoryCompareData(
        symbol="FPT",
        exchange="HOSE",
        baseline=ReportHistoryCompareItem(
            id="baseline-id",
            report_id="FPT_HOSE_1",
            created_at="2026-06-01T00:00:00+00:00",
            provider="gemini",
            model="gemini-pro",
            total_score=70.0,
            risk_score=30.0,
            data_confidence=80.0,
            decision_label="Theo dõi",
        ),
        latest=ReportHistoryCompareItem(
            id="latest-id",
            report_id="FPT_HOSE_2",
            created_at="2026-07-01T00:00:00+00:00",
            provider="gemini",
            model="gemini-pro",
            total_score=80.0,
            risk_score=25.0,
            data_confidence=85.0,
            decision_label="Mua",
        ),
        score_delta=10.0,
        risk_delta=-5.0,
        confidence_delta=5.0,
        trend="IMPROVING",
        trend_label="Cải thiện",
        recommendation="BUY",
        recommendation_label="Mua",
        reasons=["Điểm tổng hợp thay đổi +10.00 điểm so với báo cáo trước đó."],
    )


@pytest.fixture
def client(monkeypatch):
    app = _build_app()

    identity_service = AsyncMock()
    identity_service.resolve_current_user.return_value = _fake_current_user()

    history_service = AsyncMock()

    app.dependency_overrides[dependencies.get_user_identity_service] = lambda: identity_service
    app.dependency_overrides[dependencies.get_ai_report_history_service] = lambda: history_service

    test_client = TestClient(app)
    test_client.history_service = history_service  # type: ignore[attr-defined]
    return test_client


def test_compare_endpoint_success_default_latest_two(client):
    client.history_service.compare_history.return_value = _fake_compare_data()

    response = client.get(
        "/api/ai-reports/history/compare",
        params={"symbol": "FPT"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["trend"] == "IMPROVING"
    assert body["data"]["recommendation"] == "BUY"
    assert body["data"]["is_reference_only"] is True

    call_kwargs = client.history_service.compare_history.await_args.kwargs
    assert call_kwargs["symbol"] == "FPT"
    assert call_kwargs["baseline_history_id"] is None
    assert call_kwargs["latest_history_id"] is None


def test_compare_endpoint_with_explicit_ids(client):
    client.history_service.compare_history.return_value = _fake_compare_data()

    response = client.get(
        "/api/ai-reports/history/compare",
        params={"symbol": "FPT", "baselineHistoryId": "a", "latestHistoryId": "b"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    call_kwargs = client.history_service.compare_history.await_args.kwargs
    assert call_kwargs["baseline_history_id"] == "a"
    assert call_kwargs["latest_history_id"] == "b"


def test_compare_endpoint_rejects_single_id_only(client):
    response = client.get(
        "/api/ai-reports/history/compare",
        params={"symbol": "FPT", "baselineHistoryId": "a"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "HISTORY_COMPARE_INVALID_PARAMS"
    client.history_service.compare_history.assert_not_called()


def test_compare_endpoint_returns_422_when_insufficient_data(client):
    client.history_service.compare_history.side_effect = AiReportHistoryCompareInsufficientDataError(
        "Cần ít nhất 2 báo cáo trong lịch sử cùng mã và sàn để so sánh."
    )

    response = client.get(
        "/api/ai-reports/history/compare",
        params={"symbol": "FPT"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "HISTORY_COMPARE_INSUFFICIENT_DATA"


def test_compare_endpoint_returns_503_when_disabled(client):
    client.history_service.compare_history.side_effect = AiReportHistoryDisabledError(
        "Tính năng lịch sử báo cáo AI chưa được bật."
    )

    response = client.get(
        "/api/ai-reports/history/compare",
        params={"symbol": "FPT"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "HISTORY_DISABLED"


def test_compare_endpoint_returns_404_when_ids_not_found(client):
    client.history_service.compare_history.side_effect = AiReportHistoryNotFoundError(
        "Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại."
    )

    response = client.get(
        "/api/ai-reports/history/compare",
        params={"symbol": "FPT", "baselineHistoryId": "a", "latestHistoryId": "b"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["type"] == "HISTORY_NOT_FOUND"


def test_compare_endpoint_returns_422_on_symbol_mismatch(client):
    client.history_service.compare_history.side_effect = AiReportHistoryServiceError(
        "Hai báo cáo được chọn không cùng mã cổ phiếu.", code="HISTORY_COMPARE_SYMBOL_MISMATCH"
    )

    response = client.get(
        "/api/ai-reports/history/compare",
        params={"symbol": "FPT", "baselineHistoryId": "a", "latestHistoryId": "b"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "HISTORY_COMPARE_SYMBOL_MISMATCH"


def test_compare_endpoint_returns_401_when_token_unauthorized(client):
    from analyse.services.user_identity_service import UserIdentityUnauthorizedError

    client.history_service = client.history_service  # keep for readability
    identity_mock = client.app.dependency_overrides[dependencies.get_user_identity_service]()
    identity_mock.resolve_current_user.side_effect = UserIdentityUnauthorizedError(
        "Phiên đăng nhập đã hết hạn hoặc token không hợp lệ."
    )

    response = client.get(
        "/api/ai-reports/history/compare",
        params={"symbol": "FPT"},
        headers={"Authorization": "Bearer expired-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "AUTH_INVALID"
    client.history_service.compare_history.assert_not_called()


def test_compare_endpoint_route_order_not_shadowed_by_history_id_route(client):
    """Guards against a routing regression: '/history/compare' must never be
    captured by the '/history/{history_id}' path-param route."""
    client.history_service.compare_history.return_value = _fake_compare_data()

    response = client.get(
        "/api/ai-reports/history/compare",
        params={"symbol": "FPT"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    # If routing were shadowed, get_history_detail would have been called
    # with history_id="compare" instead of compare_history.
    client.history_service.get_history_detail.assert_not_called()
    client.history_service.compare_history.assert_awaited_once()