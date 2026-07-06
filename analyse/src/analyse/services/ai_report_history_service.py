from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import math
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from analyse.config.settings import Settings, get_settings
from analyse.db.models import AiReportHistory
from analyse.db.session import HistoryStorageNotConfiguredError
from analyse.repositories.ai_report_history_repository import (
    AiReportHistoryFilters,
    AiReportHistoryRepository,
    AiReportHistoryRepositoryError,
    create_ai_report_history_repository,
)
from analyse.schemas.report import AnalyseOneReportRequest
from analyse.schemas.report_history import ReportHistoryDetailData, ReportHistoryFilters, ReportHistoryListData, ReportHistoryListItem, ReportHistoryCompareData,ReportHistoryCompareItem
from analyse.services.user_identity_service import CurrentUserIdentity
from analyse.utils.symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)


class AiReportHistoryServiceError(RuntimeError):
    """Base service error for report history."""

    code = "HISTORY_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or self.code


class AiReportHistoryDisabledError(AiReportHistoryServiceError):
    """History feature is disabled or not configured."""

    code = "HISTORY_DISABLED"


class AiReportHistoryUnavailableError(AiReportHistoryServiceError):
    """History storage could not be reached."""

    code = "HISTORY_UNAVAILABLE"


class AiReportHistoryNotFoundError(AiReportHistoryServiceError):
    """Report history row was not found for the current user."""

    code = "HISTORY_NOT_FOUND"

class AiReportHistoryCompareInsufficientDataError(AiReportHistoryServiceError):
    """Not enough stored reports for the given symbol/exchange to compare."""
 
    code = "HISTORY_COMPARE_INSUFFICIENT_DATA"

class AiReportHistoryService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: AiReportHistoryRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or create_ai_report_history_repository(self.settings)
        self._repository_injected = repository is not None
        storage_name = getattr(self.repository, "storage_name", "sqlserver")
        if storage_name == "file":
            logger.info("[ai-report-history] storage=file path=%s", getattr(self.repository, "base_dir", ""))
        else:
            logger.info("[ai-report-history] storage=sqlserver configured=%s", bool(str(self.settings.ai_report_db_url or "").strip()))

    def is_persistent_history_available(self) -> bool:
        if getattr(self.repository, "storage_name", "sqlserver") == "file":
            return True
        return bool(self.settings.enable_ai_report_history and str(self.settings.ai_report_db_url or "").strip())

    async def save_report_after_analysis(
        self,
        *,
        current_user: CurrentUserIdentity,
        payload: AnalyseOneReportRequest,
        report_response: dict[str, Any],
        matched_watchlist_item: dict[str, Any] | None,
    ) -> str | None:
        if not self.is_persistent_history_available():
            return None

        history_id = str(uuid.uuid4())
        report_to_store = copy.deepcopy(report_response)
        data = report_to_store.get("data") if isinstance(report_to_store.get("data"), dict) else {}
        data["history_id"] = history_id
        report_to_store["data"] = data

        values = self._build_create_values(
            history_id=history_id,
            current_user=current_user,
            payload=payload,
            report_response=report_to_store,
            matched_watchlist_item=matched_watchlist_item,
        )
        try:
            await asyncio.to_thread(self.repository.create, values)
        except (HistoryStorageNotConfiguredError, AiReportHistoryRepositoryError) as exc:
            if self.settings.ai_report_history_save_failure_policy == "strict":
                raise AiReportHistoryUnavailableError("Không lưu được lịch sử báo cáo AI.") from exc
            self._append_save_warning(report_response)
            return None
        except Exception as exc:
            if self.settings.ai_report_history_save_failure_policy == "strict":
                raise AiReportHistoryUnavailableError("Không lưu được lịch sử báo cáo AI.") from exc
            self._append_save_warning(report_response)
            return None

        response_data = report_response.get("data") if isinstance(report_response.get("data"), dict) else {}
        response_data["history_id"] = history_id
        report_response["data"] = response_data
        return history_id

    async def list_history(self, *, current_user: CurrentUserIdentity, filters: ReportHistoryFilters) -> ReportHistoryListData:
        self._ensure_enabled()
        logger.info(
            "[ai-report-history] request page=%s limit=%s filters=symbol:%s exchange:%s provider:%s model:%s",
            filters.page,
            filters.limit,
            filters.symbol,
            filters.exchange,
            filters.provider,
            filters.model,
        )
        repo_filters = AiReportHistoryFilters(
            symbol=normalize_symbol(filters.symbol) if filters.symbol else None,
            exchange=str(filters.exchange).strip().upper() if filters.exchange else None,
            provider=str(filters.provider).strip() if filters.provider else None,
            model=str(filters.model).strip() if filters.model else None,
            from_date=filters.from_date,
            to_date=filters.to_date,
        )
        page = max(1, int(filters.page or 1))
        limit = min(100, max(1, int(filters.limit or 20)))
        try:
            rows, total = await asyncio.gather(
                asyncio.to_thread(self.repository.list_by_user, current_user.mongo_user_id, filters=repo_filters, page=page, limit=limit),
                asyncio.to_thread(self.repository.count_by_user, current_user.mongo_user_id, filters=repo_filters),
            )
        except (HistoryStorageNotConfiguredError, AiReportHistoryRepositoryError) as exc:
            if getattr(self.repository, "storage_name", "sqlserver") == "file":
                raise AiReportHistoryUnavailableError("Không thể tải lịch sử báo cáo AI.", code="AI_REPORT_HISTORY_STORAGE_ERROR") from exc
            raise AiReportHistoryUnavailableError("Không đọc được lịch sử báo cáo AI.") from exc
        logger.info("[ai-report-history] loaded total=%s page=%s limit=%s", total, page, limit)
        return ReportHistoryListData(
            items=[self._row_to_list_item(row) for row in rows],
            page=page,
            limit=limit,
            total=total,
            total_pages=max(1, math.ceil(total / limit)) if limit else 1,
        )

    async def get_history_detail(self, *, current_user: CurrentUserIdentity, history_id: str) -> ReportHistoryDetailData:
        self._ensure_enabled()
        try:
            row = await asyncio.to_thread(self.repository.get_by_id_for_user, history_id, current_user.mongo_user_id)
        except (HistoryStorageNotConfiguredError, AiReportHistoryRepositoryError) as exc:
            if getattr(self.repository, "storage_name", "sqlserver") == "file":
                raise AiReportHistoryUnavailableError("Không thể tải chi tiết lịch sử báo cáo AI.", code="AI_REPORT_HISTORY_STORAGE_ERROR") from exc
            raise AiReportHistoryUnavailableError("Không đọc được chi tiết lịch sử báo cáo AI.") from exc
        if row is None:
            raise AiReportHistoryNotFoundError("Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.")
        return ReportHistoryDetailData(id=str(row.id), report_id=row.report_id, report_json=self._json_object(row.report_json))

    async def get_history_detail_by_report_id(self, *, current_user: CurrentUserIdentity, report_id: str) -> ReportHistoryDetailData:
        self._ensure_enabled()
        clean_report_id = str(report_id or "").strip()
        if not clean_report_id:
            raise AiReportHistoryNotFoundError("Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.")
        try:
            row = await asyncio.to_thread(self.repository.get_by_report_id_for_user, clean_report_id, current_user.mongo_user_id)
        except (HistoryStorageNotConfiguredError, AiReportHistoryRepositoryError) as exc:
            if getattr(self.repository, "storage_name", "sqlserver") == "file":
                raise AiReportHistoryUnavailableError("Không thể tải chi tiết lịch sử báo cáo AI.", code="AI_REPORT_HISTORY_STORAGE_ERROR") from exc
            raise AiReportHistoryUnavailableError("Không đọc được chi tiết lịch sử báo cáo AI.") from exc
        if row is None:
            raise AiReportHistoryNotFoundError("Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.")
        return ReportHistoryDetailData(id=str(row.id), report_id=row.report_id, report_json=self._json_object(row.report_json))

    async def delete_history(self, *, current_user: CurrentUserIdentity, history_id: str) -> bool:
        self._ensure_enabled()
        try:
            deleted = await asyncio.to_thread(self.repository.delete_by_id_for_user, history_id, current_user.mongo_user_id)
        except (HistoryStorageNotConfiguredError, AiReportHistoryRepositoryError) as exc:
            if getattr(self.repository, "storage_name", "sqlserver") == "file":
                raise AiReportHistoryUnavailableError("Không thể xóa lịch sử báo cáo AI.", code="AI_REPORT_HISTORY_STORAGE_ERROR") from exc
            raise AiReportHistoryUnavailableError("Không xóa được lịch sử báo cáo AI.") from exc
        if not deleted:
            raise AiReportHistoryNotFoundError("Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.")
        return True
    
    async def compare_history(
        self,
        *,
        current_user: CurrentUserIdentity,
        symbol: str,
        exchange: str | None = None,
        baseline_history_id: str | None = None,
        latest_history_id: str | None = None,
    ) -> ReportHistoryCompareData:
        """Compare two already-stored reports for the same symbol/exchange.
 
        Never calls the LLM or crawler: comparison is computed purely from
        columns already persisted in report history (total_score, risk_score,
        data_confidence, decision_label, created_at).
 
        Default behaviour (no ids given): compares the 2 most recent reports
        for `symbol` (+ `exchange` of the current user, auto-resolved from the
        latest report if `exchange` is omitted).
        """
        self._ensure_enabled()
        normalized_symbol = normalize_symbol(symbol)
 
        if baseline_history_id and latest_history_id:
            baseline_row, latest_row = await self._load_explicit_pair(
                current_user=current_user,
                normalized_symbol=normalized_symbol,
                exchange=exchange,
                baseline_history_id=baseline_history_id,
                latest_history_id=latest_history_id,
            )
        else:
            baseline_row, latest_row = await self._load_latest_pair(
                current_user=current_user,
                normalized_symbol=normalized_symbol,
                exchange=exchange,
            )
 
        return self._build_compare_data(baseline_row, latest_row)
 
    async def _load_latest_pair(
        self,
        *,
        current_user: CurrentUserIdentity,
        normalized_symbol: str,
        exchange: str | None,
    ) -> tuple[Any, Any]:
        resolved_exchange = str(exchange).strip().upper() if exchange else None
 
        if not resolved_exchange:
            try:
                probe = await asyncio.to_thread(
                    self.repository.list_by_user,
                    current_user.mongo_user_id,
                    filters=AiReportHistoryFilters(symbol=normalized_symbol),
                    page=1,
                    limit=1,
                )
            except (HistoryStorageNotConfiguredError, AiReportHistoryRepositoryError) as exc:
                raise AiReportHistoryUnavailableError("Không đọc được lịch sử báo cáo AI để so sánh.") from exc
            if not probe:
                raise AiReportHistoryCompareInsufficientDataError(
                    "Chưa có báo cáo nào trong lịch sử cho mã này để so sánh."
                )
            resolved_exchange = str(probe[0].exchange).upper()
 
        try:
            rows = await asyncio.to_thread(
                self.repository.list_by_user,
                current_user.mongo_user_id,
                filters=AiReportHistoryFilters(symbol=normalized_symbol, exchange=resolved_exchange),
                page=1,
                limit=2,
            )
        except (HistoryStorageNotConfiguredError, AiReportHistoryRepositoryError) as exc:
            raise AiReportHistoryUnavailableError("Không đọc được lịch sử báo cáo AI để so sánh.") from exc
 
        if len(rows) < 2:
            raise AiReportHistoryCompareInsufficientDataError(
                "Cần ít nhất 2 báo cáo trong lịch sử cùng mã và sàn để so sánh."
            )
        # repository.list_by_user is ordered by created_at DESC, so rows[0] is the newest.
        return rows[1], rows[0]
 
    async def _load_explicit_pair(
        self,
        *,
        current_user: CurrentUserIdentity,
        normalized_symbol: str,
        exchange: str | None,
        baseline_history_id: str,
        latest_history_id: str,
    ) -> tuple[Any, Any]:
        try:
            baseline_row, latest_row = await asyncio.gather(
                asyncio.to_thread(self.repository.get_by_id_for_user, baseline_history_id, current_user.mongo_user_id),
                asyncio.to_thread(self.repository.get_by_id_for_user, latest_history_id, current_user.mongo_user_id),
            )
        except (HistoryStorageNotConfiguredError, AiReportHistoryRepositoryError) as exc:
            raise AiReportHistoryUnavailableError("Không đọc được lịch sử báo cáo AI để so sánh.") from exc
 
        if baseline_row is None or latest_row is None:
            raise AiReportHistoryNotFoundError("Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.")
 
        for row in (baseline_row, latest_row):
            if normalize_symbol(row.symbol) != normalized_symbol:
                raise AiReportHistoryServiceError(
                    "Hai báo cáo được chọn không cùng mã cổ phiếu.", code="HISTORY_COMPARE_SYMBOL_MISMATCH"
                )
            if exchange and str(row.exchange).upper() != str(exchange).strip().upper():
                raise AiReportHistoryServiceError(
                    "Hai báo cáo được chọn không cùng sàn giao dịch.", code="HISTORY_COMPARE_EXCHANGE_MISMATCH"
                )
 
        if baseline_row.created_at > latest_row.created_at:
            baseline_row, latest_row = latest_row, baseline_row
 
        return baseline_row, latest_row
 
    def _build_compare_data(self, baseline_row: Any, latest_row: Any) -> ReportHistoryCompareData:
        score_delta = self._delta(latest_row.total_score, baseline_row.total_score)
        risk_delta = self._delta(latest_row.risk_score, baseline_row.risk_score)
        confidence_delta = self._delta(latest_row.data_confidence, baseline_row.data_confidence)
 
        score_threshold = float(getattr(self.settings, "report_compare_score_delta_threshold", 3.0))
        risk_threshold = float(getattr(self.settings, "report_compare_risk_delta_threshold", 5.0))
 
        trend, trend_label = self._classify_trend(score_delta, score_threshold)
        recommendation, recommendation_label = self._recommend(trend, risk_delta, risk_threshold)
 
        reasons: list[str] = []
        if score_delta is None:
            reasons.append("Không đủ dữ liệu điểm tổng hợp (total_score) để so sánh chính xác.")
        else:
            reasons.append(f"Điểm tổng hợp thay đổi {score_delta:+.2f} điểm so với báo cáo trước đó.")
        if risk_delta is not None:
            reasons.append(f"Điểm rủi ro thay đổi {risk_delta:+.2f} điểm.")
        if latest_row.decision_label:
            reasons.append(f"Nhãn quyết định của báo cáo mới nhất: {latest_row.decision_label}.")
 
        return ReportHistoryCompareData(
            symbol=latest_row.symbol,
            exchange=latest_row.exchange,
            baseline=self._row_to_compare_item(baseline_row),
            latest=self._row_to_compare_item(latest_row),
            score_delta=score_delta,
            risk_delta=risk_delta,
            confidence_delta=confidence_delta,
            trend=trend,
            trend_label=trend_label,
            recommendation=recommendation,
            recommendation_label=recommendation_label,
            reasons=reasons,
        )
 
    def _classify_trend(self, score_delta: float | None, score_threshold: float) -> tuple[str, str]:
        if score_delta is None:
            return "SIDEWAYS", "Đi ngang"
        if score_delta >= score_threshold:
            return "IMPROVING", "Cải thiện"
        if score_delta <= -score_threshold:
            return "WORSENING", "Xấu đi"
        return "SIDEWAYS", "Đi ngang"
 
    def _recommend(self, trend: str, risk_delta: float | None, risk_threshold: float) -> tuple[str, str]:
        risk_increasing = risk_delta is not None and risk_delta >= risk_threshold
        risk_decreasing = risk_delta is not None and risk_delta < 0
 
        if trend == "IMPROVING":
            if risk_increasing:
                return "WATCH", "Theo dõi"
            return "BUY", "Mua"
        if trend == "WORSENING":
            if risk_decreasing:
                return "WATCH", "Theo dõi"
            return "SELL", "Bán"
        return "HOLD", "Giữ"
    
    def _delta(self, current: Any, previous: Any) -> float | None:
        current_val = self._number(current)
        previous_val = self._number(previous)
        if current_val is None or previous_val is None:
            return None
        return round(current_val - previous_val, 2)
 
    def _row_to_compare_item(self, row: Any) -> ReportHistoryCompareItem:
        return ReportHistoryCompareItem(
            id=str(row.id),
            report_id=row.report_id,
            created_at=row.created_at,
            provider=row.provider,
            model=row.model,
            total_score=self._decimal_to_float(row.total_score),
            risk_score=self._decimal_to_float(row.risk_score),
            data_confidence=self._decimal_to_float(row.data_confidence),
            decision_label=row.decision_label,
        )

    def _ensure_enabled(self) -> None:
        if getattr(self.repository, "storage_name", "sqlserver") == "file":
            return
        if not self.settings.enable_ai_report_history:
            raise AiReportHistoryDisabledError("Tính năng lịch sử báo cáo AI chưa được bật.")
        if not str(self.settings.ai_report_db_url or "").strip():
            raise AiReportHistoryDisabledError("AI_REPORT_DB_URL chưa được cấu hình.")

    def _build_create_values(
        self,
        *,
        history_id: str,
        current_user: CurrentUserIdentity,
        payload: AnalyseOneReportRequest,
        report_response: dict[str, Any],
        matched_watchlist_item: dict[str, Any] | None,
    ) -> dict[str, Any]:
        data = report_response.get("data") if isinstance(report_response.get("data"), dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        provider = data.get("provider") if isinstance(data.get("provider"), dict) else {}
        scores = summary.get("scores") if isinstance(summary.get("scores"), dict) else {}
        decision = summary.get("system_decision") if isinstance(summary.get("system_decision"), dict) else {}
        snapshot = self._summary_snapshot(report_response)
        request_dump = payload.model_dump(by_alias=True)
        return {
            "id": history_id,
            "report_id": self._text(data.get("report_id") or f"{normalize_symbol(payload.symbol)}_{payload.scope_exchange}_{history_id[:8]}", "unknown"),
            "mongo_user_id": current_user.mongo_user_id,
            "user_email": current_user.email,
            "mongo_watchlist_id": self._watchlist_id(matched_watchlist_item),
            "mongo_stock_id": self._stock_id(matched_watchlist_item),
            "symbol": normalize_symbol(data.get("symbol") or payload.symbol),
            "exchange": str(data.get("scope_exchange") or payload.scope_exchange or "").strip().upper() or "HOSE",
            "company": self._optional_text(data.get("company")),
            "provider": self._text(provider.get("name") or payload.provider or self.settings.default_llm_provider, "unknown"),
            "model": self._text(provider.get("model") or payload.model or self._default_model(provider.get("name") or payload.provider), "unknown"),
            "risk_profile": self._optional_text(payload.options.risk_profile),
            "time_horizon": self._optional_text(payload.options.time_horizon),
            "include_external_research": bool(payload.options.include_external_research),
            "total_score": self._number(scores.get("overall_score")),
            "risk_score": self._number(scores.get("risk_score")),
            "data_confidence": self._number(scores.get("score_confidence_normalized") or scores.get("data_confidence") or snapshot.get("data_confidence")),
            "decision_label": self._optional_text(decision.get("status") or snapshot.get("decision_label")),
            "report_json": json.dumps(report_response, ensure_ascii=False, default=str),
            "summary_snapshot": json.dumps(snapshot, ensure_ascii=False, default=str),
            "source_hash": self._hash(data.get("data_sources")),
            "request_hash": self._hash(request_dump),
        }

    def _summary_snapshot(self, report_response: dict[str, Any]) -> dict[str, Any]:
        data = report_response.get("data") if isinstance(report_response.get("data"), dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        scores = summary.get("scores") if isinstance(summary.get("scores"), dict) else {}
        decision = summary.get("system_decision") if isinstance(summary.get("system_decision"), dict) else {}
        provider = data.get("provider") if isinstance(data.get("provider"), dict) else {}
        presentation = summary.get("report_presentation") if isinstance(summary.get("report_presentation"), dict) else {}
        summary_bar = presentation.get("summary_bar") if isinstance(presentation.get("summary_bar"), dict) else {}
        data_confidence = (
            scores.get("score_confidence_normalized")
            or scores.get("data_confidence")
            or summary_bar.get("data_confidence")
            or self._normalize_percent(scores.get("score_confidence"))
        )
        return {
            "report_id": data.get("report_id"),
            "symbol": data.get("symbol"),
            "exchange": data.get("scope_exchange"),
            "company": data.get("company"),
            "provider": provider.get("name"),
            "model": provider.get("model"),
            "total_score": scores.get("overall_score"),
            "risk_score": scores.get("risk_score"),
            "data_confidence": data_confidence,
            "decision_label": decision.get("status"),
            "generated_at": data.get("generated_at"),
        }

    def _row_to_list_item(self, row: AiReportHistory) -> ReportHistoryListItem:
        return ReportHistoryListItem(
            id=str(row.id),
            report_id=row.report_id,
            symbol=row.symbol,
            exchange=row.exchange,
            company=row.company,
            company_name=row.company,
            provider=row.provider,
            model=row.model,
            total_score=self._decimal_to_float(row.total_score),
            score=self._decimal_to_float(row.total_score),
            risk_score=self._decimal_to_float(row.risk_score),
            risk_level=row.decision_label,
            data_confidence=self._decimal_to_float(row.data_confidence),
            decision_label=row.decision_label,
            status=row.decision_label,
            created_at=row.created_at,
            generated_at=row.created_at,
        )

    def _append_save_warning(self, report_response: dict[str, Any]) -> None:
        data = report_response.get("data")
        if not isinstance(data, dict):
            return
        warnings = data.get("warnings")
        if not isinstance(warnings, list):
            warnings = []
        message = "Báo cáo đã phân tích thành công nhưng chưa lưu được lịch sử."
        if message not in warnings:
            warnings.append(message)
        data["warnings"] = warnings

    def _watchlist_id(self, item: dict[str, Any] | None) -> str | None:
        if not isinstance(item, dict):
            return None
        value = item.get("watchlist_id")
        if value:
            return str(value)
        raw = item.get("raw_item") if isinstance(item.get("raw_item"), dict) else {}
        value = raw.get("watchlist_id") or raw.get("watchlistId") or raw.get("_id") or raw.get("id")
        return str(value) if value not in (None, "") else None

    def _stock_id(self, item: dict[str, Any] | None) -> str | None:
        if not isinstance(item, dict):
            return None
        value = item.get("stock_id")
        if value:
            return str(value)
        raw = item.get("raw_item") if isinstance(item.get("raw_item"), dict) else {}
        stock = raw.get("stock") or raw.get("stock_id")
        if isinstance(stock, dict):
            value = stock.get("id") or stock.get("_id") or stock.get("stock_id") or stock.get("stockId")
        else:
            value = stock
        return str(value) if value not in (None, "") else None

    def _json_object(self, value: str) -> dict[str, Any]:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _hash(self, value: Any) -> str | None:
        if value in (None, "", [], {}):
            return None
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _number(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float, Decimal)):
            return float(value)
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _normalize_percent(self, value: Any) -> float | None:
        numeric = self._number(value)
        if numeric is None:
            return None
        if 0 <= numeric <= 1:
            numeric *= 100
        return max(0.0, min(100.0, round(numeric, 2)))

    def _decimal_to_float(self, value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    def _text(self, value: Any, fallback: str) -> str:
        clean = str(value or "").strip()
        return clean or fallback

    def _optional_text(self, value: Any) -> str | None:
        clean = str(value or "").strip()
        return clean or None

    def _default_model(self, provider_name: Any) -> str:
        provider = str(provider_name or self.settings.default_llm_provider).strip().lower()
        return self.settings.gemini_model if provider == "gemini" else self.settings.openai_model
