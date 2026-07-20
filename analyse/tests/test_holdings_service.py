from analyse.services.holdings_service import HoldingsService


def test_extract_position_symbols_from_holdings_pnl_payload():
    service = HoldingsService()
    payload = {
        "data": {
            "items": [
                {"symbol": "HPG"},
                {"symbol": "VCB"},
                {"symbol": "hpg"},
            ]
        }
    }

    assert service.extract_position_symbols(payload) == ["HPG", "VCB"]
