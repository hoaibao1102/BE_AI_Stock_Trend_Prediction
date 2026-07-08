from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from analyse.config.settings import Settings, get_settings
from analyse.research.article_extractor import ArticleExtractor
from analyse.research.base import normalize_domain, parse_datetime_for_sort
from analyse.research.evidence_normalizer import EvidenceNormalizer
from analyse.research.research_query_builder import ResearchQueryBuilder
from analyse.research.source_registry import SourceRegistry
from analyse.schemas.evidence import EvidenceBundle, ForecastScenario, SourceEvidence
from analyse.schemas.research import ExternalResearchContext
from analyse.utils.debug_scrub import scrub_debug_payload
from analyse.utils.symbol_utils import normalize_symbol


class SourceBackedEnrichmentService:
    """Central source-backed evidence and forecast enrichment layer."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        source_registry: SourceRegistry | None = None,
        query_builder: ResearchQueryBuilder | None = None,
        evidence_normalizer: EvidenceNormalizer | None = None,
        article_extractor: ArticleExtractor | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.source_registry = source_registry or SourceRegistry(self.settings)
        self.query_builder = query_builder or ResearchQueryBuilder(self.settings)
        self.evidence_normalizer = evidence_normalizer or EvidenceNormalizer()
        self.article_extractor = article_extractor or ArticleExtractor(self.settings)

    async def enrich(
        self,
        *,
        symbol: str,
        exchange: str | None,
        company_name: str | None,
        summary: dict[str, Any],
        research_context: ExternalResearchContext | None,
    ) -> dict[str, Any]:
        if not self.settings.enable_source_backed_research:
            return summary
        clean_symbol = normalize_symbol(symbol)
        industry = self._industry_label(summary)
        source_attempts = self.source_registry.build_source_attempts(symbol=clean_symbol, exchange=exchange)
        queries = self.query_builder.build_domain_queries(
            symbol=clean_symbol,
            company_name=company_name,
            exchange=exchange,
            domains=[attempt["domain"] for attempt in source_attempts if attempt.get("domain")],
            max_queries=max(8, min(30, int(self.settings.source_backed_research_max_articles or 20))),
        )
        evidence = self.evidence_normalizer.from_summary(
            symbol=clean_symbol,
            exchange=exchange,
            company_name=company_name,
            summary=summary,
            research_context=research_context,
        )
        article_extractions = await self._extract_articles(research_context)
        article_evidence = self._article_evidence(
            symbol=clean_symbol,
            exchange=exchange,
            company_name=company_name,
            articles=article_extractions,
        )
        if article_evidence:
            evidence = [*article_evidence, *evidence]
        accepted, rejected = self.evidence_normalizer.dedupe_and_score(
            evidence,
            symbol=clean_symbol,
            company_name=company_name,
            industry=industry,
        )
        accepted = accepted[: max(1, int(self.settings.source_backed_research_max_articles or 20))]
        scenarios = self._build_forecast_scenarios(summary, accepted)
        bundle = EvidenceBundle(
            symbol=clean_symbol,
            exchange=exchange,
            company_name=company_name,
            generated_at=datetime.now(timezone.utc),
            sources_attempted=[str(attempt.get("name")) for attempt in source_attempts],
            sources_successful=sorted({item.source_name for item in accepted}),
            sources_failed=self._failed_sources(source_attempts, accepted),
            evidence_used=accepted,
            evidence_rejected=rejected,
            research_queries=queries,
            forecast_scenarios=scenarios,
            warnings=self._warnings(research_context, rejected),
        )
        enriched = dict(summary)
        enriched["source_backed_evidence"] = self._compact_evidence_bundle(bundle)
        enriched["evidence_table"] = self._evidence_table(accepted)
        enriched["executive_forecast"] = self._executive_forecast(enriched, scenarios, accepted)
        enriched["quantitative_signal_summary"] = self._quantitative_signal_summary(enriched, accepted)
        enriched["forecast_scenarios"] = [scenario.model_dump(mode="json") for scenario in scenarios]
        enriched["scenarios"] = [scenario.model_dump(mode="json") for scenario in scenarios]
        enriched["risk_map"] = self._risk_map(enriched, accepted)
        enriched["action_plan"] = self._action_plan_from_scenarios(enriched, scenarios)
        enriched["checklist"] = self._checklist_from_evidence(enriched, accepted)
        enriched["missing_value_policy"] = self._missing_value_policy(enriched)
        self._save_debug_artifacts(clean_symbol, exchange, bundle, article_extractions, enriched)
        return enriched

    async def _extract_articles(self, research_context: ExternalResearchContext | None) -> list[dict[str, Any]]:
        if not (self.settings.enable_deep_research_crawl and research_context and research_context.items):
            return []
        extractions: list[dict[str, Any]] = []
        for item in research_context.items[: min(5, int(self.settings.source_backed_research_max_articles or 20))]:
            if not item.url:
                continue
            try:
                extracted = await self.article_extractor.fetch_and_extract(item.url)
            except Exception as exc:
                extractions.append({"url": item.url, "status": "failed", "error_type": exc.__class__.__name__})
                continue
            extractions.append({"url": item.url, "status": "success", **extracted})
        return extractions

    def _article_evidence(
        self,
        *,
        symbol: str,
        exchange: str | None,
        company_name: str | None,
        articles: list[dict[str, Any]],
    ) -> list[SourceEvidence]:
        result: list[SourceEvidence] = []
        official_domains = {
            normalize_domain(domain)
            for domain in str(getattr(self.settings, "research_official_source_priority", "") or "").split(",")
            if domain.strip()
        }
        for article in articles:
            if article.get("status") != "success":
                continue
            body = str(article.get("body_text") or "").strip()
            title = str(article.get("title") or "").strip() or None
            if len(body) < 80 and not title:
                continue
            url = str(article.get("url") or "") or None
            domain = normalize_domain(article.get("source_domain") or url)
            source_type = "official_disclosure" if domain in official_domains else "news"
            source_name = self.source_registry.display_name_for_domain(domain, official=source_type == "official_disclosure") if domain else "Tin tức và nghiên cứu bên ngoài"
            summary = body[:600] if body else (title or "Bài viết nguồn ngoài đã được trích xuất.")
            result.append(
                SourceEvidence(
                    source_name=source_name,
                    source_type=source_type,  # type: ignore[arg-type]
                    url=url,
                    title=title,
                    published_at=parse_datetime_for_sort(article.get("published_at")),
                    crawled_at=datetime.now(timezone.utc),
                    symbol=symbol,
                    exchange=exchange,
                    company_name=company_name,
                    summary=summary,
                    extracted_facts=[
                        {
                            "key": "article_context",
                            "label": "Ngữ cảnh bài viết",
                            "value": summary,
                            "confidence": 0.6,
                            "source_name": source_name,
                            "source_url": url,
                        },
                        {
                            "key": "article_word_count",
                            "label": "Độ dài bài viết đã trích xuất",
                            "value": article.get("word_count"),
                            "unit": "từ",
                            "confidence": 0.7,
                            "source_name": source_name,
                            "source_url": url,
                        },
                    ],
                    relevance_score=0.0,
                    usable=True,
                )
            )
        return result

    def _build_forecast_scenarios(self, summary: dict[str, Any], evidence: list[SourceEvidence]) -> list[ForecastScenario]:
        if not self.settings.enable_forecast_scenarios:
            return []
        scores = self._dict(summary.get("scores"))
        momentum = self._dict(summary.get("momentum"))
        market = self._dict(summary.get("hose_market_context"))
        overall = self._number(scores.get("overall_score"), 50)
        risk = self._number(scores.get("risk_score"), 50)
        confidence = self._number(scores.get("score_confidence"), 0.5)
        if confidence <= 1:
            confidence *= 100
        chart_change = self._number(momentum.get("chart_period_change_pct"), 0)
        market_score = self._number(market.get("market_health_score"), 50)

        positive = 28 + (overall - 50) * 0.25 + max(-8, min(8, chart_change * 0.4)) + (market_score - 50) * 0.12 - max(0, risk - 60) * 0.12
        cautious = 25 + max(0, risk - 50) * 0.28 + max(0, -chart_change) * 0.35 + max(0, 50 - market_score) * 0.18
        if confidence < 55:
            cautious += 8
            positive -= 5
        positive = max(15, min(45, positive))
        cautious = max(15, min(45, cautious))
        base = max(20, 100 - positive - cautious)
        total = positive + base + cautious
        probs = [round(positive / total * 100), round(base / total * 100), round(cautious / total * 100)]
        probs[1] += 100 - sum(probs)

        supporting = self._supporting_signals(summary, evidence)
        invalidations = self._invalidation_signals(summary)
        source_labels = sorted({item.source_name for item in evidence[:8]})
        horizon = self._primary_horizon()
        return [
            ForecastScenario(
                scenario="Tích cực",
                probability_pct=probs[0],
                time_horizon=horizon,
                condition="Giá giữ được động lượng, thanh khoản cải thiện và không xuất hiện tin xấu mới từ nguồn đã theo dõi.",
                expected_behavior="Xác suất duy trì hoặc củng cố xu hướng tích cực cao hơn, nhưng vẫn cần xác nhận bằng dữ liệu mới.",
                supporting_signals=supporting[:5],
                invalidation_signals=invalidations[:4],
                risk_note="Đây là kịch bản xác suất dựa trên dữ liệu hiện có, không phải khuyến nghị mua/bán.",
                inference_basis=["score_weighted", "momentum", "market_context", "source_backed_evidence"],
                source_labels=source_labels,
            ),
            ForecastScenario(
                scenario="Cơ sở",
                probability_pct=probs[1],
                time_horizon=horizon,
                condition="Giá dao động quanh vùng hiện tại, dữ liệu cơ bản không thay đổi lớn và bối cảnh thị trường không xấu đi rõ rệt.",
                expected_behavior="Ưu tiên theo dõi thêm xác nhận; tín hiệu hiện tại chưa đủ để nâng mức conviction.",
                supporting_signals=supporting[:5],
                invalidation_signals=invalidations[:4],
                risk_note="Kịch bản cơ sở là khung quan sát xác suất, không phải khuyến nghị giao dịch cá nhân hóa.",
                inference_basis=["score_weighted", "data_confidence", "risk_balance"],
                source_labels=source_labels,
            ),
            ForecastScenario(
                scenario="Thận trọng",
                probability_pct=probs[2],
                time_horizon=horizon,
                condition="Giá suy yếu, thanh khoản giảm hoặc tin tức/BCTC mới làm giảm độ tin cậy của luận điểm.",
                expected_behavior="Ưu tiên quản trị rủi ro, giảm mức tự tin và kiểm tra lại toàn bộ luận điểm.",
                supporting_signals=self._risk_signals(summary, evidence),
                invalidation_signals=["Tín hiệu tích cực chỉ được khôi phục khi giá, thanh khoản và tin tức cùng xác nhận trở lại.", *invalidations[:3]],
                risk_note="Kịch bản thận trọng nhấn mạnh bảo toàn vốn trong khung học tập, không phải khuyến nghị bán.",
                inference_basis=["risk_score", "negative_evidence", "market_context"],
                source_labels=source_labels,
            ),
        ]

    def _supporting_signals(self, summary: dict[str, Any], evidence: list[SourceEvidence]) -> list[str]:
        scores = self._dict(summary.get("scores"))
        momentum = self._dict(summary.get("momentum"))
        market = self._dict(summary.get("hose_market_context"))
        signals: list[str] = []
        if scores.get("overall_score") is not None:
            signals.append(f"Điểm tổng {scores.get('overall_score')}/100 ({scores.get('overall_label')}).")
        if momentum.get("chart_period_change_pct") is not None:
            signals.append(f"Biến động kỳ chart {momentum.get('chart_period_change_pct')}%.")
        if market.get("market_health_label") or market.get("status"):
            signals.append(f"Bối cảnh thị trường: {market.get('market_health_label') or market.get('status')}.")
        financial = next((item for item in evidence if item.source_type == "structured_financial"), None)
        if financial:
            signals.append(financial.summary)
        if evidence:
            signals.append(f"Có {len(evidence)} bằng chứng nguồn được dùng trong khung dự báo.")
        return signals or ["Dữ liệu định lượng hiện có đủ để dựng khung quan sát xác suất."]

    def _risk_signals(self, summary: dict[str, Any], evidence: list[SourceEvidence]) -> list[str]:
        scores = self._dict(summary.get("scores"))
        weaknesses = [str(item) for item in self._list_any(summary.get("weaknesses")) if item]
        signals = []
        if scores.get("risk_score") is not None:
            signals.append(f"Điểm rủi ro {scores.get('risk_score')}/100 ({scores.get('risk_label')}).")
        signals.extend(weaknesses[:3])
        negative_news = [item for item in evidence if any("tiêu cực" in str(fact.value).lower() for fact in item.extracted_facts)]
        if negative_news:
            signals.append("Có tin tức/ngữ cảnh tiêu cực cần kiểm chứng từ URL nguồn.")
        return signals or ["Thiếu dữ liệu xác nhận mạnh; cần giữ mức thận trọng."]

    def _invalidation_signals(self, summary: dict[str, Any]) -> list[str]:
        return [
            "Giá giảm mạnh kèm thanh khoản cao.",
            "BCTC mới xấu hơn kỳ trước hoặc chất lượng lợi nhuận suy yếu.",
            "Tin tức tiêu cực về ngành/doanh nghiệp từ nguồn đáng tin cậy.",
            "Bối cảnh VN-Index chuyển sang trạng thái thận trọng/risk-off.",
        ]

    def _action_plan_from_scenarios(self, summary: dict[str, Any], scenarios: list[ForecastScenario]) -> dict[str, Any]:
        max_position = self._format_percent(getattr(self.settings, "default_max_position_pct", 12.0))
        risk_pct = self._format_percent(getattr(self.settings, "default_risk_per_trade_pct", 1.0))
        rows = []
        for scenario in scenarios[:3]:
            rows.append(
                {
                    "timeframe": scenario.time_horizon,
                    "action": f"Theo dõi kịch bản {scenario.scenario.lower()} và chỉ nâng/hạ mức quan sát khi điều kiện xác nhận rõ hơn.",
                    "condition": scenario.condition,
                    "price_zone": None,
                    "position_size": f"Không vượt quá {max_position} danh mục giả định trong khung học tập.",
                    "stop_loss": f"Tín hiệu vô hiệu: {scenario.invalidation_signals[0] if scenario.invalidation_signals else 'dữ liệu mới làm luận điểm suy yếu'}; rủi ro tham chiếu {risk_pct} vốn.",
                    "note": scenario.risk_note,
                    "risk_note": scenario.risk_note,
                }
            )
        return {"short_term": rows[:1], "medium_term": rows[1:2], "watch_points": rows, "risk_management": rows[-1:]}

    def _checklist_from_evidence(self, summary: dict[str, Any], evidence: list[SourceEvidence]) -> list[dict[str, Any]]:
        items = [
            {
                "label": "Kiểm tra xu hướng giá",
                "status": "pending",
                "note": "Đối chiếu biến động kỳ chart, thanh khoản và vùng giá hiện tại trước khi đánh giá kịch bản.",
            },
            {
                "label": "Đọc BCTC gần nhất",
                "status": "pending",
                "note": "So sánh các kỳ BCTC đã ghi nhận và kiểm tra thay đổi doanh thu/lợi nhuận.",
            },
            {
                "label": "Xác minh bằng chứng bên ngoài",
                "status": "pending",
                "note": f"Mở URL nguồn của các bằng chứng quan trọng; hiện có {len(evidence)} evidence item dùng được.",
            },
            {
                "label": "Theo dõi tín hiệu vô hiệu",
                "status": "pending",
                "note": "Kiểm tra giá giảm kèm thanh khoản cao, BCTC xấu hơn hoặc tin tiêu cực mới.",
            },
        ]
        return items

    def _executive_forecast(self, summary: dict[str, Any], scenarios: list[ForecastScenario], evidence: list[SourceEvidence]) -> dict[str, Any]:
        base = max(scenarios, key=lambda item: item.probability_pct) if scenarios else None
        confidence = self._dict(summary.get("scores")).get("score_confidence")
        return {
            "label": "Dự báo xác suất tham khảo",
            "primary_scenario": base.scenario if base else "Cơ sở",
            "primary_probability_pct": base.probability_pct if base else None,
            "confidence": confidence,
            "basis": "Mô hình suy luận từ điểm định lượng, momentum, BCTC, market context, peer và evidence nguồn.",
            "evidence_count": len(evidence),
            "disclaimer": "Forecast là model inference có gắn nguồn dữ liệu, không phải sự thật chắc chắn hoặc khuyến nghị mua/bán.",
        }

    def _quantitative_signal_summary(self, summary: dict[str, Any], evidence: list[SourceEvidence]) -> dict[str, Any]:
        scores = self._dict(summary.get("scores"))
        momentum = self._dict(summary.get("momentum"))
        coverage = self._dict(summary.get("data_coverage"))
        return {
            "overall_score": scores.get("overall_score"),
            "risk_score": scores.get("risk_score"),
            "momentum_change_pct": momentum.get("chart_period_change_pct"),
            "financial_periods": coverage.get("financial_periods_count"),
            "peer_count": len(self._list(self._dict(summary.get("industry_peer_context")).get("peers"))),
            "evidence_count": len(evidence),
        }

    def _risk_map(self, summary: dict[str, Any], evidence: list[SourceEvidence]) -> list[dict[str, Any]]:
        risks = [str(item) for item in self._list_any(summary.get("weaknesses")) if item]
        return [
            {
                "risk": risk,
                "monitoring_signal": "Đối chiếu với dữ liệu giá, BCTC hoặc tin tức mới.",
                "source": "summary/evidence",
            }
            for risk in (risks[:4] or ["Dữ liệu đầu vào chưa đủ độ phủ để nâng conviction."])
        ]

    def _missing_value_policy(self, summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "numeric_missing_label": "Chưa có nguồn số liệu đáng tin cậy",
            "qualitative_policy": "Cho phép model inference từ evidence hiện có, luôn gắn nhãn là kịch bản/xác suất tham khảo.",
            "require_source_for_numeric_facts": bool(self.settings.source_backed_research_require_source_for_numeric_facts),
            "show_missing_reason": bool(self.settings.report_show_missing_reason),
            "policy": self.settings.report_missing_value_policy,
        }

    def _evidence_table(self, evidence: list[SourceEvidence]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in evidence[:20]:
            rows.append(
                {
                    "source_name": item.source_name,
                    "source_type": item.source_type,
                    "title": item.title,
                    "url": item.url,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "crawled_at": item.crawled_at.isoformat() if item.crawled_at else None,
                    "summary": item.summary,
                    "fact_count": len(item.extracted_facts),
                    "relevance_score": item.relevance_score,
                    "reliability_score": item.reliability_score,
                    "freshness_score": item.freshness_score,
                    "inclusion_reason": item.inclusion_reason,
                }
            )
        return rows

    def _compact_evidence_bundle(self, bundle: EvidenceBundle) -> dict[str, Any]:
        payload = bundle.model_dump(mode="json")
        payload["evidence_used"] = payload.get("evidence_used", [])[:20]
        payload["evidence_rejected"] = payload.get("evidence_rejected", [])[:20]
        return payload

    def _failed_sources(self, attempts: list[dict[str, Any]], evidence: list[SourceEvidence]) -> list[str]:
        successful = {item.source_name for item in evidence}
        result = []
        for attempt in attempts:
            name = str(attempt.get("name") or "")
            if name and name not in successful and attempt.get("source_type") in {"news", "official_disclosure"}:
                result.append(name)
        return result[:10]

    def _warnings(self, research_context: ExternalResearchContext | None, rejected: list[SourceEvidence]) -> list[str]:
        warnings = []
        if research_context and research_context.flag_summary:
            warnings.extend([str(item) for item in research_context.flag_summary.get("warnings") or []])
        if rejected:
            warnings.append(f"Đã loại {len(rejected)} evidence item do trùng lặp hoặc điểm nguồn/liên quan thấp.")
        return warnings

    def _save_debug_artifacts(
        self,
        symbol: str,
        exchange: str | None,
        bundle: EvidenceBundle,
        article_extractions: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> None:
        if not (self.settings.external_data_debug_save_extraction_json or self.settings.vietstock_debug_save_extraction_json):
            return
        debug_dir = Path(self.settings.report_output_dir) / "debug"
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
            base = {
                "symbol": symbol,
                "exchange": exchange,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "sources_attempted": bundle.sources_attempted,
                "sources_successful": bundle.sources_successful,
                "sources_failed": bundle.sources_failed,
                "warnings": bundle.warnings,
            }
            files = {
                f"{symbol}_source_backed_evidence.json": {**base, "evidence_used": [item.model_dump(mode="json") for item in bundle.evidence_used], "evidence_rejected": [item.model_dump(mode="json") for item in bundle.evidence_rejected]},
                f"{symbol}_research_queries.json": {**base, "queries": bundle.research_queries},
                f"{symbol}_article_extraction.json": {**base, "article_extractions": article_extractions},
                f"{symbol}_forecast_scenarios.json": {**base, "forecast_scenarios": [item.model_dump(mode="json") for item in bundle.forecast_scenarios]},
                f"{symbol}_missing_value_policy.json": {**base, "missing_value_policy": summary.get("missing_value_policy")},
                f"{symbol}_llm_prompt_input_evidence.json": {**base, "evidence_used": summary.get("evidence_table"), "forecast_scenarios": summary.get("forecast_scenarios")},
            }
            for filename, payload in files.items():
                (debug_dir / filename).write_text(
                    json.dumps(self._scrub(payload), ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
        except Exception:
            return

    def _industry_label(self, summary: dict[str, Any]) -> str | None:
        industry = self._dict(self._dict(summary.get("industry_peer_context")).get("industry"))
        return industry.get("industry") or industry.get("industry_name") or industry.get("industry_level_3") or industry.get("sector")

    def _primary_horizon(self) -> str:
        horizons = [item.strip() for item in str(self.settings.forecast_time_horizons or "").split(",") if item.strip()]
        mapping = {"short_term": "1-4 tuần", "base_term": "1-3 tháng", "medium_term": "3-6 tháng"}
        return mapping.get(horizons[1] if len(horizons) > 1 else "base_term", "1-3 tháng")

    def _format_percent(self, value: Any) -> str:
        numeric = self._number(value, None)
        if numeric is None:
            return "Chưa có nguồn số liệu đáng tin cậy"
        return f"{numeric:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "%"

    def _number(self, value: Any, default: float | None) -> float | None:
        if value in (None, "") or isinstance(value, bool):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _list(self, value: Any) -> list[dict[str, Any]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def _list_any(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _scrub(self, value: Any) -> Any:
        return scrub_debug_payload(value)
