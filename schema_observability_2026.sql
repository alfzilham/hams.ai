-- ============================================================
-- AI OBSERVABILITY DASHBOARD 2026 — PostgreSQL Schema
-- zilf.ai | Railway PostgreSQL
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for fast text search on emails

-- ============================================================
-- TABLE: users
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(100) UNIQUE NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    is_admin        BOOLEAN DEFAULT FALSE,
    plan            VARCHAR(50) DEFAULT 'free',
    source          VARCHAR(100),          -- organic | referral | api
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ,
    -- Revenue (Rp20.000 per registrasi)
    revenue_credited  BOOLEAN DEFAULT FALSE,
    revenue_amount    INTEGER DEFAULT 20000
);

-- ============================================================
-- TABLE: model_logs  (Performa: latency, throughput, cost)
-- ============================================================
CREATE TABLE IF NOT EXISTS model_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    session_id      VARCHAR(255),
    model_name      VARCHAR(100) NOT NULL,
    provider        VARCHAR(100),           -- openai | anthropic | groq | zilf_max
    request_type    VARCHAR(50),            -- chat | completion | vision | embedding
    -- Performa
    latency_ms      INTEGER,
    throughput_tps  FLOAT,
    error_code      VARCHAR(50),
    error_message   TEXT,
    -- Token & Cost
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    total_tokens    INTEGER GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,
    cost_usd        NUMERIC(12, 8) DEFAULT 0,
    cost_idr        NUMERIC(14, 2) DEFAULT 0,
    -- Metadata
    temperature     FLOAT,
    prompt_length   INTEGER,
    response_length INTEGER,
    logged_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLE: model_quality  (Akurasi, Drift, Etika)
-- ============================================================
CREATE TABLE IF NOT EXISTS model_quality (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_name            VARCHAR(100) NOT NULL,
    log_id                UUID REFERENCES model_logs(id) ON DELETE SET NULL,
    evaluated_at          TIMESTAMPTZ DEFAULT NOW(),
    evaluator             VARCHAR(100) DEFAULT 'system',
    -- Akurasi & Presisi
    accuracy_score        FLOAT,       -- 0.0–1.0
    precision_score       FLOAT,
    recall_score          FLOAT,
    f1_score              FLOAT,
    confidence_score      FLOAT,
    trust_score           FLOAT,       -- composite
    -- Drift
    data_drift_score      FLOAT,       -- input distribution drift
    concept_drift_score   FLOAT,       -- output/relasi drift
    drift_detected        BOOLEAN DEFAULT FALSE,
    drift_threshold       FLOAT DEFAULT 0.15,
    -- Perilaku & Etika
    hallucination_rate    FLOAT,
    toxicity_score        FLOAT,
    bias_score            FLOAT
);

-- ============================================================
-- TABLE: security_audit  (OWASP LLM Top 10 + PII)
-- ============================================================
CREATE TABLE IF NOT EXISTS security_audit (
    id                         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                    UUID REFERENCES users(id) ON DELETE SET NULL,
    session_id                 VARCHAR(255),
    detected_at                TIMESTAMPTZ DEFAULT NOW(),
    -- OWASP LLM Classification
    owasp_category             VARCHAR(20),    -- LLM01..LLM10
    owasp_label                VARCHAR(200),
    severity                   VARCHAR(20),    -- low | medium | high | critical
    -- Jenis Ancaman
    pii_detected               BOOLEAN DEFAULT FALSE,
    pii_types                  TEXT[],         -- ['email','phone','nik','ktp']
    prompt_injection_detected  BOOLEAN DEFAULT FALSE,
    injection_pattern          TEXT,
    excessive_agency           BOOLEAN DEFAULT FALSE,
    supply_chain_risk          BOOLEAN DEFAULT FALSE,
    -- Tindakan
    action_taken               VARCHAR(100),   -- blocked | warned | logged | passed
    flagged_content            TEXT,
    resolved                   BOOLEAN DEFAULT FALSE,
    resolved_at                TIMESTAMPTZ,
    notes                      TEXT
);

-- ============================================================
-- TABLE: revenue_ledger  (Rp20.000/user registrasi)
-- ============================================================
CREATE TABLE IF NOT EXISTS revenue_ledger (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    amount_idr      INTEGER DEFAULT 20000,
    event_type      VARCHAR(50) DEFAULT 'new_registration',
    credited_at     TIMESTAMPTZ DEFAULT NOW(),
    -- Payout tracking
    payout_id       UUID,
    payout_status   VARCHAR(50) DEFAULT 'pending',  -- pending | processing | paid | failed
    payout_method   VARCHAR(50) DEFAULT 'gopay',
    payout_requested_at   TIMESTAMPTZ,
    payout_completed_at   TIMESTAMPTZ
);

-- ============================================================
-- TABLE: payout_requests  (GoPay disbursement)
-- ============================================================
CREATE TABLE IF NOT EXISTS payout_requests (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    requested_at        TIMESTAMPTZ DEFAULT NOW(),
    amount_idr          INTEGER NOT NULL,
    user_count          INTEGER NOT NULL,
    gopay_phone         VARCHAR(20),
    gopay_reference_id  VARCHAR(255),
    gopay_status        VARCHAR(50) DEFAULT 'pending',
    gopay_response      JSONB,
    completed_at        TIMESTAMPTZ,
    notes               TEXT
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX idx_users_email         ON users(email);
CREATE INDEX idx_users_created_at    ON users(created_at);
CREATE INDEX idx_ml_user_id          ON model_logs(user_id);
CREATE INDEX idx_ml_logged_at        ON model_logs(logged_at);
CREATE INDEX idx_ml_model_name       ON model_logs(model_name);
CREATE INDEX idx_sa_user_id          ON security_audit(user_id);
CREATE INDEX idx_sa_detected_at      ON security_audit(detected_at);
CREATE INDEX idx_sa_owasp            ON security_audit(owasp_category);
CREATE INDEX idx_rl_user_id          ON revenue_ledger(user_id);
CREATE INDEX idx_rl_payout_status    ON revenue_ledger(payout_status);

-- ============================================================
-- TRIGGER: auto-credit Rp20.000 saat user baru registrasi
-- ============================================================
CREATE OR REPLACE FUNCTION fn_credit_revenue_on_register()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO revenue_ledger (user_id, amount_idr, event_type)
    VALUES (NEW.id, 20000, 'new_registration');

    UPDATE users SET revenue_credited = TRUE WHERE id = NEW.id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_credit_revenue
AFTER INSERT ON users
FOR EACH ROW EXECUTE FUNCTION fn_credit_revenue_on_register();

-- ============================================================
-- VIEW: dashboard_summary  (siap pakai untuk grafik)
-- ============================================================
CREATE OR REPLACE VIEW v_dashboard_summary AS
SELECT
    -- Users
    COUNT(DISTINCT u.id)                                                        AS total_users,
    COUNT(DISTINCT CASE WHEN u.created_at >= CURRENT_DATE THEN u.id END)        AS new_users_today,
    COUNT(DISTINCT CASE WHEN u.created_at >= DATE_TRUNC('month', NOW())
                        THEN u.id END)                                          AS new_users_this_month,
    -- DAU / MAU
    COUNT(DISTINCT CASE WHEN ml.logged_at >= CURRENT_DATE
                        THEN ml.user_id END)                                    AS dau,
    COUNT(DISTINCT CASE WHEN ml.logged_at >= DATE_TRUNC('month', NOW())
                        THEN ml.user_id END)                                    AS mau,
    -- Cost
    ROUND(SUM(ml.cost_idr), 2)                                                  AS total_cost_idr,
    ROUND(AVG(ml.cost_idr), 4)                                                  AS avg_cost_per_req_idr,
    -- Performance
    ROUND(AVG(ml.latency_ms), 2)                                                AS avg_latency_ms,
    SUM(ml.total_tokens)                                                        AS total_tokens_used,
    -- Revenue
    COUNT(DISTINCT CASE WHEN u.revenue_credited THEN u.id END) * 20000         AS total_revenue_idr,
    COUNT(DISTINCT CASE WHEN u.created_at >= DATE_TRUNC('month', NOW())
                        AND u.revenue_credited THEN u.id END) * 20000          AS revenue_this_month_idr
FROM users u
LEFT JOIN model_logs ml ON u.id = ml.user_id
WHERE u.is_active = TRUE;