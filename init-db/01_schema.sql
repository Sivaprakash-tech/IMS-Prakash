-- TimescaleDB extension lives in the same Postgres container.
-- One container, two roles: transactional (work_items/rca) and timeseries (signal_metrics).
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TYPE component_type AS ENUM ('CACHE', 'RDBMS', 'API', 'MCP', 'QUEUE', 'NOSQL');
CREATE TYPE severity_level AS ENUM ('INFO', 'WARN', 'ERROR', 'CRITICAL');
CREATE TYPE work_item_state AS ENUM ('OPEN', 'INVESTIGATING', 'RESOLVED', 'CLOSED');

CREATE TABLE work_items (
    id              BIGSERIAL PRIMARY KEY,
    component_id    TEXT NOT NULL,
    component_type  component_type NOT NULL,
    severity        severity_level NOT NULL,
    state           work_item_state NOT NULL DEFAULT 'OPEN',
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ,
    mttr_seconds    DOUBLE PRECISION,
    signal_count    INTEGER NOT NULL DEFAULT 1,
    summary         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_work_items_state      ON work_items(state);
CREATE INDEX idx_work_items_severity   ON work_items(severity);
CREATE INDEX idx_work_items_component  ON work_items(component_id);
CREATE INDEX idx_work_items_start_time ON work_items(start_time DESC);

CREATE TABLE rca (
    id                   BIGSERIAL PRIMARY KEY,
    work_item_id         BIGINT NOT NULL UNIQUE REFERENCES work_items(id) ON DELETE CASCADE,
    root_cause_category  TEXT NOT NULL,
    fix_applied          TEXT NOT NULL,
    prevention           TEXT NOT NULL,
    rca_start_time       TIMESTAMPTZ NOT NULL,
    rca_end_time         TIMESTAMPTZ NOT NULL,
    submitted_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT rca_fix_applied_not_blank   CHECK (length(btrim(fix_applied))   > 0),
    CONSTRAINT rca_prevention_not_blank    CHECK (length(btrim(prevention))    > 0),
    CONSTRAINT rca_category_not_blank      CHECK (length(btrim(root_cause_category)) > 0),
    CONSTRAINT rca_end_after_start         CHECK (rca_end_time >= rca_start_time)
);

-- Lightweight pointer to the Mongo signal documents for a work item.
-- Used for joins/counting; raw payloads stay in Mongo.
CREATE TABLE signal_links (
    id                BIGSERIAL,
    work_item_id      BIGINT NOT NULL,
    mongo_signal_id   TEXT NOT NULL,
    component_id      TEXT NOT NULL,
    severity          severity_level NOT NULL,
    signal_timestamp  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id, signal_timestamp)
);

CREATE INDEX idx_signal_links_work_item ON signal_links(work_item_id);

-- Aggregations sink: 1-minute buckets per (component_id, severity).
CREATE TABLE signal_metrics (
    bucket        TIMESTAMPTZ NOT NULL,
    component_id  TEXT NOT NULL,
    severity      severity_level NOT NULL,
    count         BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (bucket, component_id, severity)
);

SELECT create_hypertable('signal_metrics', 'bucket',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE);

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER work_items_touch_updated_at
    BEFORE UPDATE ON work_items
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
