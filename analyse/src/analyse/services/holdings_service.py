from __future__ import annotations

from typing import Any

from analyse.utils.symbol_utils import normalize_symbol


class HoldingsService:
    """Parse portfolio position payloads from Backend holdings API."""

    def extract_position_symbols(self, payload: Any) -> list[str]:
        items = self._extract_items(payload)
        symbols: list[str] = []
        seen: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = normalize_symbol(item.get("symbol"))
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)

        return symbols

    def _extract_items(self, payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload

        if not isinstance(payload, dict):
            return []

        data = payload.get("data", payload)
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return items
        if isinstance(data, list):
            return data

        items = payload.get("items")
        return items if isinstance(items, list) else []
