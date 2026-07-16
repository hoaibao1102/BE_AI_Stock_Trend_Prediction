from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from analyse.api.dependencies import get_ai_report_history_service, get_user_identity_service
from analyse.app import create_app
from analyse.config.settings import Settings
from analyse.db.models import AiReportHistory
from analyse.repositories.ai_report_history_repository import AiReportHistoryRepository, AiReportHistoryRepositoryError
from analyse.schemas.report import AnalyseOneReportRequest
from analyse.schemas.report_history import ReportHistoryFilters
from analyse.services.ai_report_history_service import (
    AiReportHistoryDisabledError,
    AiReportHistoryNotFoundError,
    AiReportHistoryService,
    AiReportHistoryUnavailableError,
)
from analyse.services.user_identity_service import CurrentUserIdentity, UserIdentityMalformedError, UserIdentityService


class FakeBackendClientForIdentity:
    def __init__(self, payload):
        self.payload = payload
        self.tokens = []

    async def get_current_user(self, *, token: str):
        self.tokens.append(token)
        return self.payload


class FakeHistoryRepository:
    def __init__(self):
        self.created = []

    def create(self, values):
        self.created.append(values)
        return SimpleNamespace(**values, created_at=datetime(2026, 6, 23, 1, 2, 3))


class FailingHistoryRepository(FakeHistoryRepository):
    def create(self, values):
        raise AiReportHistoryRepositoryError("db unavailable")


def _sample_report_response():
    return {
        "code": 200,
        "message": "Tạo dữ liệu report thành công",
        "data": {
            "report_id": "FPT_HOSE_20260623_100000",
            "generated_at": "2026-06-23T10:00:00+07:00",
            "symbol": "FPT",
            "company": "Cong ty Co phan FPT",
            "scope_exchange": "HOSE",
            "provider": {"name": "openai", "model": "gpt-4.1-mini", "status": "success", "latency_ms": 12},
            "data_sources": [],
            "summary": {
                "scores": {"overall_score": 65, "risk_score": 38, "score_confidence": 0.7},
                "system_decision": {"status": "Theo dõi"},
                "report_presentation": {"summary_bar": {"data_confidence": 70}},
            },
            "warnings": [],
        },
    }


def test_user_identity_service_normalizes_backend_current_user_response():
    backend_client = FakeBackendClientForIdentity(
        {
            "success": True,
            "data": {
                "id": "65fabc",
                "email": "user@example.com",
                "full_name": "Nguyen Van A",
                "role": "USER",
                "plan": "FREE",
            },
        }
    )
    service = UserIdentityService(backend_client)  # type: ignore[arg-type]

    identity = asyncio.run(service.resolve_current_user("request-token"))

    assert identity.mongo_user_id == "65fabc"
    assert identity.email == "user@example.com"
    assert backend_client.tokens == ["request-token"]


def test_user_identity_service_rejects_missing_data_id():
    service = UserIdentityService(FakeBackendClientForIdentity({"success": True, "data": {"email": "x@y.test"}}))  # type: ignore[arg-type]

    with pytest.raises(UserIdentityMalformedError):
        service.normalize_current_user({"success": True, "data": {"email": "x@y.test"}})


def test_history_service_save_report_stores_user_id_full_json_and_history_id():
    repo = FakeHistoryRepository()
    service = AiReportHistoryService(Settings(ENABLE_AI_REPORT_HISTORY=True, AI_REPORT_DB_URL="mssql+pyodbc://user:password@localhost/db"), repo)  # type: ignore[arg-type]
    request = AnalyseOneReportRequest.model_validate({"provider": "openai", "symbol": "FPT", "scopeExchange": "HOSE"})
    response = _sample_report_response()

    history_id = asyncio.run(
        service.save_report_after_analysis(
            current_user=CurrentUserIdentity(mongo_user_id="mongo-user-1", email="user@example.com"),
            payload=request,
            report_response=response,
            matched_watchlist_item={"watchlist_id": "watch-1", "stock_id": "stock-1"},
        )
    )

    assert history_id
    assert response["data"]["history_id"] == history_id
    created = repo.created[0]
    assert created["mongo_user_id"] == "mongo-user-1"
    assert created["mongo_watchlist_id"] == "watch-1"
    assert created["mongo_stock_id"] == "stock-1"
    assert created["total_score"] == 65
    assert created["risk_score"] == 38
    assert created["data_confidence"] == 70
    assert '"history_id"' in created["report_json"]
    assert "request-token" not in created["report_json"]


def test_history_service_non_blocking_save_failure_adds_warning():
    service = AiReportHistoryService(
        Settings(
            ENABLE_AI_REPORT_HISTORY=True,
            AI_REPORT_DB_URL="mssql+pyodbc://user:password@localhost/db",
            AI_REPORT_HISTORY_SAVE_FAILURE_POLICY="non_blocking",
        ),
        FailingHistoryRepository(),  # type: ignore[arg-type]
    )
    request = AnalyseOneReportRequest.model_validate({"provider": "openai", "symbol": "FPT", "scopeExchange": "HOSE"})
    response = _sample_report_response()

    history_id = asyncio.run(
        service.save_report_after_analysis(
            current_user=CurrentUserIdentity(mongo_user_id="mongo-user-1"),
            payload=request,
            report_response=response,
            matched_watchlist_item=None,
        )
    )

    assert history_id is None
    assert "Báo cáo đã phân tích thành công nhưng chưa lưu được lịch sử." in response["data"]["warnings"]
    assert "history_id" not in response["data"]


def test_history_service_disabled_save_is_noop():
    service = AiReportHistoryService(Settings(ENABLE_AI_REPORT_HISTORY=False), FakeHistoryRepository())  # type: ignore[arg-type]
    request = AnalyseOneReportRequest.model_validate({"provider": "openai", "symbol": "FPT", "scopeExchange": "HOSE"})
    response = _sample_report_response()

    history_id = asyncio.run(
        service.save_report_after_analysis(
            current_user=CurrentUserIdentity(mongo_user_id="mongo-user-1"),
            payload=request,
            report_response=response,
            matched_watchlist_item=None,
        )
    )

    assert history_id is None
    assert "history_id" not in response["data"]


def test_file_history_empty_list_returns_paginated_empty_data(tmp_path):
    settings = Settings(_env_file=None, AI_REPORT_HISTORY_STORAGE="file", AI_REPORT_HISTORY_DIR=str(tmp_path / "ai_reports"))
    service = AiReportHistoryService(settings)

    data = asyncio.run(
        service.list_history(
            current_user=CurrentUserIdentity(mongo_user_id="mongo-user-1"),
            filters=ReportHistoryFilters(page=1, limit=20),
        )
    )

    assert data.items == []
    assert data.page == 1
    assert data.limit == 20
    assert data.total == 0
    assert data.total_pages == 1


def test_file_history_save_list_filter_and_detail(tmp_path):
    settings = Settings(_env_file=None, AI_REPORT_HISTORY_STORAGE="file", AI_REPORT_HISTORY_DIR=str(tmp_path / "ai_reports"))
    service = AiReportHistoryService(settings)
    user = CurrentUserIdentity(mongo_user_id="mongo-user-1", email="user@example.com")
    request = AnalyseOneReportRequest.model_validate({"provider": "openai", "symbol": "FPT", "scopeExchange": "HOSE"})
    response = _sample_report_response()

    history_id = asyncio.run(
        service.save_report_after_analysis(
            current_user=user,
            payload=request,
            report_response=response,
            matched_watchlist_item={"watchlist_id": "watch-1", "stock_id": "stock-1"},
        )
    )
    listed = asyncio.run(service.list_history(current_user=user, filters=ReportHistoryFilters(symbol="FPT", exchange="HOSE", page=1, limit=20)))
    detail = asyncio.run(service.get_history_detail(current_user=user, history_id=history_id or ""))

    assert history_id
    assert response["data"]["history_id"] == history_id
    assert listed.total == 1
    assert listed.total_pages == 1
    assert listed.items[0].report_id == "FPT_HOSE_20260623_100000"
    assert listed.items[0].company_name == "Cong ty Co phan FPT"
    assert listed.items[0].score == 65
    assert detail.report_json["data"]["report_id"] == "FPT_HOSE_20260623_100000"


def test_file_history_pagination_and_filters(tmp_path):
    settings = Settings(_env_file=None, AI_REPORT_HISTORY_STORAGE="file", AI_REPORT_HISTORY_DIR=str(tmp_path / "ai_reports"))
    service = AiReportHistoryService(settings)
    user = CurrentUserIdentity(mongo_user_id="mongo-user-1")

    for idx, symbol in enumerate(["FPT", "HPG", "VCB"]):
        response = _sample_report_response()
        response["data"]["report_id"] = f"{symbol}_HOSE_20260623_10000{idx}"
        response["data"]["symbol"] = symbol
        response["data"]["generated_at"] = f"2026-06-23T10:00:0{idx}+07:00"
        request = AnalyseOneReportRequest.model_validate({"provider": "openai", "symbol": symbol, "scopeExchange": "HOSE"})
        asyncio.run(service.save_report_after_analysis(current_user=user, payload=request, report_response=response, matched_watchlist_item=None))

    page = asyncio.run(service.list_history(current_user=user, filters=ReportHistoryFilters(page=2, limit=2)))
    filtered = asyncio.run(service.list_history(current_user=user, filters=ReportHistoryFilters(symbol="HPG", page=1, limit=20)))

    assert page.total == 3
    assert page.total_pages == 2
    assert len(page.items) == 1
    assert filtered.total == 1
    assert filtered.items[0].symbol == "HPG"


def test_file_history_malformed_index_raises_storage_error(tmp_path):
    storage_dir = tmp_path / "ai_reports"
    storage_dir.mkdir()
    (storage_dir / "index.json").write_text("{bad json", encoding="utf-8")
    settings = Settings(_env_file=None, AI_REPORT_HISTORY_STORAGE="file", AI_REPORT_HISTORY_DIR=str(storage_dir))
    service = AiReportHistoryService(settings)

    with pytest.raises(AiReportHistoryUnavailableError) as exc_info:
        asyncio.run(
            service.list_history(
                current_user=CurrentUserIdentity(mongo_user_id="mongo-user-1"),
                filters=ReportHistoryFilters(page=1, limit=20),
            )
        )

    assert exc_info.value.code == "AI_REPORT_HISTORY_STORAGE_ERROR"


def test_history_repository_wraps_unexpected_storage_errors_safely(monkeypatch):
    secret_db_url = "mssql+pyodbc://user:sql-secret@localhost/db"

    def broken_session(settings=None):
        raise RuntimeError(f"connection failed for {secret_db_url}")

    monkeypatch.setattr("analyse.repositories.ai_report_history_repository.get_db_session", broken_session)
    repo = AiReportHistoryRepository(Settings(ENABLE_AI_REPORT_HISTORY=True, AI_REPORT_DB_URL=secret_db_url))

    with pytest.raises(AiReportHistoryRepositoryError) as exc_info:
        repo.list_by_user("mongo-user-1")

    message = str(exc_info.value)
    assert "Không đọc được lịch sử báo cáo AI." in message
    assert "sql-secret" not in message
    assert secret_db_url not in message


def test_history_model_created_at_uses_utc_default():
    default_clause = str(AiReportHistory.__table__.c.created_at.server_default.arg).upper()

    assert "CURRENT_TIMESTAMP" in default_clause


class FakeIdentityDependency:
    async def resolve_current_user(self, token: str):
        assert token == "route-token"
        return CurrentUserIdentity(mongo_user_id="mongo-user-1", email="user@example.com")


class FakeRouteHistoryService:
    def __init__(self):
        self.current_user_ids = []

    async def list_history(self, *, current_user, filters: ReportHistoryFilters):
        self.current_user_ids.append(current_user.mongo_user_id)
        return SimpleNamespace(
            model_dump=lambda: {
                "items": [
                    {
                        "id": "history-1",
                        "report_id": "FPT_HOSE_20260623_100000",
                        "symbol": "FPT",
                        "exchange": "HOSE",
                        "company": "FPT",
                        "provider": "openai",
                        "model": "gpt-4.1-mini",
                        "total_score": 65,
                        "risk_score": 38,
                        "data_confidence": 70,
                        "decision_label": "Theo dõi",
                        "created_at": "2026-06-23T00:00:00",
                    }
                ],
                "page": filters.page,
                "limit": filters.limit,
                "total": 1,
            }
        )

    async def get_history_detail(self, *, current_user, history_id: str):
        self.current_user_ids.append(current_user.mongo_user_id)
        return SimpleNamespace(model_dump=lambda: {"id": history_id, "report_id": "RID", "report_json": _sample_report_response()})

    async def delete_history(self, *, current_user, history_id: str):
        self.current_user_ids.append(current_user.mongo_user_id)
        return True


class UnavailableRouteHistoryService(FakeRouteHistoryService):
    secret_db_url = "mssql+pyodbc://user:sql-secret@localhost/db"

    async def list_history(self, *, current_user, filters: ReportHistoryFilters):
        raise AiReportHistoryUnavailableError(f"SQL unavailable for {self.secret_db_url}")

    async def get_history_detail(self, *, current_user, history_id: str):
        raise AiReportHistoryUnavailableError(f"SQL unavailable for {self.secret_db_url}")

    async def delete_history(self, *, current_user, history_id: str):
        raise AiReportHistoryUnavailableError(f"SQL unavailable for {self.secret_db_url}")


class DisabledRouteHistoryService(FakeRouteHistoryService):
    async def list_history(self, *, current_user, filters: ReportHistoryFilters):
        raise AiReportHistoryDisabledError("disabled")

    async def get_history_detail(self, *, current_user, history_id: str):
        raise AiReportHistoryDisabledError("disabled")

    async def delete_history(self, *, current_user, history_id: str):
        raise AiReportHistoryDisabledError("disabled")


def test_history_routes_resolve_user_and_delegate_with_user_filter():
    app = create_app()
    fake_history = FakeRouteHistoryService()
    app.dependency_overrides[get_user_identity_service] = lambda: FakeIdentityDependency()
    app.dependency_overrides[get_ai_report_history_service] = lambda: fake_history
    client = TestClient(app)

    list_response = client.get("/api/ai-reports/history?symbol=FPT", headers={"Authorization": "Bearer route-token"})
    detail_response = client.get("/api/ai-reports/history/history-1", headers={"Authorization": "Bearer route-token"})
    delete_response = client.delete("/api/ai-reports/history/history-1", headers={"Authorization": "Bearer route-token"})

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"][0]["symbol"] == "FPT"
    assert detail_response.status_code == 200
    assert delete_response.status_code == 200
    assert fake_history.current_user_ids == ["mongo-user-1", "mongo-user-1", "mongo-user-1"]


def test_history_route_file_fallback_returns_200_empty_when_sql_missing(tmp_path):
    app = create_app()
    settings = Settings(_env_file=None, AI_REPORT_HISTORY_STORAGE="file", AI_REPORT_HISTORY_DIR=str(tmp_path / "ai_reports"))
    app.dependency_overrides[get_user_identity_service] = lambda: FakeIdentityDependency()
    app.dependency_overrides[get_ai_report_history_service] = lambda: AiReportHistoryService(settings)
    client = TestClient(app)

    response = client.get("/api/ai-reports/history?page=1&limit=20", headers={"Authorization": "Bearer route-token"})

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Không có báo cáo AI nào trong lịch sử."
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0
    assert body["data"]["total_pages"] == 1


def test_history_route_file_storage_malformed_returns_structured_500(tmp_path):
    storage_dir = tmp_path / "ai_reports"
    storage_dir.mkdir()
    (storage_dir / "index.json").write_text("{bad json", encoding="utf-8")
    app = create_app()
    settings = Settings(_env_file=None, AI_REPORT_HISTORY_STORAGE="file", AI_REPORT_HISTORY_DIR=str(storage_dir))
    app.dependency_overrides[get_user_identity_service] = lambda: FakeIdentityDependency()
    app.dependency_overrides[get_ai_report_history_service] = lambda: AiReportHistoryService(settings)
    client = TestClient(app)

    response = client.get("/api/ai-reports/history?page=1&limit=20", headers={"Authorization": "Bearer route-token"})

    assert response.status_code == 500
    assert response.json()["error"]["type"] == "AI_REPORT_HISTORY_STORAGE_ERROR"


def test_history_route_disabled_returns_clean_503():
    app = create_app()
    app.dependency_overrides[get_user_identity_service] = lambda: FakeIdentityDependency()
    app.dependency_overrides[get_ai_report_history_service] = lambda: DisabledRouteHistoryService()
    client = TestClient(app)

    response = client.get("/api/ai-reports/history", headers={"Authorization": "Bearer route-token"})

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "HISTORY_DISABLED"


def test_history_detail_and_delete_disabled_return_clean_503():
    app = create_app()
    app.dependency_overrides[get_user_identity_service] = lambda: FakeIdentityDependency()
    app.dependency_overrides[get_ai_report_history_service] = lambda: DisabledRouteHistoryService()
    client = TestClient(app)

    detail_response = client.get("/api/ai-reports/history/history-1", headers={"Authorization": "Bearer route-token"})
    delete_response = client.delete("/api/ai-reports/history/history-1", headers={"Authorization": "Bearer route-token"})

    assert detail_response.status_code == 503
    assert detail_response.json()["error"]["type"] == "HISTORY_DISABLED"
    assert delete_response.status_code == 503
    assert delete_response.json()["error"]["type"] == "HISTORY_DISABLED"


def test_history_routes_unavailable_return_safe_503_without_db_secret():
    app = create_app()
    app.dependency_overrides[get_user_identity_service] = lambda: FakeIdentityDependency()
    app.dependency_overrides[get_ai_report_history_service] = lambda: UnavailableRouteHistoryService()
    client = TestClient(app)

    responses = [
        client.get("/api/ai-reports/history", headers={"Authorization": "Bearer route-token"}),
        client.get("/api/ai-reports/history/history-1", headers={"Authorization": "Bearer route-token"}),
        client.delete("/api/ai-reports/history/history-1", headers={"Authorization": "Bearer route-token"}),
    ]

    for response in responses:
        body = response.json()
        text = str(body)
        assert response.status_code == 503
        assert body["error"]["type"] == "HISTORY_UNAVAILABLE"
        assert "sql-secret" not in text
        assert UnavailableRouteHistoryService.secret_db_url not in text


def test_history_detail_and_delete_not_found_preserve_404():
    class NotFoundRouteHistoryService(FakeRouteHistoryService):
        async def get_history_detail(self, *, current_user, history_id: str):
            raise AiReportHistoryNotFoundError("not found")

        async def delete_history(self, *, current_user, history_id: str):
            raise AiReportHistoryNotFoundError("not found")

    app = create_app()
    app.dependency_overrides[get_user_identity_service] = lambda: FakeIdentityDependency()
    app.dependency_overrides[get_ai_report_history_service] = lambda: NotFoundRouteHistoryService()
    client = TestClient(app)

    detail_response = client.get("/api/ai-reports/history/missing", headers={"Authorization": "Bearer route-token"})
    delete_response = client.delete("/api/ai-reports/history/missing", headers={"Authorization": "Bearer route-token"})

    assert detail_response.status_code == 404
    assert detail_response.json()["error"]["type"] == "HISTORY_NOT_FOUND"
    assert delete_response.status_code == 404
    assert delete_response.json()["error"]["type"] == "HISTORY_NOT_FOUND"
