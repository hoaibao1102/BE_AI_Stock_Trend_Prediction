from __future__ import annotations

from functools import lru_cache
from typing import Any

from analyse.clients.backend_client import BackendClient
from analyse.config.settings import Settings, get_settings
from analyse.repositories.ai_report_history_repository import create_ai_report_history_repository
from analyse.research.research_service import ExternalResearchService
from analyse.services.ai_report_history_service import AiReportHistoryService
from analyse.services.holdings_advice_service import HoldingsAdviceService
from analyse.services.report_service import ReportService
from analyse.services.user_identity_service import UserIdentityService
from analyse.services.visualization_dataset_service import VisualizationDatasetService
from analyse.services.visualization_signed_url_service import VisualizationSignedUrlService


def get_backend_client() -> BackendClient:
    return BackendClient(get_settings())


def get_external_research_service() -> ExternalResearchService:
    return ExternalResearchService(get_settings())


def get_user_identity_service() -> UserIdentityService:
    return UserIdentityService(get_backend_client())


def get_ai_report_history_repository() -> Any:
    return create_ai_report_history_repository(get_settings())


def get_ai_report_history_service() -> AiReportHistoryService:
    settings: Settings = get_settings()
    return AiReportHistoryService(settings=settings)


@lru_cache
def get_visualization_dataset_service() -> VisualizationDatasetService:
    return VisualizationDatasetService(get_settings())


@lru_cache
def get_visualization_signed_url_service() -> VisualizationSignedUrlService:
    return VisualizationSignedUrlService(get_settings())


def get_report_service() -> ReportService:
    settings: Settings = get_settings()
    backend_client = get_backend_client()
    return ReportService(
        settings=settings,
        backend_client=backend_client,
        research_service=get_external_research_service(),
        user_identity_service=UserIdentityService(backend_client),
        history_service=get_ai_report_history_service(),
    )


def get_holdings_advice_service() -> HoldingsAdviceService:
    """
    Factory cho HoldingsAdviceService.
    Wire đầy đủ dependencies: settings, backend_client, report_service, history_service, user_identity_service, research_service.
    """
    settings: Settings = get_settings()
    backend_client = get_backend_client()
    return HoldingsAdviceService(
        settings=settings,
        backend_client=backend_client,
        report_service=get_report_service(),
        history_service=get_ai_report_history_service(),
        user_identity_service=UserIdentityService(backend_client),
        research_service=get_external_research_service(),
    )

