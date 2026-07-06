from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from analyse.services.ai_report_history_service import (
    AiReportHistoryCompareInsufficientDataError,
    AiReportHistoryService,
    AiReportHistoryServiceError,
)
from analyse.services.user_identity_service import CurrentUserIdentity


def _row(
    *,
    row_id: str = "row-id",
    report_id: str = "report-id",
    symbol: str = "FPT",
    exchange: str = "HOSE",
    provider: str = "gemini",
    model: str = "gemini-pro",
    total_score: float | None = 70.0,
    risk_score: float | None = 30.0,
    data_confidence: float | None = 80.0,
    decision_label: str | None = "Theo dõi",
    created_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id,
        report_id=report_id,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        model=model,
        total_score=total_score,
        risk_score=risk_score,
        data_confidence=data_confidence,
        decision_label=decision_label,
        created_at=created_at or datetime.now(timezone.utc),
    )


def _current_user(mongo_user_id: str = "user-1") -> CurrentUserIdentity:
    return CurrentUserIdentity(mongo_user_id=mongo_user_id, email="user@example.com")


def _service(repository: MagicMock, *, enable_history: bool = True, db_url: str = "mssql://x") -> AiReportHistoryService:
    settings = SimpleNamespace(
        enable_ai_report_history=enable_history,
        ai_report_db_url=db_url,
        report_compare_score_delta_threshold=3.0,
        report_compare_risk_delta_threshold=5.0,
    )
    repository.storage_name = "sqlserver"
    return AiReportHistoryService(settings=settings, repository=repository)


@pytest.mark.asyncio
async def test_compare_history_uses_latest_two_when_no_ids():
    now = datetime.now(timezone.utc)
    latest = _row(row_id="latest", total_score=80.0, risk_score=25.0, created_at=now)
    baseline = _row(row_id="baseline", total_score=70.0, risk_score=30.0, created_at=now - timedelta(days=7))

    repository = MagicMock()
    repository.list_by_user.side_effect = [[latest, baseline]]

    service = _service(repository)
    result = await service.compare_history(current_user=_current_user(), symbol="fpt", exchange="HOSE")

    assert result.baseline.id == "baseline"
    assert result.latest.id == "latest"
    assert result.score_delta == 10.0
    assert result.risk_delta == -5.0
    assert result.trend == "IMPROVING"
    assert result.recommendation == "BUY"
    assert result.is_reference_only is True
    # only one repository call (limit=2), no probe needed since exchange was given
    assert repository.list_by_user.call_count == 1


@pytest.mark.asyncio
async def test_compare_history_resolves_exchange_when_omitted():
    now = datetime.now(timezone.utc)
    latest = _row(row_id="latest", exchange="HNX", created_at=now)
    baseline = _row(row_id="baseline", exchange="HNX", created_at=now - timedelta(days=3))

    repository = MagicMock()
    repository.list_by_user.side_effect = [[latest], [latest, baseline]]

    service = _service(repository)
    result = await service.compare_history(current_user=_current_user(), symbol="FPT", exchange=None)

    assert result.exchange == "HNX"
    assert repository.list_by_user.call_count == 2  # probe call + actual pair call


@pytest.mark.asyncio
async def test_compare_history_raises_insufficient_data_when_only_one_report():
    repository = MagicMock()
    repository.list_by_user.side_effect = [[_row()]]

    service = _service(repository)
    with pytest.raises(AiReportHistoryCompareInsufficientDataError):
        await service.compare_history(current_user=_current_user(), symbol="FPT", exchange="HOSE")


@pytest.mark.asyncio
async def test_compare_history_raises_insufficient_data_when_no_report_for_probe():
    repository = MagicMock()
    repository.list_by_user.side_effect = [[]]

    service = _service(repository)
    with pytest.raises(AiReportHistoryCompareInsufficientDataError):
        await service.compare_history(current_user=_current_user(), symbol="FPT", exchange=None)


@pytest.mark.asyncio
async def test_compare_history_explicit_ids_symbol_mismatch_raises():
    row_a = _row(row_id="a", symbol="FPT")
    row_b = _row(row_id="b", symbol="VNM")

    repository = MagicMock()
    repository.get_by_id_for_user.side_effect = [row_a, row_b]

    service = _service(repository)
    with pytest.raises(AiReportHistoryServiceError) as exc_info:
        await service.compare_history(
            current_user=_current_user(),
            symbol="FPT",
            baseline_history_id="a",
            latest_history_id="b",
        )
    assert exc_info.value.code == "HISTORY_COMPARE_SYMBOL_MISMATCH"


@pytest.mark.asyncio
async def test_compare_history_explicit_ids_exchange_mismatch_raises():
    row_a = _row(row_id="a", exchange="HOSE")
    row_b = _row(row_id="b", exchange="HNX")

    repository = MagicMock()
    repository.get_by_id_for_user.side_effect = [row_a, row_b]

    service = _service(repository)
    with pytest.raises(AiReportHistoryServiceError) as exc_info:
        await service.compare_history(
            current_user=_current_user(),
            symbol="FPT",
            exchange="HOSE",
            baseline_history_id="a",
            latest_history_id="b",
        )
    assert exc_info.value.code == "HISTORY_COMPARE_EXCHANGE_MISMATCH"


@pytest.mark.asyncio
async def test_compare_history_explicit_ids_are_reordered_by_created_at():
    now = datetime.now(timezone.utc)
    # Caller passes the newer one as "baseline" by mistake; service must reorder.
    newer_row = _row(row_id="newer", total_score=90.0, created_at=now)
    older_row = _row(row_id="older", total_score=60.0, created_at=now - timedelta(days=10))

    repository = MagicMock()
    repository.get_by_id_for_user.side_effect = [newer_row, older_row]

    service = _service(repository)
    result = await service.compare_history(
        current_user=_current_user(),
        symbol="FPT",
        baseline_history_id="newer",
        latest_history_id="older",
    )
    assert result.baseline.id == "older"
    assert result.latest.id == "newer"
    assert result.score_delta == 30.0


@pytest.mark.parametrize(
    "baseline_score,latest_score,expected_trend,expected_recommendation",
    [
        (70.0, 80.0, "IMPROVING", "BUY"),
        (70.0, 60.0, "WORSENING", "SELL"),
        (70.0, 71.0, "SIDEWAYS", "HOLD"),
        (70.0, 69.0, "SIDEWAYS", "HOLD"),
    ],
)
@pytest.mark.asyncio
async def test_compare_history_trend_and_recommendation_thresholds(
    baseline_score, latest_score, expected_trend, expected_recommendation
):
    now = datetime.now(timezone.utc)
    latest = _row(row_id="latest", total_score=latest_score, risk_score=30.0, created_at=now)
    baseline = _row(row_id="baseline", total_score=baseline_score, risk_score=30.0, created_at=now - timedelta(days=5))

    repository = MagicMock()
    repository.list_by_user.side_effect = [[latest, baseline]]

    service = _service(repository)
    result = await service.compare_history(current_user=_current_user(), symbol="FPT", exchange="HOSE")

    assert result.trend == expected_trend
    assert result.recommendation == expected_recommendation


@pytest.mark.asyncio
async def test_compare_history_improving_but_risk_rising_suggests_watch_not_buy():
    now = datetime.now(timezone.utc)
    latest = _row(row_id="latest", total_score=90.0, risk_score=50.0, created_at=now)
    baseline = _row(row_id="baseline", total_score=70.0, risk_score=30.0, created_at=now - timedelta(days=5))

    repository = MagicMock()
    repository.list_by_user.side_effect = [[latest, baseline]]

    service = _service(repository)
    result = await service.compare_history(current_user=_current_user(), symbol="FPT", exchange="HOSE")

    assert result.trend == "IMPROVING"
    assert result.recommendation == "WATCH"


@pytest.mark.asyncio
async def test_compare_history_never_triggers_llm_or_crawler_calls():
    """Regression guard: compare_history must only touch the repository, never
    re-run analysis (LLM) or research/crawler services."""
    now = datetime.now(timezone.utc)
    latest = _row(row_id="latest", created_at=now)
    baseline = _row(row_id="baseline", created_at=now - timedelta(days=1))

    repository = MagicMock()
    repository.list_by_user.side_effect = [[latest, baseline]]

    service = _service(repository)
    # AiReportHistoryService only ever depends on settings + repository;
    # asserting no extra attributes like report_service/research_service exist
    # is a cheap way to guard against accidental re-analysis wiring.
    assert not hasattr(service, "report_service")
    assert not hasattr(service, "research_service")

    await service.compare_history(current_user=_current_user(), symbol="FPT", exchange="HOSE")
    repository.create.assert_not_called()