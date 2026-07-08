"""
HoldingsAdviceService — Tầng 2 (Async, cache-aware) của Portfolio Analysis Popup.

Chiến lược:
- On-Demand + Same-Day Dedup (theo flow.md)
- asyncio.Semaphore(2) cho LLM calls — tránh burst
- Graceful degradation: LLM lỗi → trả P&L số + pnl_signal rule-based
- Timezone chuẩn: Asia/Ho_Chi_Minh cho mốc "today"
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from analyse.clients.backend_client import BackendClient
from analyse.config.settings import Settings, get_settings
from analyse.repositories.ai_report_history_repository import AiReportHistoryFilters
from analyse.research.research_service import ExternalResearchService
from analyse.schemas.holdings_advice import (
    HoldingAdviceItem,
    HoldingAdviceResult,
    HoldingAdviceReasoning,
    HoldingAdviceEvidence,
    HoldingAdviceCriterion,
    HoldingsAdviceRequest,
    HoldingsAdviceResponse,
)
from analyse.schemas.report import AnalyseOneReportRequest
from analyse.schemas.report_history import ReportHistoryFilters
from analyse.schemas.stock import AnalysisOptions
from analyse.schemas.research import ExternalResearchContext
from analyse.services.ai_report_history_service import (
    AiReportHistoryDisabledError,
    AiReportHistoryService,
    AiReportHistoryUnavailableError,
)
from analyse.services.report_service import ReportService
from analyse.services.user_identity_service import (
    CurrentUserIdentity,
    UserIdentityMalformedError,
    UserIdentityService,
    UserIdentityUnauthorizedError,
)
from analyse.utils.datetime_utils import now_iso
from analyse.utils.symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)

_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Rule-based P&L thresholds (graceful degradation khi LLM lỗi)
_STRONG_PROFIT_THRESHOLD = 15.0
_PROFIT_THRESHOLD = 5.0
_LOSS_WATCH_THRESHOLD = -5.0
_STRONG_LOSS_THRESHOLD = -15.0


def _today_start_vn() -> datetime:
    """Trả về 00:00:00 hôm nay theo Asia/Ho_Chi_Minh dưới dạng UTC-aware datetime."""
    now = datetime.now(_VN_TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today.astimezone(timezone.utc)


def _pnl_signal_from_pct(unrealized_pnl_pct: float | None) -> str:
    """
    Rule-based fallback signal dựa trên % P&L.
    Được dùng khi LLM lỗi hoặc không có lịch sử phân tích.
    """
    if unrealized_pnl_pct is None:
        return "NEUTRAL"
    if unrealized_pnl_pct >= _STRONG_PROFIT_THRESHOLD:
        return "STRONG_PROFIT_HOLD"
    if unrealized_pnl_pct >= _PROFIT_THRESHOLD:
        return "PROFIT_HOLD"
    if unrealized_pnl_pct <= _STRONG_LOSS_THRESHOLD:
        return "LOSS_REVIEW"
    if unrealized_pnl_pct <= _LOSS_WATCH_THRESHOLD:
        return "LOSS_WATCH"
    return "NEUTRAL"


def _extract_reasoning_from_report(report_json: dict[str, Any]) -> str | None:
    """Trích xuất tóm tắt lý do từ AI report JSON."""
    try:
        data = report_json.get("data") if isinstance(report_json, dict) else {}
        if not isinstance(data, dict):
            return None
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        system_decision = (
            summary.get("system_decision")
            if isinstance(summary.get("system_decision"), dict)
            else {}
        )
        # Ưu tiên: system_decision.reasons (danh sách lý do thực tế của AI) -> rationale -> reasoning -> note
        reasons_list = system_decision.get("reasons")
        if reasons_list and isinstance(reasons_list, list):
            clean_reasons = [str(r).strip() for r in reasons_list if str(r).strip()]
            # Loại bỏ disclaimer khỏi reasons nếu có lọt vào
            clean_reasons = [r for r in clean_reasons if "miễn trừ" not in r.lower() and "tham khảo" not in r.lower()]
            if clean_reasons:
                return "\n".join(clean_reasons)[:500]

        rationale = (
            system_decision.get("rationale")
            or system_decision.get("reasoning")
        )
        if rationale and str(rationale).strip():
            return str(rationale).strip()[:500]

        presentation = (
            summary.get("report_presentation")
            if isinstance(summary.get("report_presentation"), dict)
            else {}
        )
        summary_bar = (
            presentation.get("summary_bar")
            if isinstance(presentation.get("summary_bar"), dict)
            else {}
        )
        signal_label = summary_bar.get("signal_label") or summary_bar.get("decision_label")
        if signal_label:
            return str(signal_label).strip()[:300]
    except Exception:
        pass
    return None


class HoldingsAdviceService:
    """
    Orchestrates AI-powered portfolio advice với same-day dedup.

    Không kế thừa hay modify bất kỳ service cũ — chỉ import read-only.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        backend_client: BackendClient | None = None,
        report_service: ReportService | None = None,
        history_service: AiReportHistoryService | None = None,
        user_identity_service: UserIdentityService | None = None,
        research_service: ExternalResearchService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.backend_client = backend_client or BackendClient(self.settings)
        self.report_service = report_service
        self.history_service = history_service or AiReportHistoryService(self.settings)
        self.user_identity_service = user_identity_service or UserIdentityService(
            self.backend_client
        )
        self.research_service = research_service or ExternalResearchService(self.settings)

    async def generate_advice(
        self, request: HoldingsAdviceRequest, user_token: str
    ) -> dict[str, Any]:
        """
        Điểm vào chính:
        1. Resolve current_user từ token
        2. Batch process holdings với asyncio.Semaphore(2)
        3. Trả kết quả kể cả khi LLM lỗi (graceful degradation)
        """
        # Validate token
        if not str(user_token or "").strip():
            return self._error_response(401, "Missing Authorization header.", "AUTH_REQUIRED")

        # Resolve user
        try:
            current_user = await self.user_identity_service.resolve_current_user(user_token)
        except UserIdentityUnauthorizedError as exc:
            return self._error_response(
                401, "Phiên đăng nhập đã hết hạn hoặc token không hợp lệ.", "AUTH_INVALID"
            )
        except (UserIdentityMalformedError, Exception) as exc:
            return self._error_response(
                502,
                f"Không xác định được người dùng: {str(exc)[:100]}",
                "CURRENT_USER_UNAVAILABLE",
            )

        if not request.items:
            return self._success_response(
                HoldingsAdviceResponse(
                    generated_at=now_iso(self.settings.analyse_timezone),
                    advice=[],
                    total_items=0,
                )
            )

        # Semaphore = 2 để tránh burst LLM calls
        sem = asyncio.Semaphore(2)
        recent_start = datetime.now(timezone.utc) - timedelta(days=3)

        tasks = [
            self._process_one(
                item=item,
                current_user=current_user,
                user_token=user_token,
                sem=sem,
                recent_start=recent_start,
                force_refresh=request.force_refresh,
            )
            for item in request.items
        ]

        results: list[HoldingAdviceResult] = []
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, raw in enumerate(raw_results):
            if isinstance(raw, BaseException):
                item = request.items[i]
                logger.warning(
                    "[holdings-advice] unexpected error symbol=%s: %s",
                    item.symbol,
                    raw,
                    exc_info=False,
                )
                results.append(
                    self._build_fallback(item, error=str(raw)[:200])
                )
            else:
                results.append(raw)

        cached_count = sum(1 for r in results if r.source == "cache")
        generated_count = sum(1 for r in results if r.source == "generated")
        fallback_count = sum(1 for r in results if r.source == "fallback")

        response = HoldingsAdviceResponse(
            generated_at=now_iso(self.settings.analyse_timezone),
            advice=results,
            total_items=len(results),
            cached_count=cached_count,
            generated_count=generated_count,
            fallback_count=fallback_count,
        )
        return self._success_response(response)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _process_one(
        self,
        *,
        item: HoldingAdviceItem,
        current_user: CurrentUserIdentity,
        user_token: str,
        sem: asyncio.Semaphore,
        recent_start: datetime,
        force_refresh: bool,
    ) -> HoldingAdviceResult:
        """
        Xử lý một holding:
        1. Same-day dedup check (không tốn LLM)
        2. HIT → trả cached (có gọi detail load full report_json & collect evidence)
        3. MISS → gọi LLM với P&L context (dưới semaphore)
        4. Lỗi → graceful degradation (fallback rule-based)
        """
        symbol = normalize_symbol(item.symbol)
        exchange = str(item.exchange or "HOSE").strip().upper()
        logger.info(
            "[holdings-advice] processing symbol=%s exchange=%s force_refresh=%s",
            symbol,
            exchange,
            force_refresh,
        )

        # ── 1. Same-day dedup check ──────────────────────────────────────
        if not force_refresh:
            cached = await self._check_recent_cache(
                current_user=current_user,
                symbol=symbol,
                exchange=exchange,
                recent_start=recent_start,
            )
            if cached is not None:
                logger.info("[holdings-advice] cache=HIT symbol=%s", symbol)
                report_json = None
                try:
                    detail = await self.history_service.get_history_detail(
                        current_user=current_user,
                        history_id=cached.id
                    )
                    report_json = detail.report_json
                except Exception as exc:
                    logger.warning("[holdings-advice] failed to load cache detail for symbol=%s: %s", symbol, exc)
                
                evidence = await self._collect_evidence(
                    symbol=symbol,
                    exchange=exchange,
                    item=item,
                    report_json=report_json,
                    user_token=user_token,
                )
                return self._build_from_cache(item, cached, report_json, evidence)

        # ── 2. Generate fresh (under semaphore) ──────────────────────────
        logger.info("[holdings-advice] cache=MISS symbol=%s → calling LLM", symbol)
        async with sem:
            return await self._generate_fresh(
                item=item,
                symbol=symbol,
                exchange=exchange,
                user_token=user_token,
            )

    async def _check_recent_cache(
        self,
        *,
        current_user: CurrentUserIdentity,
        symbol: str,
        exchange: str,
        recent_start: datetime,
    ) -> Any | None:
        """
        Kiểm tra xem đã có báo cáo AI cho mã này hôm nay chưa.
        Trả về row (history item) nếu cache HIT, None nếu MISS.
        """
        try:
            result = await self.history_service.list_history(
                current_user=current_user,
                filters=ReportHistoryFilters(
                    symbol=symbol,
                    exchange=exchange,
                    fromDate=recent_start,
                    page=1,
                    limit=1,
                ),
            )
            if result.total > 0 and result.items:
                return result.items[0]
        except (AiReportHistoryDisabledError, AiReportHistoryUnavailableError):
            # History disabled/unavailable → bỏ qua, tiến hành generate
            logger.debug("[holdings-advice] history unavailable for dedup check symbol=%s", symbol)
        except Exception as exc:
            logger.warning(
                "[holdings-advice] dedup check error symbol=%s: %s", symbol, exc
            )
        return None

    async def _generate_fresh(
        self,
        *,
        item: HoldingAdviceItem,
        symbol: str,
        exchange: str,
        user_token: str,
    ) -> HoldingAdviceResult:
        """
        Gọi report_service.analyse_one_report() với P&L context inject.
        Nếu LLM lỗi → graceful degradation (fallback rule-based).
        """
        try:
            if self.report_service is None:
                raise RuntimeError("ReportService chưa được inject vào HoldingsAdviceService.")

            # Build P&L context để inject vào AnalysisOptions (extra="allow")
            pnl_context = {
                "average_cost": item.average_cost,
                "quantity": item.quantity,
                "close_price": item.close_price,
                "market_value": item.market_value,
                "cost": item.cost,
                "unrealized_pnl": item.unrealized_pnl,
                "unrealized_pnl_pct": item.unrealized_pnl_pct,
                "status": item.status,
                "company_name": item.company_name,
            }

            payload = AnalyseOneReportRequest(
                symbol=symbol,
                scope_exchange=exchange,
                options=AnalysisOptions(
                    render_markdown=True,
                    render_html=True,
                    include_external_research=False,  # Tắt external research để nhanh hơn
                    pnl_context=pnl_context,  # extra="allow" → pass thẳng
                ),
            )

            report = await self.report_service.analyse_one_report(
                payload, user_token=user_token
            )

            evidence = await self._collect_evidence(
                symbol=symbol,
                exchange=exchange,
                item=item,
                report_json=report,
                user_token=user_token,
            )

            # Extract decision + scores từ report response
            return self._build_from_report(item, report, evidence, source="generated")

        except Exception as exc:
            logger.warning(
                "[holdings-advice] LLM error symbol=%s → fallback. error=%s",
                symbol,
                str(exc)[:200],
            )
            evidence = await self._collect_evidence(
                symbol=symbol,
                exchange=exchange,
                item=item,
                report_json=None,
                user_token=user_token,
            )
            return self._build_fallback(item, evidence, error=str(exc)[:200])

    def _parse_iso(self, iso_str: str | None) -> datetime | None:
        if not iso_str:
            return None
        try:
            clean_str = iso_str.strip()
            if clean_str.endswith("Z"):
                clean_str = clean_str[:-1] + "+00:00"
            return datetime.fromisoformat(clean_str)
        except Exception:
            return None

    def _dedupe_evidence(self, evidence_list: list[HoldingAdviceEvidence]) -> list[HoldingAdviceEvidence]:
        seen = set()
        deduped = []
        for ev in evidence_list:
            key = (ev.source, ev.source_url or "", ev.metric_name.strip().lower(), str(ev.value).strip().lower())
            if key not in seen:
                seen.add(key)
                deduped.append(ev)
        return deduped

    def _evidence_from_chart_7d(self, chart: dict | list | None, item: HoldingAdviceItem) -> list[HoldingAdviceEvidence]:
        if not chart:
            return []
        
        days = []
        if isinstance(chart, dict):
            days = chart.get("data") or []
        elif isinstance(chart, list):
            days = chart
        
        if not isinstance(days, list) or not days:
            return []
            
        close_prices = []
        volumes = []
        dates = []
        
        for d in days:
            if not isinstance(d, dict):
                continue
            close = d.get("close") or d.get("close_price")
            vol = d.get("volume") or d.get("total_volume")
            t = d.get("time") or d.get("date")
            
            if close is not None:
                try:
                    close_prices.append(float(close))
                except (ValueError, TypeError):
                    pass
            if vol is not None:
                try:
                    volumes.append(float(vol))
                except (ValueError, TypeError):
                    pass
            if t:
                dates.append(str(t))
                
        if not close_prices:
            return []
            
        latest_date = dates[-1] if dates else None
        
        evidence = []
        highest = max(close_prices)
        lowest = min(close_prices)
        
        evidence.append(HoldingAdviceEvidence(
            metric_name="Giá cao nhất 7 ngày",
            value=highest,
            unit="VND",
            source="backend_price",
            source_url=None,
            published_at=latest_date,
            note="7 ngày qua"
        ))
        evidence.append(HoldingAdviceEvidence(
            metric_name="Giá thấp nhất 7 ngày",
            value=lowest,
            unit="VND",
            source="backend_price",
            source_url=None,
            published_at=latest_date,
            note="7 ngày qua"
        ))
        
        if len(close_prices) > 1 and close_prices[0] != 0:
            change_pct = (close_prices[-1] - close_prices[0]) / close_prices[0] * 100
            evidence.append(HoldingAdviceEvidence(
                metric_name="Biến động giá 7 ngày",
                value=f"{change_pct:+.2f}%",
                unit="%",
                source="backend_price",
                source_url=None,
                published_at=latest_date,
                note="7 ngày qua"
            ))
            
        if volumes:
            avg_vol = sum(volumes) / len(volumes)
            evidence.append(HoldingAdviceEvidence(
                metric_name="Khối lượng GD TB 7 ngày",
                value=int(avg_vol),
                unit="cổ phiếu",
                source="backend_price",
                source_url=None,
                published_at=latest_date,
                note="7 ngày qua"
            ))
            
        evidence.append(HoldingAdviceEvidence(
            metric_name="Giá đóng cửa gần nhất",
            value=close_prices[-1],
            unit="VND",
            source="backend_price",
            source_url=None,
            published_at=latest_date,
            note="Cập nhật gần nhất"
        ))
        
        return evidence

    def _evidence_from_report_json(self, report_json: dict | None) -> list[HoldingAdviceEvidence]:
        if not report_json or not isinstance(report_json, dict):
            return []
            
        evidence = []
        data = report_json.get("data") or {}
        summary = data.get("summary") or report_json.get("summary") or {}
        
        # 1. BCTC
        bctc = summary.get("bctc_3q") or summary.get("financials_merged") or {}
        periods = bctc.get("periods") or []
        if periods and isinstance(periods, list):
            latest = periods[0]
            q = latest.get("quarter")
            y = latest.get("year")
            period_str = f"Q{q}/{y}" if q and y else "kỳ gần nhất"
            source = "history_bctc"
            
            rev = latest.get("revenue")
            profit = latest.get("profit_after_tax") or latest.get("parent_profit")
            
            if rev is not None:
                evidence.append(HoldingAdviceEvidence(
                    metric_name=f"Doanh thu {period_str}",
                    value=rev,
                    unit="triệu VND",
                    source=source,
                    source_url=None,
                    published_at=None,
                    note="Báo cáo tài chính"
                ))
            if profit is not None:
                evidence.append(HoldingAdviceEvidence(
                    metric_name=f"Lợi nhuận sau thuế {period_str}",
                    value=profit,
                    unit="triệu VND",
                    source=source,
                    source_url=None,
                    published_at=None,
                    note="Báo cáo tài chính"
                ))
                
        # 2. Latest market
        latest_market = summary.get("latest_market") or {}
        if latest_market:
            source = "history_market"
            for key, name, unit in [("pe", "P/E", None), ("pb", "P/B", None), ("roe", "ROE", "%"), ("eps", "EPS", "VND")]:
                val = latest_market.get(key)
                if val is not None:
                    evidence.append(HoldingAdviceEvidence(
                        metric_name=name,
                        value=val,
                        unit=unit,
                        source=source,
                        source_url=None,
                        published_at=None,
                        note="Dữ liệu thị trường"
                    ))
                    
        # 3. Peer context
        peers = summary.get("industry_peer_context", {}).get("peers") or []
        if peers and isinstance(peers, list):
            source = "history_peer"
            for p in peers[:3]:
                sym = p.get("symbol")
                if not sym:
                    continue
                pe_p = p.get("pe")
                pb_p = p.get("pb")
                if pe_p is not None:
                    evidence.append(HoldingAdviceEvidence(
                        metric_name=f"P/E đối thủ {sym}",
                        value=pe_p,
                        unit=None,
                        source=source,
                        source_url=None,
                        published_at=None,
                        note="So sánh cùng ngành"
                    ))
                if pb_p is not None:
                    evidence.append(HoldingAdviceEvidence(
                        metric_name=f"P/B đối thủ {sym}",
                        value=pb_p,
                        unit=None,
                        source=source,
                        source_url=None,
                        published_at=None,
                        note="So sánh cùng ngành"
                    ))
                    
        # 4. Hose market context
        hose = summary.get("hose_market_context") or {}
        if hose:
            source = "history_hose"
            vnindex = hose.get("vnindex") or hose.get("vnindex_close")
            change = hose.get("change_percent") or hose.get("change_pct")
            if vnindex is not None:
                evidence.append(HoldingAdviceEvidence(
                    metric_name="Chỉ số VN-Index",
                    value=vnindex,
                    unit=None,
                    source=source,
                    source_url=None,
                    published_at=None,
                    note="Bối cảnh thị trường"
                ))
            if change is not None:
                evidence.append(HoldingAdviceEvidence(
                    metric_name="Biến động VN-Index",
                    value=f"{change:+.2f}%",
                    unit="%",
                    source=source,
                    source_url=None,
                    published_at=None,
                    note="Bối cảnh thị trường"
                ))
                
        # 5. Evidence table from LLM / evidence_pool (if exists)
        ev_table = summary.get("evidence_table") or report_json.get("evidence_table") or report_json.get("evidence_pool") or summary.get("evidence_pool") or []
        if ev_table and isinstance(ev_table, list):
            for raw_ev in ev_table:
                if not isinstance(raw_ev, dict):
                    continue
                try:
                    metric = raw_ev.get("metric_name") or raw_ev.get("metric")
                    val = raw_ev.get("value")
                    src = raw_ev.get("source")
                    if metric and val is not None and src:
                        evidence.append(HoldingAdviceEvidence(
                            metric_name=str(metric),
                            value=val,
                            unit=raw_ev.get("unit"),
                            source=src,
                            source_url=raw_ev.get("source_url") or raw_ev.get("sourceUrl"),
                            published_at=raw_ev.get("published_at") or raw_ev.get("publishedAt"),
                            note=raw_ev.get("note")
                        ))
                except Exception:
                    pass
                    
        return evidence

    def _evidence_from_research(self, ctx: ExternalResearchContext, symbol: str) -> list[HoldingAdviceEvidence]:
        if not ctx or not ctx.items:
            return []
            
        evidence = []
        valid_items = []
        now = datetime.now(timezone.utc)
        
        for item in ctx.items:
            relevance = item.relevance_score if item.relevance_score is not None else 1.0
            if relevance < 0.4:
                continue
                
            if not item.url:
                continue
                
            pub_date = self._parse_iso(item.published_at)
            if pub_date:
                days_age = (now - pub_date).days
                if days_age > 14:
                    continue
                    
            valid_items.append(item)
            
        valid_items = sorted(valid_items, key=lambda x: x.relevance_score or 0.0, reverse=True)[:3]
        
        for item in valid_items:
            source_str = (item.source or "").lower()
            url_str = (item.url or "").lower()
            if "cafef" in source_str or "cafef" in url_str:
                source_val = "cafef_news"
            elif "vietstock" in source_str or "vietstock" in url_str:
                source_val = "vietstock_news"
            else:
                source_val = "google_news"
                
            evidence.append(HoldingAdviceEvidence(
                metric_name=f"Tin tức: {item.title[:60] if item.title else 'News'}",
                value=item.snippet[:120] if item.snippet else (item.tone or "Tin tức thị trường"),
                unit=None,
                source=source_val,
                source_url=item.url,
                published_at=item.published_at,
                note=f"Độ tin cậy: {item.relevance_score or 1.0}"
            ))
            
        return evidence

    async def _collect_evidence(
        self,
        *,
        symbol: str,
        exchange: str,
        item: HoldingAdviceItem,
        report_json: dict | None,
        user_token: str,
    ) -> list[HoldingAdviceEvidence]:
        evidence: list[HoldingAdviceEvidence] = []
        
        # Nguồn 1 — 7 ngày giá từ backend
        try:
            chart = await self.backend_client.get_stock_chart(symbol, "7d", token=user_token)
            evidence.extend(self._evidence_from_chart_7d(chart, item))
        except Exception as exc:
            logger.warning("[holdings-advice] chart 7d failed symbol=%s: %s", symbol, exc)
            
        # Nguồn 2 — history trong ngày (report_json)
        if report_json:
            evidence.extend(self._evidence_from_report_json(report_json))
            
        # Nguồn 3 — external research
        if self.settings.enable_external_research:
            try:
                ctx = await self.research_service.search(symbol, item.company_name)
                evidence.extend(self._evidence_from_research(ctx, symbol))
            except Exception as exc:
                logger.warning("[holdings-advice] research failed symbol=%s: %s", symbol, exc)
                
        return self._dedupe_evidence(evidence)

    def _build_from_cache(
        self, item: HoldingAdviceItem, cache_row: Any, report_json: dict | None = None, evidence: list[HoldingAdviceEvidence] | None = None
    ) -> HoldingAdviceResult:
        """Xây dựng kết quả từ cached history row (đã phân tích hôm nay)."""
        pnl_signal = _pnl_signal_from_pct(item.unrealized_pnl_pct)

        # Trích decision_label từ row
        decision = str(cache_row.decision_label or "").strip() or None
        if decision and decision.upper() in {"BUY", "SELL", "HOLD", "WATCH"}:
            decision = decision.upper()
        else:
            decision = self._pnl_to_decision(pnl_signal)

        analysed_at = None
        try:
            if hasattr(cache_row, "created_at") and cache_row.created_at:
                analysed_at = cache_row.created_at.isoformat() if hasattr(
                    cache_row.created_at, "isoformat"
                ) else str(cache_row.created_at)
        except Exception:
            pass

        reasoning = None
        reasons_list = []
        summary = {}
        if report_json is None:
            try:
                if hasattr(cache_row, "report_json") and cache_row.report_json:
                    raw = cache_row.report_json
                    report_json = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                pass
                
        if report_json:
            try:
                reasoning = _extract_reasoning_from_report(report_json)
                data = report_json.get("data") or {}
                summary = data.get("summary") or {}
                system_decision = summary.get("system_decision") or {}
                reasons_list = system_decision.get("reasons") or []
            except Exception:
                pass

        # Xây dựng skeleton lý do cấu trúc
        skeleton = self._build_reasoning_skeleton(
            item=item,
            reasons=reasons_list,
            summary=summary if summary else None,
            decision=decision,
            evidence=evidence,
        )

        report_id = getattr(cache_row, "report_id", None)
        if not report_id and report_json:
            report_id = report_json.get("data", {}).get("report_id") or report_json.get("report_id")

        return HoldingAdviceResult(
            symbol=item.symbol,
            exchange=item.exchange,
            company_name=item.company_name,
            average_cost=item.average_cost,
            quantity=item.quantity,
            close_price=item.close_price,
            unrealized_pnl=item.unrealized_pnl,
            unrealized_pnl_pct=item.unrealized_pnl_pct,
            status=item.status,
            decision=decision,
            pnl_signal=pnl_signal,
            total_score=getattr(cache_row, "total_score", None),
            risk_score=getattr(cache_row, "risk_score", None),
            data_confidence=getattr(cache_row, "data_confidence", None),
            reasoning=reasoning,
            reasoning_skeleton=skeleton,
            source="cache",
            report_id=report_id,
            analysed_at=analysed_at,
            error=None,
        )

    def _build_from_report(
        self,
        item: HoldingAdviceItem,
        report: dict[str, Any],
        evidence: list[HoldingAdviceEvidence] | None = None,
        source: str = "generated",
    ) -> HoldingAdviceResult:
        """Xây dựng kết quả từ fresh LLM report response."""
        pnl_signal = _pnl_signal_from_pct(item.unrealized_pnl_pct)

        data = report.get("data") if isinstance(report.get("data"), dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        scores = summary.get("scores") if isinstance(summary.get("scores"), dict) else {}
        system_decision = (
            summary.get("system_decision")
            if isinstance(summary.get("system_decision"), dict)
            else {}
        )

        decision_label = str(system_decision.get("status") or "").strip().upper() or None
        if decision_label not in {"BUY", "SELL", "HOLD", "WATCH"}:
            decision_label = self._pnl_to_decision(pnl_signal)

        total_score = self._safe_float(scores.get("overall_score"))
        risk_score = self._safe_float(scores.get("risk_score"))
        data_confidence = self._safe_float(
            scores.get("score_confidence_normalized")
            or scores.get("data_confidence")
        )
        reasoning = _extract_reasoning_from_report(report)
        generated_at = str(data.get("generated_at") or "")
        
        reasons_list = system_decision.get("reasons") or []

        # Xây dựng skeleton lý do cấu trúc
        skeleton = self._build_reasoning_skeleton(
            item=item,
            reasons=reasons_list,
            summary=summary,
            decision=decision_label,
            evidence=evidence,
        )

        report_id = data.get("report_id")

        return HoldingAdviceResult(
            symbol=item.symbol,
            exchange=item.exchange,
            company_name=item.company_name,
            average_cost=item.average_cost,
            quantity=item.quantity,
            close_price=item.close_price,
            unrealized_pnl=item.unrealized_pnl,
            unrealized_pnl_pct=item.unrealized_pnl_pct,
            status=item.status,
            decision=decision_label,
            pnl_signal=pnl_signal,
            total_score=total_score,
            risk_score=risk_score,
            data_confidence=data_confidence,
            reasoning=reasoning,
            reasoning_skeleton=skeleton,
            source=source,  # type: ignore[arg-type]
            report_id=report_id,
            analysed_at=generated_at or now_iso(self.settings.analyse_timezone),
            error=None,
        )

    def _build_fallback(
        self, item: HoldingAdviceItem, evidence: list[HoldingAdviceEvidence] | None = None, error: str | None = None
    ) -> HoldingAdviceResult:
        """Graceful degradation: LLM lỗi → trả P&L số + rule-based signal."""
        pnl_signal = _pnl_signal_from_pct(item.unrealized_pnl_pct)
        decision = self._pnl_to_decision(pnl_signal)
        
        # Xây dựng skeleton lý do cấu trúc cho fallback
        skeleton = self._build_reasoning_skeleton(
            item=item,
            reasons=None,
            summary=None,
            decision=decision,
            evidence=evidence,
        )

        return HoldingAdviceResult(
            symbol=item.symbol,
            exchange=item.exchange,
            company_name=item.company_name,
            average_cost=item.average_cost,
            quantity=item.quantity,
            close_price=item.close_price,
            unrealized_pnl=item.unrealized_pnl,
            unrealized_pnl_pct=item.unrealized_pnl_pct,
            status=item.status,
            decision=decision,
            pnl_signal=pnl_signal,
            total_score=None,
            risk_score=None,
            data_confidence=None,
            reasoning=f"Phân tích rule-based dựa trên P&L {item.unrealized_pnl_pct:+.2f}%. AI report không khả dụng."
            if item.unrealized_pnl_pct is not None
            else "Phân tích rule-based. AI report không khả dụng.",
            reasoning_skeleton=skeleton,
            source="fallback",
            analysed_at=now_iso(self.settings.analyse_timezone),
            error=error,
        )

    def _build_reasoning_skeleton(
        self,
        *,
        item: HoldingAdviceItem,
        reasons: list[str] | None,
        summary: dict[str, Any] | None,
        decision: str,
        evidence: list[HoldingAdviceEvidence] | None = None,
    ) -> HoldingAdviceReasoning:
        """
        Xây dựng cấu trúc giải thích 5 tiêu chí chuẩn hóa từ reasons của AI hoặc tự sinh
        dựa trên số liệu P&L và BCTC có sẵn, kèm theo structured evidence.
        """
        # 1. Mặc định tự sinh dựa trên giá trị P&L thực tế
        avg_cost = item.average_cost
        close = item.close_price or 0.0
        pnl_pct = item.unrealized_pnl_pct or 0.0
        pnl_vnd = item.unrealized_pnl or 0.0
        qty = item.quantity or 0
        status_text = "lãi" if item.status == "PROFIT" else "lỗ"

        portfolio_fit = (
            f"Vị thế giá vốn trung bình {avg_cost:,.0f} VND đối với {item.symbol} "
            f"(số lượng {qty:,} CP, giá khớp gần nhất {close:,.0f} VND) đang tạm {status_text} "
            f"{pnl_pct:+.2f}% (tương đương {pnl_vnd:+,.0f} VND) theo dữ liệu danh mục đã xác thực."
        )

        # 2. Mặc định Sức khỏe tài chính
        financial_health = "Báo cáo tài chính gần nhất cho thấy sức khỏe tài chính ổn định, doanh thu/lợi nhuận đang đi ngang tích lũy."
        if summary:
            periods = summary.get("bctc_3q", {}).get("periods") or summary.get("financials_merged", {}).get("periods") or []
            if periods and isinstance(periods, list):
                latest = periods[0]
                q = latest.get("quarter")
                y = latest.get("year")
                period_str = f"Q{q}/{y}" if q and y else "kỳ gần nhất"
                rev = latest.get("revenue")
                profit = latest.get("profit_after_tax") or latest.get("parent_profit")
                
                rev_str = f"doanh thu {self._format_bil_or_mil_vnd(rev)}" if isinstance(rev, (int, float)) and abs(rev) >= 1.0 else ""
                profit_str = f"LNST {self._format_bil_or_mil_vnd(profit)}" if isinstance(profit, (int, float)) and abs(profit) >= 1.0 else ""
                
                parts = [p for p in [rev_str, profit_str] if p]
                if parts:
                    financial_health = f"Báo cáo tài chính {period_str} ghi nhận " + " và ".join(parts) + "."
                    if len(periods) > 1:
                        prev = periods[1]
                        prev_profit = prev.get("profit_after_tax") or prev.get("parent_profit")
                        if isinstance(profit, (int, float)) and isinstance(prev_profit, (int, float)) and prev_profit:
                            change = round((profit - prev_profit) / abs(prev_profit) * 100, 1)
                            financial_health += f" Lợi nhuận sau thuế thay đổi {change:+.1f}% so với kỳ liền trước."
            else:
                strengths = summary.get("strengths") or []
                health_strengths = [s for s in strengths if any(k in s.lower() for k in ["lợi nhuận", "doanh thu", "tăng trưởng", "bctc", "biên"])]
                if health_strengths:
                    financial_health = health_strengths[0]

        # 3. Mặc định Định giá & Đối thủ
        valuation_peer = "Chỉ số định giá P/E và P/B của doanh nghiệp đang nằm trong vùng hợp lý so với các đối thủ cạnh tranh cùng ngành."
        if summary:
            latest_market = summary.get("latest_market", {})
            pe = latest_market.get("pe")
            pb = latest_market.get("pb")
            roe = latest_market.get("roe")
            val_parts = []
            if isinstance(pe, (int, float)):
                val_parts.append(f"P/E là {pe:.2f}")
            if isinstance(pb, (int, float)):
                val_parts.append(f"P/B là {pb:.2f}")
            if isinstance(roe, (int, float)):
                val_parts.append(f"ROE đạt {roe:.1f}%")
            
            peer_text = ""
            peers = summary.get("industry_peer_context", {}).get("peers", [])
            if peers and isinstance(peers, list):
                valid_peers = [p for p in peers if p.get("symbol") != item.symbol]
                if valid_peers:
                    peer_names = ", ".join([p.get("symbol") for p in valid_peers[:3]])
                    peer_text = f" so với các đối thủ cùng ngành ({peer_names})"
            
            if val_parts:
                valuation_peer = f"Chỉ số định giá ({', '.join(val_parts)}){peer_text} đang ở mức hợp lý."
            else:
                weaknesses = summary.get("weaknesses") or []
                valuation_weaknesses = [w for w in weaknesses if any(k in w.lower() for k in ["định giá", "p/e", "p/b", "đắt", "cao"])]
                if valuation_weaknesses:
                    valuation_peer = valuation_weaknesses[0]

        # 4. Mặc định Xu hướng & Thị trường
        market_momentum = "Xu hướng kỹ thuật ngắn hạn của cổ phiếu đang trong trạng thái tích lũy; thị trường chung đang phân hóa."
        if summary:
            latest_market = summary.get("latest_market", {})
            change_pct = latest_market.get("change_pct") or latest_market.get("change_percent")
            if change_pct is None:
                momentum = summary.get("momentum") or {}
                change_pct = momentum.get("change_pct") or momentum.get("change_1d_percent")
            
            price = latest_market.get("close_price") or latest_market.get("price") or item.close_price or 0.0
            
            market_info = ""
            hose_market = summary.get("hose_market_context", {})
            vnindex = hose_market.get("vnindex") or hose_market.get("vnindex_close")
            if isinstance(vnindex, (int, float)):
                market_info = f", trong khi chỉ số VN-Index đóng cửa ở mức {vnindex:,.1f}"
                
            if isinstance(change_pct, (int, float)):
                trend_dir = "tăng" if change_pct > 0 else "giảm"
                market_momentum = f"Biến động giá gần nhất là {change_pct:+.2f}% (xu hướng {trend_dir}), giá khớp {price:,.0f} VND/cổ phiếu{market_info}."

        # 5. Mặc định Kế hoạch hành động
        action_plan = f"Hành động đề xuất: {decision}. Cần quản trị rủi ro chặt chẽ, tuân thủ nguyên tắc cắt lỗ/chốt lời chủ động."
        if summary:
            plan_data = summary.get("action_plan") or {}
            short_term_actions = plan_data.get("short_term") or []
            price_levels = []
            for item_act in short_term_actions:
                if isinstance(item_act, dict) and item_act.get("price_zone"):
                    price_levels.append(str(item_act.get("price_zone")))
            if not price_levels:
                risk_items = plan_data.get("risk_management") or []
                for item_act in risk_items:
                    if isinstance(item_act, dict) and item_act.get("price_zone"):
                        price_levels.append(str(item_act.get("price_zone")))
            
            price_zone_str = ""
            if price_levels:
                price_zone_str = f" với vùng giá quan sát/hành động {', '.join(price_levels)}"
            
            if decision == "BUY":
                action_plan = f"Khuyến nghị MUA{price_zone_str}. Vùng giá hiện tại thuận lợi để tích lũy thêm cổ phiếu theo kế hoạch."
            elif decision == "SELL":
                action_plan = f"Khuyến nghị BÁN{price_zone_str}. Cân nhắc giảm bớt tỷ trọng để bảo toàn danh mục."
            elif decision == "HOLD":
                action_plan = f"Khuyến nghị GIỮ{price_zone_str}. Tiếp tục nắm giữ cổ phiếu để theo dõi xu hướng tiếp theo."
        else:
            if decision == "BUY":
                action_plan = "Khuyến nghị MUA: Vùng giá hiện tại thuận lợi để tích lũy thêm cổ phiếu theo kế hoạch."
            elif decision == "SELL":
                action_plan = "Khuyến nghị BÁN: Cân nhắc giảm bớt tỷ trọng để bảo toàn danh mục."
            elif decision == "HOLD":
                action_plan = "Khuyến nghị GIỮ: Tiếp tục nắm giữ cổ phiếu để theo dõi xu hướng tiếp theo."

        # Parse từ mảng reasons của AI nếu có định dạng chuẩn
        if reasons and isinstance(reasons, list):
            for r in reasons:
                r_str = str(r).strip()
                clean_r = re.sub(r"^[\s*\d\.\-]*", "", r_str)

                if any(clean_r.upper().startswith(prefix) for prefix in ["VỊ THẾ GIÁ VỐN:", "VỊ THẾ:"]):
                    portfolio_fit = clean_r
                elif any(clean_r.upper().startswith(prefix) for prefix in ["SỨC KHỎE TÀI CHÍNH:", "TÀI CHÍNH:"]):
                    financial_health = clean_r
                elif any(clean_r.upper().startswith(prefix) for prefix in ["ĐỊNH GIÁ & ĐỐI THỦ:", "ĐỊNH GIÁ:", "ĐỐI THỦ:"]):
                    valuation_peer = clean_r
                elif any(clean_r.upper().startswith(prefix) for prefix in ["XU HƯỚNG & THỊ TRƯỜNG:", "XU HƯỚNG:", "THỊ TRƯỜNG:"]):
                    market_momentum = clean_r
                elif any(clean_r.upper().startswith(prefix) for prefix in ["NGUYÊN TẮC HÀNH ĐỘNG:", "HÀNH ĐỘNG:", "NGUYÊN TẮC:"]):
                    action_plan = clean_r
                elif len(reasons) == 5:
                    idx = reasons.index(r)
                    if idx == 0:
                        portfolio_fit = r_str
                    elif idx == 1:
                        financial_health = r_str
                    elif idx == 2:
                        valuation_peer = r_str
                    elif idx == 3:
                        market_momentum = r_str
                    elif idx == 4:
                        action_plan = r_str

        # Phân nhóm evidence cho 5 tiêu chí
        fit_ev = []
        health_ev = []
        val_ev = []
        mom_ev = []
        act_ev = []
        
        # Tạo sẵn purchase context evidence
        fit_ev.append(HoldingAdviceEvidence(
            metric_name="Giá vốn trung bình",
            value=item.average_cost,
            unit="VND",
            source="backend_price",
            note="Danh mục đầu tư"
        ))
        fit_ev.append(HoldingAdviceEvidence(
            metric_name="Số lượng nắm giữ",
            value=item.quantity,
            unit="cổ phiếu",
            source="backend_price",
            note="Danh mục đầu tư"
        ))
        if item.unrealized_pnl_pct is not None:
            fit_ev.append(HoldingAdviceEvidence(
                metric_name="Lãi/lỗ tạm tính",
                value=f"{item.unrealized_pnl_pct:+.2f}%",
                unit="%",
                source="backend_price",
                note="Danh mục đầu tư"
            ))

        if evidence:
            for ev in evidence:
                if ev.source == "backend_price":
                    if "giá" in ev.metric_name.lower() or "biến động" in ev.metric_name.lower():
                        mom_ev.append(ev)
                elif ev.source in {"history_bctc", "cafef_news", "vietstock_news"}:
                    health_ev.append(ev)
                elif ev.source in {"history_market", "history_peer"}:
                    val_ev.append(ev)
                elif ev.source in {"history_hose"}:
                    mom_ev.append(ev)
                elif ev.source in {"google_news"}:
                    # Phân bổ news chung vào health hoặc momentum tùy keyword
                    if any(k in ev.metric_name.lower() for k in ["lợi nhuận", "doanh thu", "bctc", "tài chính"]):
                        health_ev.append(ev)
                    else:
                        mom_ev.append(ev)

        # Xây dựng vùng giá cho action plan evidence
        if summary:
            plan_data = summary.get("action_plan") or {}
            short_term_actions = plan_data.get("short_term") or []
            for item_act in short_term_actions:
                if isinstance(item_act, dict):
                    pz_val = item_act.get("price_zone")
                    # Kiểm tra xem có chứa chữ số không (nếu là chữ thô kiểu "Vùng giá hiện tại" hoặc None -> return None)
                    is_specific = False
                    if pz_val is not None:
                        is_specific = any(char.isdigit() for char in str(pz_val))
                    
                    act_ev.append(HoldingAdviceEvidence(
                        metric_name=item_act.get("action") or "Hành động ngắn hạn",
                        value=str(pz_val) if is_specific else None,
                        unit="VND" if is_specific else None,
                        source="history_market",
                        note=item_act.get("price_zone_note") or ("Vùng giá ngắn hạn" if is_specific else "Không có vùng giá cụ thể")
                    ))

        # Giới hạn tối đa 5 evidence mỗi criterion
        criteria_list = [
            HoldingAdviceCriterion(title="Vị thế giá vốn", verdict=portfolio_fit, evidence=fit_ev[:5]),
            HoldingAdviceCriterion(title="Sức khỏe tài chính", verdict=financial_health, evidence=health_ev[:5]),
            HoldingAdviceCriterion(title="Định giá & Đối thủ", verdict=valuation_peer, evidence=val_ev[:5]),
            HoldingAdviceCriterion(title="Xu hướng & Thị trường", verdict=market_momentum, evidence=mom_ev[:5]),
            HoldingAdviceCriterion(title="Kế hoạch hành động", verdict=action_plan, evidence=act_ev[:5]),
        ]

        # gom all evidence pool
        pool = []
        pool.extend(fit_ev)
        pool.extend(health_ev)
        pool.extend(val_ev)
        pool.extend(mom_ev)
        pool.extend(act_ev)
        pool = self._dedupe_evidence(pool)

        return HoldingAdviceReasoning(
            portfolio_fit=portfolio_fit,
            financial_health=financial_health,
            valuation_peer=valuation_peer,
            market_momentum=market_momentum,
            action_plan=action_plan,
            criteria=criteria_list,
            evidence_pool=pool,
        )



    @staticmethod
    def _format_bil_or_mil_vnd(val: Any) -> str:
        if val is None:
            return ""
        try:
            val_f = float(val)
            billions = val_f / 1000.0
            if abs(billions) >= 0.1:
                return f"{billions:,.1f} tỷ đồng"
            else:
                return f"{val_f:,.1f} triệu đồng"
        except (ValueError, TypeError):
            return ""

    @staticmethod
    def _pnl_to_decision(pnl_signal: str) -> str:
        """Map rule-based signal sang BUY/HOLD/SELL."""
        mapping = {
            "STRONG_PROFIT_HOLD": "HOLD",   # Lãi lớn → giữ (chốt lời từng phần)
            "PROFIT_HOLD": "HOLD",           # Lãi bình thường → giữ
            "NEUTRAL": "HOLD",               # Bình thường → giữ
            "LOSS_WATCH": "WATCH",           # Lỗ nhẹ → theo dõi
            "LOSS_REVIEW": "SELL",           # Lỗ nặng → xem xét bán
        }
        return mapping.get(pnl_signal, "HOLD")

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _success_response(data: HoldingsAdviceResponse) -> dict[str, Any]:
        advice_count = len(data.advice)
        if advice_count == 0:
            message = "Không có holdings nào để phân tích."
        elif data.cached_count == advice_count:
            message = f"Khuyến nghị danh mục từ cache ({advice_count} mã)."
        elif data.generated_count > 0:
            message = f"Khuyến nghị danh mục đã sẵn sàng ({advice_count} mã, {data.generated_count} mới)."
        else:
            message = f"Khuyến nghị danh mục đã sẵn sàng ({advice_count} mã)."
        return {
            "code": 200,
            "success": True,
            "message": message,
            "data": data.model_dump(by_alias=True),
        }

    @staticmethod
    def _error_response(
        code: int, message: str, error_type: str
    ) -> dict[str, Any]:
        return {
            "code": code,
            "success": False,
            "message": message,
            "error": {"type": error_type, "code": error_type, "details": []},
            "data": None,
        }
