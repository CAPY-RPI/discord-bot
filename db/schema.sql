CREATE TABLE telemetry_interactions (
    id               BIGSERIAL     PRIMARY KEY,
    correlation_id   VARCHAR(12)   NOT NULL,
    timestamp        TIMESTAMPTZ   NOT NULL,
    received_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    interaction_type VARCHAR(20)   NOT NULL,
    user_id          BIGINT        NOT NULL,
    command_name     VARCHAR(100),
    guild_id         BIGINT,
    guild_name       VARCHAR(100),
    channel_id       BIGINT        NOT NULL,
    options          JSONB         NOT NULL DEFAULT '{}',
    bot_version      VARCHAR(20)   NOT NULL DEFAULT 'unknown'
);

CREATE TABLE telemetry_completions (
    id             BIGSERIAL     PRIMARY KEY,
    correlation_id VARCHAR(12)   NOT NULL,
    timestamp      TIMESTAMPTZ   NOT NULL,
    received_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    command_name   VARCHAR(100)  NOT NULL,
    status         VARCHAR(20)   NOT NULL,
    duration_ms    NUMERIC(10,2),
    error_type     VARCHAR(100),

    CONSTRAINT chk_completion_status
        CHECK (status IN ('success', 'user_error', 'internal_error'))
);

-- Indexes (telemetry_interactions)
CREATE INDEX idx_interactions_timestamp      ON telemetry_interactions (timestamp);
CREATE INDEX idx_interactions_correlation_id ON telemetry_interactions (correlation_id);
CREATE INDEX idx_interactions_command_name   ON telemetry_interactions (command_name, timestamp) WHERE command_name IS NOT NULL;

-- Indexes (telemetry_completions)
CREATE INDEX idx_completions_timestamp       ON telemetry_completions (timestamp);
CREATE INDEX idx_completions_correlation_id  ON telemetry_completions (correlation_id);
CREATE INDEX idx_completions_command_status  ON telemetry_completions (command_name, status);
