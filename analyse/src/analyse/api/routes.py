from __future__ import annotations

import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from analyse.api.dependencies import (
    get_ai_report_history_service,
    get_holdings_advice_service,
    get_report_service,
    get_user_identity_service,
    get_visualization_dataset_service,
    get_visualization_signed_url_service,
)
from analyse.config.settings import get_settings
from analyse.schemas.common import api_error, api_success
from analyse.schemas.report import AnalyseOneReportRequest
from analyse.schemas.report_history import ReportHistoryFilters
from analyse.schemas.holdings_advice import HoldingsAdviceRequest
from analyse.schemas.stock import StockAnalysisRequest, StockFetchAnalysisRequest
from analyse.schemas.watchlist import WatchlistAnalysisRequest
from analyse.services.ai_report_history_service import (
    AiReportHistoryCompareInsufficientDataError,
    AiReportHistoryDisabledError,
    AiReportHistoryNotFoundError,
    AiReportHistoryService,
    AiReportHistoryServiceError,
    AiReportHistoryUnavailableError,
)
from analyse.services.config_diagnostic_service import ConfigDiagnosticService
from analyse.services.holdings_advice_service import HoldingsAdviceService
from analyse.services.report_service import ReportService
from analyse.services.user_identity_service import UserIdentityMalformedError, UserIdentityService, UserIdentityUnauthorizedError
from analyse.services.visualization_dataset_service import VisualizationDatasetService
from analyse.services.visualization_signed_url_service import (
    ALLOWED_VISUALIZATION_TABLES,
    VisualizationSignedUrlService,
)
from analyse.utils.auth import get_bearer_token_from_request

router = APIRouter(tags=["analyse"])
logger = logging.getLogger(__name__)


@router.get("/api/analyse/health")
async def health() -> dict:
    return api_success("Analyse service đã sẵn sàng.")


@router.get("/api/analyse/config-check")
async def config_check(check_backend: bool = Query(default=False, alias="checkBackend")) -> dict:
    service = ConfigDiagnosticService(get_settings())
    data = await service.build(check_backend=check_backend)
    return api_success("Kiểm tra cấu hình analyse hoàn tất.", data=data)


@router.post("/api/analyse/stock", include_in_schema=False)
async def analyse_stock(payload: StockAnalysisRequest) -> JSONResponse:
    _ = payload
    return _not_implemented_response("Endpoint legacy /api/analyse/stock chưa được triển khai. Vui lòng dùng /api/ai-reports/analyse-one.")


@router.post("/api/analyse/watchlist", include_in_schema=False)
async def analyse_watchlist(payload: WatchlistAnalysisRequest) -> JSONResponse:
    _ = payload
    return _not_implemented_response("Endpoint legacy /api/analyse/watchlist chưa được triển khai. Vui lòng dùng /api/ai-reports/analyse-one.")


@router.post("/api/analyse/fetch-and-analyse/stock", include_in_schema=False)
async def fetch_and_analyse_stock(payload: StockFetchAnalysisRequest) -> JSONResponse:
    _ = payload
    return _not_implemented_response(
        "Endpoint legacy /api/analyse/fetch-and-analyse/stock chưa được triển khai. Vui lòng dùng /api/ai-reports/analyse-one."
    )


@router.post("/api/ai-reports/analyse-one", response_model=None)
async def analyse_one_report(
    payload: AnalyseOneReportRequest,
    request: Request,
    service: ReportService = Depends(get_report_service),
    visualization_service: VisualizationDatasetService = Depends(get_visualization_dataset_service),
) -> dict | JSONResponse:
    user_token = get_bearer_token_from_request(request)
    result = await service.analyse_one_report(payload, user_token=user_token)
    status_code = int(result.get("code", 200)) if isinstance(result, dict) else 200
    if status_code >= 400:
        return JSONResponse(status_code=status_code, content=result)
    _cache_visualization_from_current_report(
        result=result,
        payload=payload,
        visualization_service=visualization_service,
    )
    return result


@router.post("/api/ai-reports/holdings-advice", response_model=None)
async def holdings_advice(
    payload: HoldingsAdviceRequest,
    request: Request,
    service: HoldingsAdviceService = Depends(get_holdings_advice_service),
) -> dict | JSONResponse:
    """
    Phân tích danh mục holdings và đưa ra khuyến nghị BUY/HOLD/SELL cho từng mã.

    **Chiến lược Same-Day Dedup:**
    - Crawler chỉ chạy 1 lần/ngày (EOD) → giá không đổi trong ngày
    - Nếu đã có báo cáo AI cho mã này hôm nay → trả cache (< 1s, `source: "cache"`)
    - Nếu chưa có → gọi LLM với P&L context (30-120s, `source: "generated"`)
    - Nếu LLM lỗi → graceful degradation với rule-based signal (`source: "fallback"`)

    **Rate limit:**
    - Tối đa 2 LLM calls song song (asyncio.Semaphore)
    - `forceRefresh: true` bỏ qua cache, tạo báo cáo mới

    **Body:**
    ```json
    {
      "items": [{
        "symbol": "HPG",
        "exchange": "HOSE",
        "average_cost": 25000,
        "quantity": 1000,
        "unrealized_pnl": 2150000,
        "unrealized_pnl_pct": 8.6,
        "status": "PROFIT"
      }],
      "forceRefresh": false
    }
    ```
    """
    user_token = get_bearer_token_from_request(request)
    if not str(user_token or "").strip():
        return JSONResponse(
            status_code=401,
            content={
                "code": 401,
                "success": False,
                "message": "Missing Authorization header. Please login again.",
                "error": {"type": "AUTH_REQUIRED", "code": "AUTH_REQUIRED", "details": []},
                "data": None,
            },
        )

    try:
        result = await service.generate_advice(payload, user_token)
    except Exception as exc:
        logger.error("[holdings-advice] unhandled error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "success": False,
                "message": "Không tạo được khuyến nghị danh mục.",
                "error": {"type": "HOLDINGS_ADVICE_ERROR", "code": "HOLDINGS_ADVICE_ERROR", "details": []},
                "data": None,
            },
        )

    status_code = int(result.get("code", 200)) if isinstance(result, dict) else 200
    if status_code >= 400:
        return JSONResponse(status_code=status_code, content=result)
    return result


@router.post("/api/ai-reports/analyse-one/visualization-data", response_model=None)
async def analyse_one_visualization_data(
    payload: AnalyseOneReportRequest,
    request: Request,
    service: ReportService = Depends(get_report_service),
    identity_service: UserIdentityService = Depends(get_user_identity_service),
    history_service: AiReportHistoryService = Depends(get_ai_report_history_service),
    visualization_service: VisualizationDatasetService = Depends(get_visualization_dataset_service),
) -> dict | JSONResponse:
    started = time.perf_counter()
    user_token = get_bearer_token_from_request(request)
    _ = service
    settings = visualization_service.settings
    if not settings.visualization_export_enabled:
        return _error_response(503, "Tính năng xuất dữ liệu trực quan hóa chưa được bật.", "VISUALIZATION_EXPORT_DISABLED")

    chart_range = _visualization_chart_range(payload, settings.visualization_default_chart_range)
    report_id = _payload_report_id(payload)
    if report_id:
        logger.info(
            "[visualization-data] start report_id=%s symbol=%s exchange=%s",
            report_id,
            payload.symbol,
            payload.scope_exchange,
        )
        cached_dataset = visualization_service.get_cached_dataset(
            symbol=payload.symbol,
            exchange=payload.scope_exchange,
            chart_range=chart_range,
            report_id=report_id,
        )
        cache_hit = cached_dataset is not None
        if cached_dataset is None:
            cache_started = time.perf_counter()
            logger.info("[visualization-data] cache_read_start report_id=%s", report_id)
            cached_dataset = visualization_service.load_visualization_json_file(report_id)
            logger.info(
                "[visualization-data] cache_read_done report_id=%s hit=%s duration_ms=%s",
                report_id,
                bool(cached_dataset),
                _duration_ms(cache_started),
            )
            cache_hit = cached_dataset is not None
        if cached_dataset is not None:
            visualization_service.store_dataset_cache(cached_dataset, chart_range=chart_range)
            logger.info(
                "[visualization-data] report_id=%s cache_hit=true total_ms=%s",
                cached_dataset.meta.source_report_id,
                _duration_ms(started),
            )
            return api_success("Tải dữ liệu biểu đồ thành công.", data=_visualization_response_data(cached_dataset, cache_hit=cache_hit, duration_ms=_duration_ms(started)))

        current_user = await _resolve_current_user(user_token, identity_service)
        if isinstance(current_user, JSONResponse):
            return current_user
        try:
            load_started = time.perf_counter()
            logger.info("[visualization-data] load_saved_report start report_id=%s via=report_id", report_id)
            detail = await history_service.get_history_detail_by_report_id(current_user=current_user, report_id=report_id)
            logger.info("[visualization-data] load_saved_report done report_id=%s duration_ms=%s", report_id, _duration_ms(load_started))
        except AiReportHistoryDisabledError:
            logger.warning("[visualization-data] failed status=404 code=REPORT_NOT_FOUND details=history_disabled report_id=%s", report_id)
            return _error_response(
                404,
                "Không tìm thấy báo cáo đã lưu để tạo biểu đồ.",
                "REPORT_NOT_FOUND",
                details=[{"field": "report_id", "message": f"{report_id}; history disabled and visualization cache miss"}],
            )
        except AiReportHistoryNotFoundError:
            logger.warning("[visualization-data] failed status=404 code=REPORT_NOT_FOUND details=not_found report_id=%s", report_id)
            return _error_response(
                404,
                "Không tìm thấy báo cáo để tạo biểu đồ.",
                "REPORT_NOT_FOUND",
                details=[{"field": "report_id", "message": report_id}],
            )
        except AiReportHistoryUnavailableError:
            logger.warning("[visualization-data] failed status=404 code=REPORT_NOT_FOUND details=history_unavailable_cache_miss report_id=%s", report_id)
            return _error_response(
                404,
                "Không tìm thấy báo cáo đã lưu/cache để tạo biểu đồ.",
                "REPORT_NOT_FOUND",
                details=[{"field": "report_id", "message": f"{report_id}; history unavailable and visualization cache miss"}],
            )

        dataset, cache_hit, build_ms = _load_or_build_visualization_dataset(
            detail=detail,
            visualization_service=visualization_service,
            chart_range=chart_range,
        )
        if isinstance(dataset, JSONResponse):
            return dataset
        logger.info(
            "[visualization-data] success report_id=%s chart_count=%s cache_hit=%s build_ms=%s total_ms=%s",
            dataset.meta.source_report_id,
            len((dataset.visualization or {}).get("charts") or []),
            str(cache_hit).lower(),
            build_ms,
            _duration_ms(started),
        )
        return api_success("Tải dữ liệu biểu đồ thành công.", data=_visualization_response_data(dataset, cache_hit=cache_hit, duration_ms=_duration_ms(started)))

    cached_dataset = visualization_service.get_cached_dataset(symbol=payload.symbol, exchange=payload.scope_exchange, chart_range=chart_range)
    if cached_dataset is not None:
        logger.info(
            "[visualization] report_id=%s cache_hit=true total_ms=%s route=analyse_one_visualization_data symbol_cache=true",
            cached_dataset.meta.source_report_id,
            _duration_ms(started),
        )
        return api_success("Visualization dataset generated successfully.", data=_visualization_response_data(cached_dataset, cache_hit=True, duration_ms=_duration_ms(started)))

    logger.info(
        "[visualization] report_id=missing symbol=%s exchange=%s cache_hit=false total_ms=%s route=analyse_one_visualization_data",
        payload.symbol,
        payload.scope_exchange,
        _duration_ms(started),
    )
    return _error_response(
        400,
        "Thiếu report_id để tải dữ liệu biểu đồ đã lưu. Visualization không chạy lại phân tích cổ phiếu.",
        "VISUALIZATION_REPORT_ID_REQUIRED",
    )


@router.post("/api/ai-reports/analyse-one/visualization-data.csv")
async def analyse_one_visualization_csv(
    payload: AnalyseOneReportRequest,
    request: Request,
    table: str = Query(default="prices"),
    identity_service: UserIdentityService = Depends(get_user_identity_service),
    history_service: AiReportHistoryService = Depends(get_ai_report_history_service),
    visualization_service: VisualizationDatasetService = Depends(get_visualization_dataset_service),
) -> Response:
    started = time.perf_counter()
    user_token = get_bearer_token_from_request(request)
    settings = visualization_service.settings
    if not settings.visualization_export_enabled:
        return _error_response(503, "Tính năng xuất dữ liệu trực quan hóa chưa được bật.", "VISUALIZATION_EXPORT_DISABLED")
    if not settings.visualization_csv_export_enabled:
        return _error_response(503, "Tính năng xuất CSV trực quan hóa chưa được bật.", "VISUALIZATION_CSV_EXPORT_DISABLED")

    chart_range = _visualization_chart_range(payload, settings.visualization_default_chart_range)
    report_id = _payload_report_id(payload)
    dataset = visualization_service.get_cached_dataset(
        symbol=payload.symbol,
        exchange=payload.scope_exchange,
        chart_range=chart_range,
        report_id=report_id,
    )
    if dataset is None and report_id:
        dataset = visualization_service.load_visualization_json_file(report_id)
        if dataset is not None:
            visualization_service.store_dataset_cache(dataset, chart_range=chart_range)
    if dataset is None and report_id:
        current_user = await _resolve_current_user(user_token, identity_service)
        if isinstance(current_user, JSONResponse):
            return current_user
        try:
            detail = await history_service.get_history_detail_by_report_id(
                current_user=current_user,
                report_id=report_id,
            )
        except AiReportHistoryNotFoundError:
            detail = None
        except AiReportHistoryDisabledError:
            detail = None
        except AiReportHistoryUnavailableError:
            detail = None
        if detail is not None and _has_report_data(detail.report_json):
            dataset = visualization_service.build_from_report_response(detail.report_json, chart_range=chart_range)
            visualization_service.store_dataset_cache(dataset, chart_range=chart_range)
            visualization_service.export_visualization_json_file(dataset)

    if dataset is None:
        logger.info(
            "endpoint=analyse_one_visualization_csv cache=miss report_id=%s symbol=%s exchange=%s table=%s duration_ms=%s",
            report_id,
            payload.symbol,
            payload.scope_exchange,
            table,
            _duration_ms(started),
        )
        return _error_response(
            404,
            "Không tìm thấy dữ liệu trực quan hóa đã lưu cho báo cáo này. Vui lòng mở tab Biểu đồ trực quan trước hoặc tải CSV từ lịch sử báo cáo.",
            "VISUALIZATION_NOT_FOUND",
            details=[{"field": "report_id", "message": report_id or "missing"}, {"field": "table", "message": table}],
        )

    return _csv_file_response(
        visualization_service=visualization_service,
        dataset=dataset,
        table=table,
        started=started,
        endpoint_name="analyse_one_visualization_csv",
    )


@router.get("/api/ai-reports/history")
async def list_report_history(
    request: Request,
    symbol: str | None = Query(default=None),
    exchange: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None, alias="fromDate"),
    to_date: datetime | None = Query(default=None, alias="toDate"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    identity_service: UserIdentityService = Depends(get_user_identity_service),
    history_service: AiReportHistoryService = Depends(get_ai_report_history_service),
):
    user_token = get_bearer_token_from_request(request)
    current_user = await _resolve_current_user(user_token, identity_service)
    if isinstance(current_user, JSONResponse):
        return current_user
    filters = ReportHistoryFilters(
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        model=model,
        fromDate=from_date,
        toDate=to_date,
        page=page,
        limit=limit,
    )
    try:
        data = await history_service.list_history(current_user=current_user, filters=filters)
    except AiReportHistoryDisabledError:
        return _error_response(503, "Tính năng lịch sử báo cáo AI chưa được bật.", "HISTORY_DISABLED")
    except AiReportHistoryUnavailableError as exc:
        if getattr(exc, "code", "") == "AI_REPORT_HISTORY_STORAGE_ERROR":
            return _error_response(500, "Không thể tải lịch sử báo cáo AI.", "AI_REPORT_HISTORY_STORAGE_ERROR")
        return _error_response(503, "Không đọc được lịch sử báo cáo AI trong lần này.", "HISTORY_UNAVAILABLE")
    response_data = data.model_dump()
    message = "Không có báo cáo AI nào trong lịch sử." if _history_total(response_data, data) == 0 else "Tải lịch sử báo cáo AI thành công."
    return api_success(message, data=response_data)

@router.get("/api/ai-reports/history/compare")
async def compare_report_history(
    request: Request,
    symbol: str = Query(...),
    exchange: str | None = Query(default=None),
    baseline_history_id: str | None = Query(default=None, alias="baselineHistoryId"),
    latest_history_id: str | None = Query(default=None, alias="latestHistoryId"),
    identity_service: UserIdentityService = Depends(get_user_identity_service),
    history_service: AiReportHistoryService = Depends(get_ai_report_history_service),
):
    user_token = get_bearer_token_from_request(request)
    current_user = await _resolve_current_user(user_token, identity_service)
    if isinstance(current_user, JSONResponse):
        return current_user

    if bool(baseline_history_id) != bool(latest_history_id):
        return _error_response(
            422,
            "Cần truyền cả baselineHistoryId và latestHistoryId, hoặc bỏ trống cả hai để dùng 2 báo cáo mới nhất.",
            "HISTORY_COMPARE_INVALID_PARAMS",
        )

    try:
        data = await history_service.compare_history(
            current_user=current_user,
            symbol=symbol,
            exchange=exchange,
            baseline_history_id=baseline_history_id,
            latest_history_id=latest_history_id,
        )
    except AiReportHistoryDisabledError:
        return _error_response(503, "Tính năng lịch sử báo cáo AI chưa được bật.", "HISTORY_DISABLED")
    except AiReportHistoryCompareInsufficientDataError as exc:
        return _error_response(422, str(exc), exc.code)
    except AiReportHistoryNotFoundError:
        return _error_response(404, "Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.", "HISTORY_NOT_FOUND")
    except AiReportHistoryServiceError as exc:
        return _error_response(422, str(exc), exc.code)
    except AiReportHistoryUnavailableError as exc:
        if getattr(exc, "code", "") == "AI_REPORT_HISTORY_STORAGE_ERROR":
            return _error_response(500, "Không thể tải lịch sử báo cáo AI.", "AI_REPORT_HISTORY_STORAGE_ERROR")
        return _error_response(503, "Không đọc được lịch sử báo cáo AI trong lần này.", "HISTORY_UNAVAILABLE")

    return api_success("So sánh báo cáo lịch sử thành công.", data=data.model_dump())

@router.get("/api/ai-reports/history/{history_id}/visualization-data")
async def get_report_history_visualization_data(
    history_id: str,
    request: Request,
    identity_service: UserIdentityService = Depends(get_user_identity_service),
    history_service: AiReportHistoryService = Depends(get_ai_report_history_service),
    visualization_service: VisualizationDatasetService = Depends(get_visualization_dataset_service),
):
    started = time.perf_counter()
    user_token = get_bearer_token_from_request(request)
    settings = visualization_service.settings
    if not settings.visualization_export_enabled:
        return _error_response(503, "Tính năng xuất dữ liệu trực quan hóa chưa được bật.", "VISUALIZATION_EXPORT_DISABLED")

    current_user = await _resolve_current_user(user_token, identity_service)
    if isinstance(current_user, JSONResponse):
        return current_user
    try:
        detail = await history_service.get_history_detail(current_user=current_user, history_id=history_id)
    except AiReportHistoryDisabledError:
        return _error_response(503, "Tính năng lịch sử báo cáo AI chưa được bật.", "HISTORY_DISABLED")
    except AiReportHistoryNotFoundError:
        return _error_response(404, "Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.", "HISTORY_NOT_FOUND")
    except AiReportHistoryUnavailableError as exc:
        if getattr(exc, "code", "") == "AI_REPORT_HISTORY_STORAGE_ERROR":
            return _error_response(500, "Không thể tải chi tiết lịch sử báo cáo AI.", "AI_REPORT_HISTORY_STORAGE_ERROR")
        return _error_response(503, "Không đọc được chi tiết lịch sử báo cáo AI trong lần này.", "HISTORY_UNAVAILABLE")

    dataset, cache_hit, build_ms = _load_or_build_visualization_dataset(
        detail=detail,
        visualization_service=visualization_service,
    )
    if isinstance(dataset, JSONResponse):
        return dataset
    logger.info(
        "[visualization] endpoint=get_report_history_visualization_data history_id=%s report_id=%s symbol=%s exchange=%s cache_hit=%s build_ms=%s duration_ms=%s",
        history_id,
        dataset.meta.source_report_id,
        dataset.symbol,
        dataset.exchange,
        str(cache_hit).lower(),
        build_ms,
        _duration_ms(started),
    )
    return api_success("Visualization dataset generated successfully.", data=_visualization_response_data(dataset, cache_hit=cache_hit, duration_ms=_duration_ms(started)))


@router.get("/api/ai-reports/history/{history_id}/visualization-data.csv")
async def get_report_history_visualization_csv(
    history_id: str,
    request: Request,
    table: str = Query(default="prices"),
    identity_service: UserIdentityService = Depends(get_user_identity_service),
    history_service: AiReportHistoryService = Depends(get_ai_report_history_service),
    visualization_service: VisualizationDatasetService = Depends(get_visualization_dataset_service),
) -> Response:
    started = time.perf_counter()
    user_token = get_bearer_token_from_request(request)
    settings = visualization_service.settings
    if not settings.visualization_export_enabled:
        return _error_response(503, "Tính năng xuất dữ liệu trực quan hóa chưa được bật.", "VISUALIZATION_EXPORT_DISABLED")
    if not settings.visualization_csv_export_enabled:
        return _error_response(503, "Tính năng xuất CSV trực quan hóa chưa được bật.", "VISUALIZATION_CSV_EXPORT_DISABLED")

    current_user = await _resolve_current_user(user_token, identity_service)
    if isinstance(current_user, JSONResponse):
        return current_user
    try:
        detail = await history_service.get_history_detail(current_user=current_user, history_id=history_id)
    except AiReportHistoryDisabledError:
        return _error_response(503, "Tính năng lịch sử báo cáo AI chưa được bật.", "HISTORY_DISABLED")
    except AiReportHistoryNotFoundError:
        return _error_response(404, "Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.", "HISTORY_NOT_FOUND")
    except AiReportHistoryUnavailableError as exc:
        if getattr(exc, "code", "") == "AI_REPORT_HISTORY_STORAGE_ERROR":
            return _error_response(500, "Không thể tải chi tiết lịch sử báo cáo AI.", "AI_REPORT_HISTORY_STORAGE_ERROR")
        return _error_response(503, "Không đọc được chi tiết lịch sử báo cáo AI trong lần này.", "HISTORY_UNAVAILABLE")

    dataset = visualization_service.get_cached_dataset(report_id=detail.report_id)
    cache_status = "hit"
    if dataset is None:
        cache_status = "miss"
        if not _has_report_data(detail.report_json):
            return _error_response(422, "Dữ liệu báo cáo không đủ để tạo biểu đồ.", "MALFORMED_REPORT_DATA")
        dataset = visualization_service.build_from_report_response(detail.report_json)
        visualization_service.store_dataset_cache(dataset)
    logger.info(
        "[export_csv] endpoint=get_report_history_visualization_csv cache=%s history_id=%s report_id=%s symbol=%s exchange=%s table=%s",
        cache_status,
        history_id,
        dataset.meta.source_report_id,
        dataset.symbol,
        dataset.exchange,
        table,
    )
    return _csv_file_response(
        visualization_service=visualization_service,
        dataset=dataset,
        table=table,
        started=started,
        endpoint_name="get_report_history_visualization_csv",
    )


@router.get("/api/ai-reports/history/{history_id}/data-formulator-package.json")
async def get_report_history_data_formulator_package(
    history_id: str,
    request: Request,
    identity_service: UserIdentityService = Depends(get_user_identity_service),
    history_service: AiReportHistoryService = Depends(get_ai_report_history_service),
    visualization_service: VisualizationDatasetService = Depends(get_visualization_dataset_service),
) -> Response:
    started = time.perf_counter()
    user_token = get_bearer_token_from_request(request)
    if not visualization_service.settings.visualization_export_enabled:
        return _error_response(503, "Tính năng xuất dữ liệu trực quan hóa chưa được bật.", "VISUALIZATION_EXPORT_DISABLED")

    current_user = await _resolve_current_user(user_token, identity_service)
    if isinstance(current_user, JSONResponse):
        return current_user
    try:
        detail = await history_service.get_history_detail(current_user=current_user, history_id=history_id)
    except AiReportHistoryDisabledError:
        return _error_response(503, "Tính năng lịch sử báo cáo AI chưa được bật.", "HISTORY_DISABLED")
    except AiReportHistoryNotFoundError:
        return _error_response(404, "Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.", "HISTORY_NOT_FOUND")
    except AiReportHistoryUnavailableError as exc:
        if getattr(exc, "code", "") == "AI_REPORT_HISTORY_STORAGE_ERROR":
            return _error_response(500, "Không thể tải chi tiết lịch sử báo cáo AI.", "AI_REPORT_HISTORY_STORAGE_ERROR")
        return _error_response(503, "Không đọc được chi tiết lịch sử báo cáo AI trong lần này.", "HISTORY_UNAVAILABLE")

    dataset = visualization_service.get_cached_dataset(report_id=detail.report_id)
    if dataset is None:
        if not _has_report_data(detail.report_json):
            return _error_response(422, "Dữ liệu báo cáo không đủ để tạo biểu đồ.", "MALFORMED_REPORT_DATA")
        dataset = visualization_service.build_from_report_response(detail.report_json)
        visualization_service.store_dataset_cache(dataset)
    path = visualization_service.export_data_formulator_package_file(dataset)
    logger.info(
        "endpoint=get_report_history_data_formulator_package history_id=%s report_id=%s symbol=%s exchange=%s duration_ms=%s export_file=%s",
        history_id,
        dataset.meta.source_report_id,
        dataset.symbol,
        dataset.exchange,
        _duration_ms(started),
        path,
    )
    return FileResponse(
        path,
        media_type="application/json; charset=utf-8",
        filename=path.name,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get("/api/ai-reports/history/{history_id}")
async def get_report_history_detail(
    history_id: str,
    request: Request,
    identity_service: UserIdentityService = Depends(get_user_identity_service),
    history_service: AiReportHistoryService = Depends(get_ai_report_history_service),
):
    user_token = get_bearer_token_from_request(request)
    current_user = await _resolve_current_user(user_token, identity_service)
    if isinstance(current_user, JSONResponse):
        return current_user
    try:
        data = await history_service.get_history_detail(current_user=current_user, history_id=history_id)
    except AiReportHistoryDisabledError:
        return _error_response(503, "Tính năng lịch sử báo cáo AI chưa được bật.", "HISTORY_DISABLED")
    except AiReportHistoryNotFoundError:
        return _error_response(404, "Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.", "HISTORY_NOT_FOUND")
    except AiReportHistoryUnavailableError as exc:
        if getattr(exc, "code", "") == "AI_REPORT_HISTORY_STORAGE_ERROR":
            return _error_response(500, "Không thể tải chi tiết lịch sử báo cáo AI.", "AI_REPORT_HISTORY_STORAGE_ERROR")
        return _error_response(503, "Không đọc được chi tiết lịch sử báo cáo AI trong lần này.", "HISTORY_UNAVAILABLE")
    return api_success("Lấy chi tiết lịch sử báo cáo AI thành công.", data=data.model_dump())


@router.delete("/api/ai-reports/history/{history_id}")
async def delete_report_history(
    history_id: str,
    request: Request,
    identity_service: UserIdentityService = Depends(get_user_identity_service),
    history_service: AiReportHistoryService = Depends(get_ai_report_history_service),
):
    user_token = get_bearer_token_from_request(request)
    current_user = await _resolve_current_user(user_token, identity_service)
    if isinstance(current_user, JSONResponse):
        return current_user

    try:
        await history_service.delete_history(current_user=current_user, history_id=history_id)
    except AiReportHistoryDisabledError:
        return _error_response(503, "Tính năng lịch sử báo cáo AI chưa được bật.", "HISTORY_DISABLED")
    except AiReportHistoryNotFoundError:
        return _error_response(404, "Không tìm thấy báo cáo trong lịch sử của người dùng hiện tại.", "HISTORY_NOT_FOUND")
    except AiReportHistoryUnavailableError as exc:
        if getattr(exc, "code", "") == "AI_REPORT_HISTORY_STORAGE_ERROR":
            return _error_response(500, "Không thể xóa lịch sử báo cáo AI.", "AI_REPORT_HISTORY_STORAGE_ERROR")
        return _error_response(503, "Không xóa được lịch sử báo cáo AI trong lần này.", "HISTORY_UNAVAILABLE")
    return api_success("Xóa lịch sử báo cáo AI thành công.", data={"deleted": True})


@router.post("/api/ai-reports/analyse-one/visualization-data/signed-url", response_model=None)
async def create_visualization_signed_url(
    payload: AnalyseOneReportRequest,
    request: Request,
    identity_service: UserIdentityService = Depends(get_user_identity_service),
    history_service: AiReportHistoryService = Depends(get_ai_report_history_service),
    visualization_service: VisualizationDatasetService = Depends(get_visualization_dataset_service),
    signed_url_service: VisualizationSignedUrlService = Depends(get_visualization_signed_url_service),
) -> dict | JSONResponse:
    """Create temporary public links for an existing saved visualization dataset."""
    user_token = get_bearer_token_from_request(request)
    settings = visualization_service.settings

    if not settings.visualization_export_enabled:
        return _error_response(503, "Tính năng xuất dữ liệu trực quan hóa chưa được bật.", "VISUALIZATION_EXPORT_DISABLED")

    if not settings.data_formulator_signed_url_secret:
        return _error_response(503, "DATA_FORMULATOR_SIGNED_URL_SECRET chưa được cấu hình.", "SIGNED_URL_NOT_CONFIGURED")

    chart_range = _visualization_chart_range(payload, settings.visualization_default_chart_range)
    report_id = _payload_report_id(payload)
    dataset = visualization_service.get_cached_dataset(
        symbol=payload.symbol,
        exchange=payload.scope_exchange,
        chart_range=chart_range,
        report_id=report_id,
    )
    if dataset is None and report_id:
        dataset = visualization_service.load_visualization_json_file(report_id)
        if dataset is not None:
            visualization_service.store_dataset_cache(dataset, chart_range=chart_range)
    if dataset is None and report_id:
        current_user = await _resolve_current_user(user_token, identity_service)
        if isinstance(current_user, JSONResponse):
            return current_user
        try:
            detail = await history_service.get_history_detail_by_report_id(
                current_user=current_user,
                report_id=report_id,
            )
        except AiReportHistoryNotFoundError:
            return _error_response(
                404,
                "Không tìm thấy dữ liệu biểu đồ đã lưu để tạo signed URL.",
                "VISUALIZATION_DATASET_NOT_FOUND",
                details=[{"field": "report_id", "message": report_id}],
            )
        except AiReportHistoryDisabledError:
            return _error_response(
                404,
                "Không tìm thấy dữ liệu biểu đồ đã lưu để tạo signed URL.",
                "VISUALIZATION_DATASET_NOT_FOUND",
                details=[{"field": "report_id", "message": f"{report_id}; history disabled"}],
            )
        except AiReportHistoryUnavailableError:
            return _error_response(
                404,
                "Không tìm thấy dữ liệu biểu đồ đã lưu để tạo signed URL.",
                "VISUALIZATION_DATASET_NOT_FOUND",
                details=[{"field": "report_id", "message": f"{report_id}; history unavailable"}],
            )
        if not _has_report_data(detail.report_json):
            return _error_response(422, "Dữ liệu báo cáo không đủ để tạo signed URL.", "MALFORMED_REPORT_DATA")
        dataset = visualization_service.build_from_report_response(detail.report_json, chart_range=chart_range)
        visualization_service.store_dataset_cache(dataset, chart_range=chart_range)
        visualization_service.export_visualization_json_file(dataset)
    if dataset is None:
        return _error_response(
            404,
            "Không tìm thấy dữ liệu biểu đồ đã lưu để tạo signed URL.",
            "VISUALIZATION_DATASET_NOT_FOUND",
            details=[{"field": "report_id", "message": report_id or "missing"}],
        )

    dataset_id = signed_url_service.generate_dataset_id(dataset.symbol, dataset.exchange)
    cache_entry = visualization_service.store_signed_dataset(
        dataset_id=dataset_id,
        dataset=dataset,
        ttl_seconds=settings.visualization_dataset_ttl_seconds,
    )

    try:
        dataset_url = signed_url_service.generate_signed_dataset_url(
            symbol=dataset.symbol,
            exchange=dataset.exchange,
            chart_range=chart_range,
            format="json",
            ttl_seconds=settings.visualization_dataset_ttl_seconds,
            dataset_id=dataset_id,
        )

        csv_urls = {}
        for table in dataset.tables:
            try:
                csv_url = signed_url_service.generate_csv_download_url(
                    symbol=dataset.symbol,
                    exchange=dataset.exchange,
                    table=table.name,
                    ttl_seconds=settings.visualization_dataset_ttl_seconds,
                    dataset_id=dataset_id,
                )
                csv_urls[table.name] = csv_url
            except Exception:
                pass

        expires_at = cache_entry.get("expires_at_iso") or _calculate_expiry(settings.visualization_dataset_ttl_seconds)
        logger.info(
            "Signed dataset created: dataset_id=%s symbol=%s exchange=%s tables=%s expires_at=%s cache_size=%s",
            dataset_id,
            dataset.symbol,
            dataset.exchange,
            cache_entry.get("available_tables", []),
            cache_entry.get("expires_at"),
            visualization_service.signed_dataset_cache_size(),
        )

        return api_success(
            "Signed URL generated successfully.",
            data={
                "dataset_id": dataset_id,
                "dataset_url": dataset_url,
                "csv_urls": csv_urls,
                "expires_at": expires_at,
                "available_tables": [table.name for table in dataset.tables],
            },
        )
    except ValueError as exc:
        return _error_response(500, str(exc), "SIGNED_URL_GENERATION_ERROR")
    except Exception as exc:
        return _error_response(500, f"Error generating signed URL: {exc}", "SIGNED_URL_GENERATION_ERROR")


@router.get("/api/ai-reports/visualization-datasets/{dataset_id}.csv")
async def get_visualization_csv_signed(
    dataset_id: str,
    table: str = Query(default="prices"),
    expires: int = Query(...),
    signature: str | None = Query(default=None),
    visualization_service: VisualizationDatasetService = Depends(get_visualization_dataset_service),
    signed_url_service: VisualizationSignedUrlService = Depends(get_visualization_signed_url_service),
) -> Response:
    """Serve CSV table via signed URL."""
    settings = visualization_service.settings

    if not settings.visualization_export_enabled:
        return _error_response(503, "Tính năng xuất dữ liệu trực quan hóa chưa được bật.", "VISUALIZATION_EXPORT_DISABLED")

    if not settings.visualization_csv_export_enabled:
        return _error_response(503, "Tính năng xuất CSV chưa được bật.", "VISUALIZATION_CSV_EXPORT_DISABLED")
    if not str(settings.data_formulator_signed_url_secret or "").strip():
        return _error_response(503, "Signed dataset URL chưa được cấu hình.", "SIGNED_URL_NOT_CONFIGURED")
    if signature is None or not signature.strip():
        return _error_response(403, "Missing signature", "INVALID_SIGNATURE")

    # Validate table name
    if table not in ALLOWED_VISUALIZATION_TABLES:
        return _error_response(400, f"Invalid table: {table}. Allowed: {', '.join(sorted(ALLOWED_VISUALIZATION_TABLES))}", "INVALID_TABLE")

    # Verify signature
    is_valid, error_msg = signed_url_service.verify_csv_signature(
        dataset_id=dataset_id,
        format="csv",
        table=table,
        expires=expires,
        signature=signature,
    )

    if not is_valid:
        status_code = 401 if "expired" in str(error_msg).lower() else 403
        return _error_response(status_code, error_msg or "Invalid signature", "INVALID_SIGNATURE")

    try:
        cache_entry = visualization_service.get_signed_dataset_entry(dataset_id)
        if cache_entry is None:
            logger.info(
                "Signed CSV cache miss: dataset_id=%s table=%s cache_size=%s",
                dataset_id,
                table,
                visualization_service.signed_dataset_cache_size(),
            )
            return _error_response(404, "Signed dataset không tồn tại hoặc đã hết hạn cache.", "SIGNED_DATASET_NOT_FOUND")
        logger.info(
            "Signed CSV cache hit: dataset_id=%s table=%s expires_at=%s cache_size=%s",
            dataset_id,
            table,
            cache_entry.get("expires_at"),
            visualization_service.signed_dataset_cache_size(),
        )
        dataset = visualization_service.get_signed_dataset(dataset_id)
        if dataset is None:
            return _error_response(404, "Signed dataset không tồn tại hoặc đã hết hạn cache.", "SIGNED_DATASET_NOT_FOUND")
        return _csv_file_response(
            visualization_service=visualization_service,
            dataset=dataset,
            table=table,
            started=time.perf_counter(),
            endpoint_name="get_visualization_csv_signed",
        )
    except ValueError:
        return _error_response(404, f"Table not found: {table}", "TABLE_NOT_FOUND")
    except Exception as exc:
        return _error_response(500, f"Error serving CSV: {exc}", "CSV_ERROR")


@router.get("/api/ai-reports/visualization-datasets/{dataset_id}.json")
async def get_visualization_dataset_signed(
    dataset_id: str,
    expires: int = Query(...),
    signature: str | None = Query(default=None),
    visualization_service: VisualizationDatasetService = Depends(get_visualization_dataset_service),
    signed_url_service: VisualizationSignedUrlService = Depends(get_visualization_signed_url_service),
) -> Response:
    """Serve visualization.v1 JSON via signed URL without user Authorization."""
    settings = visualization_service.settings

    if not settings.visualization_export_enabled:
        return _error_response(503, "Tính năng xuất dữ liệu trực quan hóa chưa được bật.", "VISUALIZATION_EXPORT_DISABLED")
    if not str(settings.data_formulator_signed_url_secret or "").strip():
        return _error_response(503, "Signed dataset URL chưa được cấu hình.", "SIGNED_URL_NOT_CONFIGURED")
    if signature is None or not signature.strip():
        return _error_response(403, "Missing signature", "INVALID_SIGNATURE")

    # Verify signature
    is_valid, error_msg = signed_url_service.verify_signature(
        dataset_id=dataset_id,
        format="json",
        expires=expires,
        signature=signature,
    )

    if not is_valid:
        status_code = 401 if "expired" in str(error_msg).lower() else 403
        return _error_response(status_code, error_msg or "Invalid signature", "INVALID_SIGNATURE")

    try:
        cache_entry = visualization_service.get_signed_dataset_entry(dataset_id)
        if cache_entry is None:
            logger.info(
                "Signed JSON cache miss: dataset_id=%s format=%s cache_size=%s",
                dataset_id,
                "json",
                visualization_service.signed_dataset_cache_size(),
            )
            return _error_response(404, "Signed dataset không tồn tại hoặc đã hết hạn cache.", "SIGNED_DATASET_NOT_FOUND")
        logger.info(
            "Signed JSON cache hit: dataset_id=%s format=%s expires_at=%s tables=%s cache_size=%s",
            dataset_id,
            "json",
            cache_entry.get("expires_at"),
            cache_entry.get("available_tables", []),
            visualization_service.signed_dataset_cache_size(),
        )
        dataset = visualization_service.get_signed_dataset(dataset_id)
        if dataset is None:
            return _error_response(404, "Signed dataset không tồn tại hoặc đã hết hạn cache.", "SIGNED_DATASET_NOT_FOUND")

        return Response(
            content=dataset.model_dump_json(),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{dataset.symbol}_visualization.json"'},
        )
    except Exception as exc:
        return _error_response(500, f"Error serving visualization: {exc}", "VISUALIZATION_ERROR")


def _calculate_expiry(ttl_seconds: int) -> str:
    """Calculate and format expiry ISO datetime."""
    import time
    from datetime import datetime, timedelta, timezone

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    return expires_at.isoformat()


async def _resolve_current_user(user_token: str, identity_service: UserIdentityService):
    try:
        return await identity_service.resolve_current_user(user_token)
    except UserIdentityUnauthorizedError:
        return _error_response(401, "Phiên đăng nhập đã hết hạn hoặc token không hợp lệ.", "AUTH_INVALID")
    except UserIdentityMalformedError:
        return _error_response(502, "Không xác định được người dùng hiện tại từ Backend.", "CURRENT_USER_MALFORMED")
    except Exception:
        return _error_response(502, "Không xác thực được người dùng hiện tại từ Backend.", "CURRENT_USER_UNAVAILABLE")


def _status_code_from_result(result: dict | object) -> int:
    if not isinstance(result, dict):
        return 200
    try:
        return int(result.get("code", 200))
    except (TypeError, ValueError):
        return 200


def _visualization_chart_range(payload: AnalyseOneReportRequest, fallback: str) -> str:
    extra = getattr(payload.options, "model_extra", None) or {}
    raw = extra.get("chartRange") or extra.get("chart_range") or fallback
    clean = str(raw or fallback).strip().lower()
    return clean if clean in {"7d", "1m", "3m", "6m", "1y", "all"} else fallback


def _payload_report_id(payload: AnalyseOneReportRequest) -> str | None:
    extra = getattr(payload.options, "model_extra", None) or {}
    value = extra.get("report_id") or extra.get("reportId") or extra.get("history_report_id")
    clean = str(value or "").strip()
    return clean or None


def _load_or_build_visualization_dataset(
    *,
    detail,
    visualization_service: VisualizationDatasetService,
    chart_range: str | None = None,
):
    report_id = str(getattr(detail, "report_id", "") or "").strip()
    cache_started = time.perf_counter()
    logger.info("[visualization] cache_read_start report_id=%s", report_id)
    cached_dataset = visualization_service.load_visualization_json_file(report_id)
    logger.info("[visualization] cache_read_done report_id=%s hit=%s duration_ms=%s", report_id, bool(cached_dataset), _duration_ms(cache_started))
    if cached_dataset is not None:
        visualization_service.store_dataset_cache(cached_dataset, chart_range=chart_range)
        return cached_dataset, True, 0

    if not _has_report_data(detail.report_json):
        logger.warning("[visualization-data] failed status=422 code=MALFORMED_REPORT_DATA details=missing_root_data report_id=%s", report_id)
        return _error_response(422, "Dữ liệu báo cáo không đủ để tạo biểu đồ.", "MALFORMED_REPORT_DATA"), False, 0

    normalize_started = time.perf_counter()
    logger.info("[visualization-data] normalize_start report_id=%s", report_id)
    try:
        dataset = visualization_service.build_from_report_response(detail.report_json, chart_range=chart_range)
    except Exception:
        logger.exception("[visualization-data] failed status=422 code=MALFORMED_REPORT_DATA details=builder_failed report_id=%s", report_id)
        return _error_response(422, "Dữ liệu báo cáo không hợp lệ để tạo biểu đồ.", "MALFORMED_REPORT_DATA"), False, 0
    build_ms = _duration_ms(normalize_started)
    logger.info("[visualization-data] normalize_done report_id=%s duration_ms=%s", dataset.meta.source_report_id, build_ms)

    cache_write_started = time.perf_counter()
    logger.info("[visualization] cache_write_start report_id=%s", dataset.meta.source_report_id)
    visualization_service.store_dataset_cache(dataset, chart_range=chart_range)
    visualization_service.export_visualization_json_file(dataset)
    logger.info("[visualization] cache_write_done report_id=%s duration_ms=%s", dataset.meta.source_report_id, _duration_ms(cache_write_started))
    return dataset, False, build_ms


def _cache_visualization_from_current_report(
    *,
    result: dict | object,
    payload: AnalyseOneReportRequest,
    visualization_service: VisualizationDatasetService,
) -> None:
    if not isinstance(result, dict) or not _has_report_data(result):
        return
    if not visualization_service.settings.visualization_export_enabled:
        return
    chart_range = _visualization_chart_range(payload, visualization_service.settings.visualization_default_chart_range)
    try:
        started = time.perf_counter()
        dataset = visualization_service.build_from_report_response(result, chart_range=chart_range)
        visualization_service.store_dataset_cache(dataset, chart_range=chart_range)
        visualization_service.export_visualization_json_file(dataset)
        logger.info(
            "[visualization-data] warmed_cache report_id=%s symbol=%s exchange=%s chart_count=%s duration_ms=%s",
            dataset.meta.source_report_id,
            dataset.symbol,
            dataset.exchange,
            len((dataset.visualization or {}).get("charts") or []),
            _duration_ms(started),
        )
    except Exception:
        logger.warning(
            "[visualization-data] warm_cache_failed symbol=%s exchange=%s",
            payload.symbol,
            payload.scope_exchange,
            exc_info=True,
        )


def _visualization_response_data(dataset, *, cache_hit: bool, duration_ms: int) -> dict:
    data = dataset.model_dump(mode="json")
    visualization = data.get("visualization") if isinstance(data.get("visualization"), dict) else {}
    meta_val = visualization.get("meta")
    meta: dict = meta_val if isinstance(meta_val, dict) else {}
    meta["cache_hit"] = cache_hit
    meta["duration_ms"] = duration_ms
    visualization["meta"] = meta
    data["visualization"] = visualization
    return data


def _has_report_data(report_json: dict | object) -> bool:
    return isinstance(report_json, dict) and isinstance(report_json.get("data"), dict)


def _history_total(response_data: dict | object, data: object) -> int:
    if isinstance(response_data, dict):
        try:
            return int(response_data.get("total", 0))
        except (TypeError, ValueError):
            return 0
    try:
        return int(getattr(data, "total", 0))
    except (TypeError, ValueError):
        return 0


def _csv_file_response(
    *,
    visualization_service: VisualizationDatasetService,
    dataset,
    table: str,
    started: float,
    endpoint_name: str,
) -> Response:
    try:
        path = visualization_service.export_csv_file(dataset, table)
    except ValueError:
        return _error_response(404, "Không tìm thấy bảng visualization cần xuất CSV.", "VISUALIZATION_TABLE_NOT_FOUND")
    except Exception:
        logger.exception(
            "endpoint=%s report_id=%s symbol=%s exchange=%s table=%s failed_to_export_csv",
            endpoint_name,
            dataset.meta.source_report_id,
            dataset.symbol,
            dataset.exchange,
            table,
        )
        return _error_response(500, "Không thể tạo file CSV trực quan hóa.", "VISUALIZATION_CSV_EXPORT_FAILED")

    logger.info(
        "endpoint=%s cache=file report_id=%s symbol=%s exchange=%s table=%s duration_ms=%s export_file=%s",
        endpoint_name,
        dataset.meta.source_report_id,
        dataset.symbol,
        dataset.exchange,
        table,
        _duration_ms(started),
        path,
    )
    return FileResponse(
        path,
        media_type="text/csv; charset=utf-8",
        filename=path.name,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def _maybe_refresh_visualization_price_history(
    *,
    payload: AnalyseOneReportRequest,
    result: dict,
    user_token: str,
    report_service: ReportService,
    chart_range: str,
) -> None:
    backend_client = getattr(report_service, "backend_client", None)
    stock_data_service = getattr(report_service, "stock_data_service", None)
    if backend_client is None or stock_data_service is None:
        return
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    try:
        chart_payload = await backend_client.get_stock_chart(payload.symbol, range_value=chart_range, token=user_token)
        chart_rows = stock_data_service.normalize_stock_chart(chart_payload)
    except Exception:
        warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
        message = "Không tải thêm được price history cho visualization; dataset dùng price_history sẵn có trong report."
        if message not in warnings:
            warnings.append(message)
        data["warnings"] = warnings
        result["data"] = data
        return
    if chart_rows:
        summary["price_history"] = chart_rows
        coverage = summary.get("data_coverage") if isinstance(summary.get("data_coverage"), dict) else {}
        coverage["price_history_points"] = len(chart_rows)
        summary["data_coverage"] = coverage
        data["summary"] = summary
        result["data"] = data


def _error_response(status_code: int, message: str, error_type: str, details: list[dict] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=api_error(message, error_type, code=status_code, details=details))


def _not_implemented_response(message: str) -> JSONResponse:
    return _error_response(501, message, "NOT_IMPLEMENTED")
