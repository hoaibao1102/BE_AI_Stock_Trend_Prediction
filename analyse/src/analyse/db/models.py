import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Index, Numeric, Unicode, UnicodeText, text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AiReportHistory(Base):
    __tablename__ = "ai_report_histories"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id: Mapped[str] = mapped_column(Unicode(120), nullable=False, unique=True)

    mongo_user_id: Mapped[str] = mapped_column(Unicode(64), nullable=False)
    user_email: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)

    mongo_watchlist_id: Mapped[str | None] = mapped_column(Unicode(64), nullable=True)
    mongo_stock_id: Mapped[str | None] = mapped_column(Unicode(64), nullable=True)

    symbol: Mapped[str] = mapped_column(Unicode(20), nullable=False)
    exchange: Mapped[str] = mapped_column(Unicode(20), nullable=False)
    company: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)

    provider: Mapped[str] = mapped_column(Unicode(50), nullable=False)
    model: Mapped[str] = mapped_column(Unicode(100), nullable=False)

    risk_profile: Mapped[str | None] = mapped_column(Unicode(30), nullable=True)
    time_horizon: Mapped[str | None] = mapped_column(Unicode(30), nullable=True)
    include_external_research: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))

    total_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    data_confidence: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    decision_label: Mapped[str | None] = mapped_column(Unicode(120), nullable=True)

    report_json: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    summary_snapshot: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)

    source_hash: Mapped[str | None] = mapped_column(Unicode(128), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(Unicode(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


Index("IX_ai_report_histories_user_created", AiReportHistory.mongo_user_id, AiReportHistory.created_at.desc())
Index("IX_ai_report_histories_user_symbol_created", AiReportHistory.mongo_user_id, AiReportHistory.symbol, AiReportHistory.exchange, AiReportHistory.created_at.desc())
Index("IX_ai_report_histories_report_id", AiReportHistory.report_id)
