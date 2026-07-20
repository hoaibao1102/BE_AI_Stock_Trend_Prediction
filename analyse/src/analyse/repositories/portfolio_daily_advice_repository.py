from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from analyse.config.settings import ANALYSE_ROOT, Settings, get_settings

logger = logging.getLogger(__name__)


class PortfolioDailyAdviceRepository:
    """File-backed once-per-day portfolio advice cache (user + symbol + VN date)."""

    _lock = threading.RLock()

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        configured = str(
            getattr(self.settings, "portfolio_daily_advice_dir", "storage/portfolio_daily_advice")
            or "storage/portfolio_daily_advice"
        ).strip()
        base = Path(configured)
        self.base_dir = base if base.is_absolute() else ANALYSE_ROOT / base

    def advice_date_str(self, *, at: datetime | None = None) -> str:
        tz_name = self.settings.analyse_timezone or "Asia/Ho_Chi_Minh"
        tz = ZoneInfo(tz_name)
        current = (at or datetime.now(tz)).astimezone(tz)
        return current.strftime("%Y%m%d")

    def _path_for(self, *, user_id: str, symbol: str, advice_date: str) -> Path:
        safe_user = self._safe_segment(user_id)
        safe_symbol = self._safe_segment(symbol.upper())
        safe_date = self._safe_segment(advice_date)
        return self.base_dir / safe_user / safe_date / f"{safe_symbol}.json"

    def get(
        self,
        *,
        user_id: str,
        symbol: str,
        advice_date: str | None = None,
    ) -> dict[str, Any] | None:
        date_key = advice_date or self.advice_date_str()
        path = self._path_for(user_id=user_id, symbol=symbol, advice_date=date_key)
        if not path.exists():
            return None
        try:
            with self._lock:
                payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            stored_date = str(payload.get("advice_date") or "").strip()
            if stored_date and stored_date != date_key:
                return None
            advice = payload.get("advice")
            if not isinstance(advice, dict):
                return None
            return payload
        except Exception as exc:
            logger.warning(
                "[portfolio-daily-advice] read failed user=%s symbol=%s: %s",
                user_id,
                symbol,
                exc,
            )
            return None

    def save(
        self,
        *,
        user_id: str,
        symbol: str,
        advice: dict[str, Any],
        advice_date: str | None = None,
        source: str = "generated",
    ) -> None:
        date_key = advice_date or self.advice_date_str()
        path = self._path_for(user_id=user_id, symbol=symbol, advice_date=date_key)
        payload = {
            "user_id": user_id,
            "symbol": symbol.upper(),
            "advice_date": date_key,
            "saved_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "source": source,
            "advice": advice,
        }
        try:
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = path.with_suffix(".json.tmp")
                temp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temp_path.replace(path)
        except Exception as exc:
            logger.warning(
                "[portfolio-daily-advice] save failed user=%s symbol=%s: %s",
                user_id,
                symbol,
                exc,
            )

    @staticmethod
    def _safe_segment(value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))
        return cleaned or "unknown"
