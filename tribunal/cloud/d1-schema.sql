-- Tribunal cloud — D1 schema
--
-- D1 charges per row scanned, so we keep this schema deliberately tiny:
-- only the summary rows that the dashboard *needs* to filter and group on.
-- Full event payloads live in R2 as gzipped JSON Lines, partitioned by
-- date (YYYY/MM/DD/HH/<session_id>.jsonl.gz). The worker copies the
-- minimal subset here for dashboard queries.

CREATE TABLE IF NOT EXISTS orgs (
    id            TEXT PRIMARY KEY,            -- ULID
    name          TEXT NOT NULL,
    plan          TEXT NOT NULL DEFAULT 'oss',  -- 'oss' | 'team' | 'compliance'
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL DEFAULT 0,
    stripe_customer_id  TEXT,
    stripe_subscription_id TEXT,
    subscription_status TEXT NOT NULL DEFAULT 'none', -- 'none' | 'active' | 'past_due' | 'canceled'
    seat_limit    INTEGER NOT NULL DEFAULT 0,
    retention_days INTEGER NOT NULL DEFAULT 90
);

-- Users are global (one row per human across orgs). Membership is a
-- separate table so the same person can later join multiple orgs.
CREATE TABLE IF NOT EXISTS users (
    id                TEXT PRIMARY KEY,         -- ULID / random hex
    email             TEXT NOT NULL,
    name              TEXT,
    avatar_url        TEXT,
    provider          TEXT NOT NULL DEFAULT 'github',
    provider_user_id  TEXT NOT NULL,
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL,
    last_seen_at      INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS users_email_idx ON users(email);
CREATE UNIQUE INDEX IF NOT EXISTS users_provider_idx ON users(provider, provider_user_id);

CREATE TABLE IF NOT EXISTS org_members (
    org_id        TEXT NOT NULL REFERENCES orgs(id),
    user_id       TEXT NOT NULL REFERENCES users(id),
    role          TEXT NOT NULL DEFAULT 'member', -- 'owner' | 'admin' | 'member' | 'viewer'
    created_at    INTEGER NOT NULL,
    PRIMARY KEY (org_id, user_id)
);
CREATE INDEX IF NOT EXISTS org_members_user_idx ON org_members(user_id);

CREATE TABLE IF NOT EXISTS ingestion_tokens (
    id            TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL REFERENCES orgs(id),
    user_id       TEXT REFERENCES users(id),
    name          TEXT NOT NULL,
    token_hash    TEXT NOT NULL,                -- sha256(token)
    created_at    INTEGER NOT NULL,
    last_used_at  INTEGER,
    revoked_at    INTEGER
);
CREATE INDEX IF NOT EXISTS ingestion_tokens_hash_idx ON ingestion_tokens(token_hash);
CREATE INDEX IF NOT EXISTS ingestion_tokens_org_idx ON ingestion_tokens(org_id);

-- One row per event we accept. Payload is NOT stored here — keep this
-- table narrow so D1 scans are cheap. Use `r2_object_key` to fetch the
-- full event from R2 when needed.
CREATE TABLE IF NOT EXISTS event_summary (
    id            TEXT PRIMARY KEY,             -- event.event_id
    org_id        TEXT NOT NULL REFERENCES orgs(id),
    user_id       TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    agent         TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    epoch_ms      INTEGER NOT NULL,
    repo_path     TEXT,
    cost_usd      REAL DEFAULT 0,
    policy_decision TEXT,                       -- allow|warn|ask|deny|NULL
    policy_rule   TEXT,
    injection_severity TEXT,                    -- low|medium|high|NULL
    r2_object_key TEXT NOT NULL                 -- full event location in R2
);

-- Queries we expect — every dashboard view should hit at least one index:
CREATE INDEX IF NOT EXISTS event_org_time_idx
    ON event_summary(org_id, epoch_ms DESC);
CREATE INDEX IF NOT EXISTS event_session_idx
    ON event_summary(session_id);
CREATE INDEX IF NOT EXISTS event_agent_idx
    ON event_summary(org_id, agent, epoch_ms DESC);
CREATE INDEX IF NOT EXISTS event_type_idx
    ON event_summary(org_id, event_type, epoch_ms DESC);
CREATE INDEX IF NOT EXISTS event_policy_idx
    ON event_summary(org_id, policy_decision, epoch_ms DESC);
CREATE INDEX IF NOT EXISTS event_user_idx
    ON event_summary(org_id, user_id, epoch_ms DESC);

-- Hourly cost rollup. Worker aggregator updates these every minute so
-- the cost page never scans event_summary directly.
CREATE TABLE IF NOT EXISTS cost_hourly (
    org_id        TEXT NOT NULL REFERENCES orgs(id),
    hour_epoch_ms INTEGER NOT NULL,             -- floor(epoch_ms / 3600000) * 3600000
    user_id       TEXT NOT NULL,
    agent         TEXT NOT NULL,
    model         TEXT NOT NULL DEFAULT '',
    repo_path     TEXT,
    total_usd     REAL NOT NULL DEFAULT 0,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    event_count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (org_id, hour_epoch_ms, user_id, agent, model, repo_path)
);
CREATE INDEX IF NOT EXISTS cost_org_hour_idx ON cost_hourly(org_id, hour_epoch_ms DESC);

-- Per-session timeline metadata for the sessions page.
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,             -- session_id
    org_id        TEXT NOT NULL REFERENCES orgs(id),
    user_id       TEXT NOT NULL,
    agent         TEXT NOT NULL,
    start_epoch_ms INTEGER NOT NULL,
    end_epoch_ms  INTEGER,
    event_count   INTEGER NOT NULL DEFAULT 0,
    tool_count    INTEGER NOT NULL DEFAULT 0,
    policy_blocks INTEGER NOT NULL DEFAULT 0,
    injection_alerts INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    repo_path     TEXT,
    title         TEXT                          -- first prompt, truncated
);
CREATE INDEX IF NOT EXISTS sessions_org_time_idx ON sessions(org_id, start_epoch_ms DESC);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(org_id, user_id, start_epoch_ms DESC);

-- Custom policy packs uploaded by orgs (shipped packs live in code).
CREATE TABLE IF NOT EXISTS policy_packs (
    id            TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL REFERENCES orgs(id),
    name          TEXT NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    yaml_body     TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS policy_pack_org_name_idx ON policy_packs(org_id, name);

-- Audit log of dashboard actions (who toggled which pack, etc.).
CREATE TABLE IF NOT EXISTS dashboard_audit (
    id            TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    action        TEXT NOT NULL,                -- 'policy.enable', 'token.create', ...
    target        TEXT,
    metadata_json TEXT,
    epoch_ms      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS dashboard_audit_org_idx ON dashboard_audit(org_id, epoch_ms DESC);
