"""Safe policy helpers for direct messaging."""

from __future__ import annotations

from capy_discord.services.dm import DEFAULT_MAX_RECIPIENTS, Policy

DENY_ALL = Policy()


def allow_users(*user_ids: int, max_recipients: int = DEFAULT_MAX_RECIPIENTS) -> Policy:
    """Build a policy that only permits the provided user IDs."""
    return Policy(
        allowed_user_ids=frozenset(user_ids),
        max_recipients=max_recipients,
    )


def allow_roles(*role_ids: int, max_recipients: int = DEFAULT_MAX_RECIPIENTS) -> Policy:
    """Build a policy that only permits the provided role IDs."""
    return Policy(
        allowed_role_ids=frozenset(role_ids),
        max_recipients=max_recipients,
    )


def allow_targets(
    *,
    user_ids: frozenset[int] = frozenset(),
    role_ids: frozenset[int] = frozenset(),
    max_recipients: int = DEFAULT_MAX_RECIPIENTS,
) -> Policy:
    """Build a policy that permits the provided user and role IDs."""
    return Policy(
        allowed_user_ids=user_ids,
        allowed_role_ids=role_ids,
        max_recipients=max_recipients,
    )
