"""Demo script to exercise in-memory telemetry metrics and print stats.

Run with: uv run python -c "import sys; sys.path.insert(0, '.'); exec(open('scripts/demo_stats.py').read())"
"""

import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, ".")

from capy_discord.exts.core.telemetry import TelemetryMetrics


def populate_metrics() -> TelemetryMetrics:
    """Simulate a bot session with realistic telemetry data."""
    m = TelemetryMetrics()
    m.boot_time = datetime.now(UTC) - timedelta(hours=2, minutes=15, seconds=42)

    interactions = [
        ("slash_command", "ping", 101, 9000),
        ("slash_command", "ping", 102, 9000),
        ("slash_command", "ping", 101, 9000),
        ("slash_command", "help", 103, 9000),
        ("slash_command", "help", 101, 9001),
        ("slash_command", "feedback", 104, 9000),
        ("slash_command", "stats", 101, 9000),
        ("button", "confirm_btn", 102, 9000),
        ("button", "cancel_btn", 103, 9000),
        ("modal", "feedback_form", 104, 9000),
        ("slash_command", "ping", 105, None),
    ]

    for itype, cmd, user_id, guild_id in interactions:
        m.total_interactions += 1
        m.interactions_by_type[itype] += 1
        if cmd:
            m.command_invocations[cmd] += 1
        m.unique_user_ids.add(user_id)
        if guild_id is not None:
            m.guild_interactions[guild_id] += 1

    completions = [
        ("ping", "success", 12.3, None),
        ("ping", "success", 8.7, None),
        ("ping", "success", 15.1, None),
        ("ping", "success", 9.4, None),
        ("help", "success", 22.0, None),
        ("help", "user_error", 5.2, "UserFriendlyError"),
        ("feedback", "success", 45.6, None),
        ("stats", "success", 3.1, None),
        ("ping", "internal_error", 2.0, "RuntimeError"),
        ("feedback", "internal_error", 100.5, "ValueError"),
    ]

    for cmd, status, duration, error_type in completions:
        m.completions_by_status[status] += 1
        m.command_latency[cmd].record(duration)
        if status != "success":
            m.command_failures[cmd][status] += 1
        if error_type:
            m.error_types[error_type] += 1

    return m


def _print_header(m: TelemetryMetrics) -> None:
    delta = datetime.now(UTC) - m.boot_time
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    print("=" * 50)  # noqa: T201
    print("  Bot Statistics")  # noqa: T201
    print(f"  Stats since last restart ({hours}h {minutes}m {seconds}s ago)")  # noqa: T201
    print("=" * 50)  # noqa: T201


def _print_overview(m: TelemetryMetrics) -> None:
    total_completions = sum(m.completions_by_status.values())
    successes = m.completions_by_status.get("success", 0)
    rate = (successes / total_completions * 100) if total_completions else 0.0
    print("\n--- Overview ---")  # noqa: T201
    print(f"  Total Interactions: {m.total_interactions}")  # noqa: T201
    print(f"  Unique Users:      {len(m.unique_user_ids)}")  # noqa: T201
    print(f"  Active Guilds:     {len(m.guild_interactions)}")  # noqa: T201
    print(f"  Success Rate:      {rate:.1f}%")  # noqa: T201


def _print_commands_and_types(m: TelemetryMetrics) -> None:
    if m.command_invocations:
        print("\n--- Top Commands ---")  # noqa: T201
        top = sorted(m.command_invocations.items(), key=lambda x: x[1], reverse=True)[:5]
        for cmd, count in top:
            latency = m.command_latency.get(cmd)
            avg = f" ({latency.avg_ms:.1f}ms avg)" if latency and latency.count else ""
            print(f"  /{cmd}: {count}{avg}")  # noqa: T201

    if m.interactions_by_type:
        print("\n--- Interaction Types ---")  # noqa: T201
        for itype, count in sorted(m.interactions_by_type.items()):
            print(f"  {itype}: {count}")  # noqa: T201

    if m.command_latency:
        print("\n--- Latency Details ---")  # noqa: T201
        for cmd in sorted(m.command_latency):
            s = m.command_latency[cmd]
            print(f"  /{cmd}: min={s.min_ms:.1f}ms  avg={s.avg_ms:.1f}ms  max={s.max_ms:.1f}ms  (n={s.count})")  # noqa: T201


def _print_errors(m: TelemetryMetrics) -> None:
    total_errors = sum(c for s, c in m.completions_by_status.items() if s != "success")
    if total_errors > 0:
        print("\n--- Errors ---")  # noqa: T201
        print(f"  User Errors:     {m.completions_by_status.get('user_error', 0)}")  # noqa: T201
        print(f"  Internal Errors: {m.completions_by_status.get('internal_error', 0)}")  # noqa: T201
        if m.error_types:
            print("  Top error types:")  # noqa: T201
            for etype, ecount in sorted(m.error_types.items(), key=lambda x: x[1], reverse=True):
                print(f"    {etype}: {ecount}")  # noqa: T201

    if m.command_failures:
        print("\n--- Failures by Command ---")  # noqa: T201
        for cmd, statuses in sorted(m.command_failures.items()):
            parts = [f"{s}={c}" for s, c in statuses.items()]
            print(f"  /{cmd}: {', '.join(parts)}")  # noqa: T201


def print_stats(m: TelemetryMetrics) -> None:
    """Print stats in a readable format."""
    _print_header(m)
    _print_overview(m)
    _print_commands_and_types(m)
    _print_errors(m)
    print("\n" + "=" * 50)  # noqa: T201
    print("  In-memory stats \u2014 resets on bot restart")  # noqa: T201
    print("=" * 50)  # noqa: T201


if __name__ == "__main__":
    metrics = populate_metrics()
    print_stats(metrics)
