-- Kexar database schema and seed data.
-- 
-- Apply with: psql "$DATABASE_URL" -f kexar/db/schema.sql
-- Or in Python: see scripts/init_db.py.
--
-- Three tables matching the architecture doc, section "Data model":
--   incidents:        seeded scenarios (read-only during demo)
--   incident_signals: per-incident logs / metrics / runbooks queried by MCP tools
--   runs:             written by the runtime; stores the event log for replay

-- Drop in reverse dependency order so re-running is clean.
DROP TABLE IF EXISTS runs CASCADE;
DROP TABLE IF EXISTS incident_signals CASCADE;
DROP TABLE IF EXISTS incidents CASCADE;


-- ============================================================================
-- incidents: one row per seeded scenario
-- ============================================================================

CREATE TABLE incidents (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,
    severity     TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    service      TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_incidents_service ON incidents(service);


-- ============================================================================
-- incident_signals: logs, metrics, runbooks queried by the MCP tools
-- ============================================================================

CREATE TABLE incident_signals (
    id           BIGSERIAL PRIMARY KEY,
    incident_id  TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    signal_type  TEXT NOT NULL CHECK (signal_type IN ('log', 'metric', 'runbook')),
    payload      JSONB NOT NULL,
    occurred_at  TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_signals_incident_type ON incident_signals(incident_id, signal_type);
CREATE INDEX idx_signals_occurred ON incident_signals(occurred_at);


-- ============================================================================
-- runs: written by the runtime
-- ============================================================================

CREATE TABLE runs (
    id            TEXT PRIMARY KEY,
    incident_id   TEXT REFERENCES incidents(id) ON DELETE SET NULL,
    status        TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'aborted')),
    started_at    TIMESTAMPTZ NOT NULL,
    ended_at      TIMESTAMPTZ,
    final_answer  TEXT,
    event_log     JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_runs_incident ON runs(incident_id);
CREATE INDEX idx_runs_status ON runs(status);


-- ============================================================================
-- Seed data: the "checkout-latency" incident from the demo script
-- ============================================================================

INSERT INTO incidents (id, title, description, severity, service, started_at) VALUES (
    'inc_checkout_latency',
    'Checkout API p99 latency spike',
    'p99 latency on POST /checkout jumped from 80ms to 4.2s starting at 02:14 UTC. Affects all customer purchases.',
    'high',
    'checkout',
    '2026-05-21 02:14:00+00'
);


-- Logs around the deploy that broke things
INSERT INTO incident_signals (incident_id, signal_type, payload, occurred_at) VALUES
    ('inc_checkout_latency', 'log',
     '{"service": "checkout", "level": "INFO", "msg": "Deploy 1f3a-prod started, rolling out v2.18.0"}',
     '2026-05-21 02:13:42+00'),
    ('inc_checkout_latency', 'log',
     '{"service": "checkout", "level": "INFO", "msg": "Deploy 1f3a-prod complete on all 8 pods"}',
     '2026-05-21 02:13:58+00'),
    ('inc_checkout_latency', 'log',
     '{"service": "checkout", "level": "WARN", "msg": "p99 latency 4231ms on POST /checkout", "trace_id": "abc-123"}',
     '2026-05-21 02:14:11+00'),
    ('inc_checkout_latency', 'log',
     '{"service": "checkout", "level": "WARN", "msg": "fraud-check call took 4180ms, normal is 50ms", "trace_id": "abc-123"}',
     '2026-05-21 02:14:11+00'),
    ('inc_checkout_latency', 'log',
     '{"service": "checkout", "level": "ERROR", "msg": "downstream timeout: fraud-service responded in 4200ms"}',
     '2026-05-21 02:15:03+00');


-- Metric samples showing the spike
INSERT INTO incident_signals (incident_id, signal_type, payload, occurred_at) VALUES
    ('inc_checkout_latency', 'metric',
     '{"service": "checkout", "metric": "p99_latency_ms", "value": 81}',
     '2026-05-21 02:10:00+00'),
    ('inc_checkout_latency', 'metric',
     '{"service": "checkout", "metric": "p99_latency_ms", "value": 79}',
     '2026-05-21 02:11:00+00'),
    ('inc_checkout_latency', 'metric',
     '{"service": "checkout", "metric": "p99_latency_ms", "value": 84}',
     '2026-05-21 02:12:00+00'),
    ('inc_checkout_latency', 'metric',
     '{"service": "checkout", "metric": "p99_latency_ms", "value": 88}',
     '2026-05-21 02:13:00+00'),
    ('inc_checkout_latency', 'metric',
     '{"service": "checkout", "metric": "p99_latency_ms", "value": 4231}',
     '2026-05-21 02:14:00+00'),
    ('inc_checkout_latency', 'metric',
     '{"service": "checkout", "metric": "p99_latency_ms", "value": 4180}',
     '2026-05-21 02:15:00+00'),
    ('inc_checkout_latency', 'metric',
     '{"service": "checkout", "metric": "p99_latency_ms", "value": 4205}',
     '2026-05-21 02:16:00+00'),
    ('inc_checkout_latency', 'metric',
     '{"service": "checkout", "metric": "error_rate_pct", "value": 0.1}',
     '2026-05-21 02:13:00+00'),
    ('inc_checkout_latency', 'metric',
     '{"service": "checkout", "metric": "error_rate_pct", "value": 3.8}',
     '2026-05-21 02:15:00+00');


-- The rollback runbook
INSERT INTO incident_signals (incident_id, signal_type, payload, occurred_at) VALUES
    ('inc_checkout_latency', 'runbook',
     '{
        "title": "Rollback a checkout deploy",
        "applies_to": ["checkout", "checkout-api"],
        "steps": [
            "Identify the bad deploy: kubectl rollout history deployment/checkout -n prod",
            "Roll back to previous: kubectl rollout undo deployment/checkout -n prod",
            "Wait for new pods to become ready (60s)",
            "Verify p99 drops below 200ms in the dashboard",
            "Post incident summary in #incidents channel"
        ],
        "owner": "platform-team",
        "estimated_recovery_minutes": 5
     }'::jsonb,
     '2026-01-15 00:00:00+00');
