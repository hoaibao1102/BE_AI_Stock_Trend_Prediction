CREATE TABLE ai_report_histories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    report_id VARCHAR(120) NOT NULL UNIQUE,

    mongo_user_id VARCHAR(64) NOT NULL,
    user_email VARCHAR(255) NULL,

    mongo_watchlist_id VARCHAR(64) NULL,
    mongo_stock_id VARCHAR(64) NULL,

    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    company VARCHAR(255) NULL,

    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,

    risk_profile VARCHAR(30) NULL,
    time_horizon VARCHAR(30) NULL,
    include_external_research BOOLEAN NOT NULL DEFAULT TRUE,

    total_score DECIMAL(6,2) NULL,
    risk_score DECIMAL(6,2) NULL,
    data_confidence DECIMAL(6,2) NULL,
    decision_label VARCHAR(120) NULL,

    report_json TEXT NOT NULL,
    summary_snapshot TEXT NULL,

    source_hash VARCHAR(128) NULL,
    request_hash VARCHAR(128) NULL,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IX_ai_report_histories_user_created
ON ai_report_histories (mongo_user_id, created_at DESC);

CREATE INDEX IX_ai_report_histories_user_symbol_created
ON ai_report_histories (mongo_user_id, symbol, exchange, created_at DESC);

CREATE INDEX IX_ai_report_histories_report_id
ON ai_report_histories (report_id);
