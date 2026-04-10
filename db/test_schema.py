# ruff: noqa
"""Verifies the local telemetry Postgres schema matches the tech spec."""

import psycopg2
import psycopg2.extras

DSN = "postgresql://capy:capy@localhost:5432/capy_dev"


def test_tables_exist(cur) -> None:
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    tables = {row[0] for row in cur.fetchall()}
    assert "telemetry_interactions" in tables, "Missing: telemetry_interactions"
    assert "telemetry_completions" in tables, "Missing: telemetry_completions"


def test_interactions_columns(cur) -> None:
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'telemetry_interactions'
        ORDER BY ordinal_position
    """)
    cols = {row[0]: {"type": row[1], "nullable": row[2]} for row in cur.fetchall()}

    assert cols["id"]["type"] == "bigint"
    assert cols["correlation_id"]["type"] == "character varying"
    assert cols["user_id"]["type"] == "bigint"
    assert cols["guild_id"]["nullable"] == "YES"  # nullable (DMs)
    assert cols["guild_name"]["nullable"] == "YES"  # nullable (DMs); name as of event time
    assert cols["command_name"]["nullable"] == "YES"  # nullable (buttons, modals)
    assert cols["options"]["type"] == "jsonb"
    assert cols["timestamp"]["type"] == "timestamp with time zone"
    assert "username" not in cols, "username should not be stored"


def test_completions_check_constraint(cur) -> None:
    # Inserting an invalid status should fail
    try:
        cur.execute("""
            INSERT INTO telemetry_completions
                (correlation_id, timestamp, command_name, status)
            VALUES ('zzzzzzzzzzzz', NOW(), 'test', 'bad_status')
        """)
        cur.connection.rollback()
        raise AssertionError("CHECK constraint did not fire!")
    except psycopg2.errors.CheckViolation:
        cur.connection.rollback()


def test_indexes_exist(cur) -> None:
    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY indexname
    """)
    indexes = {row[0] for row in cur.fetchall()}
    expected = {
        "idx_interactions_timestamp",
        "idx_interactions_correlation_id",
        "idx_interactions_command_name",
        "idx_completions_timestamp",
        "idx_completions_correlation_id",
        "idx_completions_command_status",
    }
    missing = expected - indexes
    assert not missing, f"Missing indexes: {missing}"


def test_seed_data_queries(cur) -> None:
    cur.execute("SELECT COUNT(*) FROM telemetry_interactions")
    count = cur.fetchone()[0]
    assert count > 0, "No seed data in telemetry_interactions"

    # Top commands query from tech spec
    cur.execute("""
        SELECT
            i.command_name,
            COUNT(i.id) AS invocations,
            ROUND(AVG(c.duration_ms), 1) AS avg_latency_ms,
            ROUND(
                SUM(CASE WHEN c.status = 'success' THEN 1 ELSE 0 END)::numeric
                / NULLIF(COUNT(c.id), 0), 2
            ) AS success_rate
        FROM telemetry_interactions i
        LEFT JOIN telemetry_completions c ON i.correlation_id = c.correlation_id
        WHERE i.command_name IS NOT NULL
        GROUP BY i.command_name
        ORDER BY invocations DESC
        LIMIT 10
    """)
    rows = cur.fetchall()
    assert len(rows) > 0, "Top commands query returned no results"
    for _row in rows:
        pass


def test_error_breakdown(cur) -> None:
    cur.execute("""
        SELECT error_type, COUNT(*) AS count
        FROM telemetry_completions
        WHERE error_type IS NOT NULL
        GROUP BY error_type
        ORDER BY count DESC
    """)
    rows = cur.fetchall()
    assert len(rows) > 0, "No error rows found (check seed data)"


def run_all() -> None:
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    tests = [
        test_tables_exist,
        test_interactions_columns,
        test_completions_check_constraint,
        test_indexes_exist,
        test_seed_data_queries,
        test_error_breakdown,
    ]
    passed = 0
    for t in tests:
        try:
            t(cur)
            passed += 1
        except AssertionError:
            pass
    cur.close()
    conn.close()


if __name__ == "__main__":
    run_all()
