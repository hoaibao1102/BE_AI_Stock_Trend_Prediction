from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

from analyse.clients.http_client import HttpClient, HttpClientError
from analyse.config.settings import Settings, get_settings


class BackendClient:
    """Client gọi Node.js Backend API hiện có."""

    def __init__(self, settings: Settings | None = None, http_client: HttpClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self._normalize_base_url(self.settings.backend_api_base_url)
        self.http_client = http_client or HttpClient(
            timeout_ms=self.settings.backend_api_timeout_ms,
            verify_ssl=self.settings.backend_api_verify_ssl,
        )
        self.diagnostics: list[dict[str, Any]] = []

    def _headers(self, token: str | None = None) -> dict[str, str]:
        return self._auth_headers(token)

    def _auth_headers(self, token: str | None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        auth_value = self._authorization_header(token)
        if auth_value:
            headers["Authorization"] = auth_value
        return headers

    def _authorization_header(self, token: str | None = None) -> str | None:
        normalized = self._normalize_request_token(token)
        if not normalized:
            return None
        return f"Bearer {normalized}"

    def _normalize_request_token(self, token: str | None) -> str:
        value = str(token or "").strip()
        if value.lower().startswith("bearer "):
            value = value[7:].strip()
        return value

    def _require_token(self, token: str | None, operation: str) -> str:
        normalized = self._normalize_request_token(token)
        if not normalized:
            raise ValueError(f"Backend user token is required for {operation}")
        return normalized

    def _url(self, path: str) -> str:
        clean_path = path if path.startswith("/") else f"/{path}"
        return urljoin(self.base_url + "/", clean_path.lstrip("/"))

    def build_url(self, path: str, *, params: dict[str, Any] | None = None) -> str:
        url = self._url(path)
        if not params:
            return url
        return f"{url}?{urlencode(params)}"

    def build_stock_analysis_data_url(
        self,
        symbol: str,
        exchange: str | None = None,
        quarters: int | None = None,
        chart_range: str | None = None,
        include_peers: bool | None = None,
        include_market_context: bool | None = None,
    ) -> str:
        path = self.settings.backend_analysis_data_endpoint.format(symbol=symbol.upper())
        params = self._analysis_data_params(
            exchange=exchange,
            quarters=quarters if quarters is not None else self.settings.backend_analysis_data_quarters,
            chart_range=chart_range or self.settings.backend_analysis_data_chart_range,
            include_peers=self.settings.backend_analysis_data_include_peers if include_peers is None else include_peers,
            include_market_context=(
                self.settings.backend_analysis_data_include_market_context
                if include_market_context is None
                else include_market_context
            ),
        )
        return self.build_url(path, params=params)

    def _normalize_base_url(self, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("BACKEND_API_BASE_URL chưa được cấu hình.")
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("BACKEND_API_BASE_URL phải có dạng http://host:port hoặc https://domain.")
        normalized = raw.rstrip("/")
        if normalized.lower().endswith("/api"):
            normalized = normalized[:-4].rstrip("/")
        return normalized

    def _record_success(self, url: str, *, params: dict[str, Any] | None = None, token: str | None = None) -> None:
        self.diagnostics.append(
            {
                "method": "GET",
                "url": self._with_params(url, params),
                "status": "success",
                "token_attached": bool(self._authorization_header(token)),
                "timeout_ms": self.settings.backend_api_timeout_ms,
            }
        )

    def _record_failure(self, exc: Exception, *, url: str, params: dict[str, Any] | None = None, token: str | None = None) -> None:
        if isinstance(exc, HttpClientError):
            diagnostic = exc.diagnostic()
        else:
            diagnostic = {"method": "GET", "url": self._with_params(url, params), "category": exc.__class__.__name__, "message": str(exc)}
        diagnostic.update(
            {
                "status": "failed",
                "token_attached": bool(self._authorization_header(token)),
                "timeout_ms": self.settings.backend_api_timeout_ms,
            }
        )
        self.diagnostics.append(diagnostic)

    async def _get_json(self, path: str, *, token: str, params: dict[str, Any] | None = None, operation: str = "backend request") -> dict[str, Any]:
        clean_token = self._require_token(token, operation)
        url = self._url(path)
        try:
            payload = await self.http_client.get_json(url, headers=self._headers(clean_token), params=params)
        except Exception as exc:
            self._record_failure(exc, url=url, params=params, token=clean_token)
            raise
        self._record_success(url, params=params, token=clean_token)
        return payload

    async def get_watchlists(self, *, token: str) -> dict[str, Any]:
        path = self.settings.backend_watchlist_endpoint
        return await self._get_json(path, token=token, operation="get_watchlists")

    async def get_holdings_pnl(self, *, token: str) -> dict[str, Any]:
        path = self.settings.backend_holdings_pnl_endpoint
        return await self._get_json(path, token=token, operation="get_holdings_pnl")

    async def get_current_user(self, *, token: str) -> dict[str, Any]:
        path = self.settings.backend_current_user_endpoint
        return await self._get_json(path, token=token, operation="get_current_user")

    async def get_stock_detail(self, symbol: str, *, token: str) -> dict[str, Any]:
        path = self.settings.backend_stock_detail_endpoint.format(symbol=symbol.upper())
        return await self._get_json(path, token=token, operation="get_stock_detail")

    async def get_stock_chart(self, symbol: str, range_value: str = "1m", *, token: str) -> dict[str, Any]:
        endpoint = self.settings.backend_stock_chart_endpoint
        if "{range}" in endpoint:
            path = endpoint.format(symbol=symbol.upper(), range=range_value)
            params = None
        else:
            path = endpoint.format(symbol=symbol.upper())
            params = {"range": range_value}
        return await self._get_json(path, token=token, params=params, operation="get_stock_chart")

    async def get_stock_analysis_data(
        self,
        symbol: str,
        *,
        token: str,
        exchange: str | None = None,
        quarters: int = 6,
        chart_range: str = "3m",
        include_peers: bool = True,
        include_market_context: bool = True,
    ) -> dict[str, Any]:
        path = self.settings.backend_analysis_data_endpoint.format(symbol=symbol.upper())
        params = self._analysis_data_params(
            exchange=exchange,
            quarters=quarters,
            chart_range=chart_range,
            include_peers=include_peers,
            include_market_context=include_market_context,
        )
        return await self._get_json(path, token=token, params=params, operation="get_stock_analysis_data")

    def _analysis_data_params(
        self,
        *,
        exchange: str | None,
        quarters: int,
        chart_range: str,
        include_peers: bool,
        include_market_context: bool,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "quarters": quarters,
            "chartRange": chart_range,
            "includePeers": str(include_peers).lower(),
            "includeMarketContext": str(include_market_context).lower(),
        }
        if exchange:
            params["exchange"] = exchange.upper()
        return params

    def _with_params(self, url: str, params: dict[str, Any] | None) -> str:
        if not params:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{urlencode(params)}"

    def sanitized_diagnostics(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.diagnostics[-20:]]
