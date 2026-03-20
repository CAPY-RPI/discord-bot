"""Internal-safe direct message helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

DEFAULT_MAX_RECIPIENTS = 25
MAX_MESSAGE_LENGTH = 2000
MAX_PREVIEW_NAMES = 10


class DmSafetyError(ValueError):
    """Raised when a DM operation violates safety constraints."""


@dataclass(frozen=True, slots=True)
class Policy:
    """Allowlist and cap used to validate a DM request."""

    allowed_user_ids: frozenset[int] = frozenset()
    allowed_role_ids: frozenset[int] = frozenset()
    max_recipients: int = DEFAULT_MAX_RECIPIENTS

    def __post_init__(self) -> None:
        """Validate policy bounds."""
        if self.max_recipients < 1:
            msg = "DM policy max_recipients must be at least 1."
            raise DmSafetyError(msg)


@dataclass(slots=True)
class MessagePayload:
    """Normalized message content for DM sending."""

    content: str


@dataclass(slots=True)
class AudiencePreview:
    """Resolved recipient set and preview metadata."""

    recipients: list[discord.Member]
    skipped_ids: list[int] = field(default_factory=list)
    source_user_ids: tuple[int, ...] = ()
    source_role_ids: tuple[int, ...] = ()

    @property
    def recipient_count(self) -> int:
        """Return the number of unique resolved recipients."""
        return len(self.recipients)


@dataclass(slots=True)
class Draft:
    """Validated DM draft ready for preview or sending."""

    guild_id: int
    preview: AudiencePreview
    payload: MessagePayload
    policy: Policy
    created_at: datetime = field(default_factory=lambda: datetime.now(ZoneInfo("UTC")))


@dataclass(slots=True)
class SendResult:
    """Result of a DM batch send."""

    sent_count: int = 0
    failed_ids: list[int] = field(default_factory=list)


class DirectMessenger:
    """Compose and send direct messages through explicit audience policies."""

    def __init__(self) -> None:
        """Initialize the DM service logger."""
        self.log = logging.getLogger(__name__)

    async def compose(
        self,
        guild: discord.Guild,
        content: str,
        *,
        user_ids: tuple[int, ...] = (),
        role_ids: tuple[int, ...] = (),
        policy: Policy | None = None,
    ) -> Draft:
        """Validate the requested audience and return a DM draft."""
        return await self._compose(
            guild,
            content,
            user_ids=user_ids,
            role_ids=role_ids,
            policy=self._resolve_policy(policy),
        )

    async def compose_to_user(
        self,
        guild: discord.Guild,
        user_id: int,
        content: str,
        *,
        policy: Policy | None = None,
    ) -> Draft:
        """Compose a DM draft for a single user."""
        return await self.compose(guild, content, user_ids=(user_id,), policy=policy)

    async def compose_to_users(
        self,
        guild: discord.Guild,
        user_ids: tuple[int, ...],
        content: str,
        *,
        policy: Policy | None = None,
    ) -> Draft:
        """Compose a DM draft for explicit users."""
        return await self.compose(guild, content, user_ids=user_ids, policy=policy)

    async def compose_to_role(
        self,
        guild: discord.Guild,
        role_id: int,
        content: str,
        *,
        policy: Policy | None = None,
    ) -> Draft:
        """Compose a DM draft for a single role."""
        return await self.compose(guild, content, role_ids=(role_id,), policy=policy)

    async def compose_to_roles(
        self,
        guild: discord.Guild,
        role_ids: tuple[int, ...],
        content: str,
        *,
        policy: Policy | None = None,
    ) -> Draft:
        """Compose a DM draft for explicit roles."""
        return await self.compose(guild, content, role_ids=role_ids, policy=policy)

    async def send(self, guild: discord.Guild, draft: Draft) -> SendResult:
        """Send a validated DM draft."""
        if draft.guild_id != guild.id:
            msg = "DM draft guild does not match the provided guild."
            raise DmSafetyError(msg)

        self._validate_send_policy(draft.policy, draft.preview)
        result = SendResult()

        for recipient in draft.preview.recipients:
            try:
                await recipient.send(
                    draft.payload.content,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                result.sent_count += 1
            except (discord.Forbidden, discord.HTTPException):
                result.failed_ids.append(recipient.id)

        self.log.info(
            "DM batch complete guild=%s recipients=%s sent=%s failed=%s",
            guild.id,
            draft.preview.recipient_count,
            result.sent_count,
            len(result.failed_ids),
        )
        return result

    def render_preview(self, draft: Draft) -> str:
        """Render a compact preview for logging or operator review."""
        mentions = [recipient.mention for recipient in draft.preview.recipients[:MAX_PREVIEW_NAMES]]
        preview_mentions = ", ".join(mentions) if mentions else "None"
        if draft.preview.recipient_count > MAX_PREVIEW_NAMES:
            preview_mentions = f"{preview_mentions}, ..."

        return (
            f"DM draft for guild={draft.guild_id}\n"
            f"Recipients: {draft.preview.recipient_count}\n"
            f"Skipped IDs: {len(draft.preview.skipped_ids)}\n"
            f"Source user IDs: {len(draft.preview.source_user_ids)}\n"
            f"Source role IDs: {len(draft.preview.source_role_ids)}\n"
            f"Recipients preview: {preview_mentions}\n\n"
            f"Message:\n{draft.payload.content}"
        )

    async def _compose(
        self,
        guild: discord.Guild,
        content: str,
        *,
        user_ids: tuple[int, ...],
        role_ids: tuple[int, ...],
        policy: Policy,
    ) -> Draft:
        normalized_content = self._normalize_content(content)
        self._validate_requested_audience(user_ids, role_ids, policy, guild.default_role.id)
        preview = await self._resolve_audience(guild, user_ids=user_ids, role_ids=role_ids)
        self._validate_send_policy(policy, preview)

        draft = Draft(
            guild_id=guild.id,
            preview=preview,
            payload=MessagePayload(content=normalized_content),
            policy=policy,
        )
        self.log.info(
            "DM draft composed guild=%s users=%s roles=%s recipients=%s",
            guild.id,
            len(preview.source_user_ids),
            len(preview.source_role_ids),
            preview.recipient_count,
        )
        return draft

    def _resolve_policy(self, policy: Policy | None) -> Policy:
        if policy is not None:
            return policy

        return Policy()

    def _normalize_content(self, content: str) -> str:
        normalized = content.strip()
        if not normalized:
            msg = "DM content must not be empty."
            raise DmSafetyError(msg)
        if len(normalized) > MAX_MESSAGE_LENGTH:
            msg = f"DM content cannot exceed {MAX_MESSAGE_LENGTH} characters."
            raise DmSafetyError(msg)
        return normalized

    def _validate_requested_audience(
        self,
        user_ids: tuple[int, ...],
        role_ids: tuple[int, ...],
        policy: Policy,
        default_role_id: int,
    ) -> None:
        if not user_ids and not role_ids:
            msg = "DM request must include at least one explicit user ID or role ID."
            raise DmSafetyError(msg)

        if default_role_id in role_ids or default_role_id in policy.allowed_role_ids:
            msg = "The @everyone role cannot be used in DM policies or requests."
            raise DmSafetyError(msg)

        disallowed_users = set(user_ids) - set(policy.allowed_user_ids)
        if disallowed_users:
            msg = f"DM request includes user IDs outside the allowed policy: {sorted(disallowed_users)}"
            raise DmSafetyError(msg)

        disallowed_roles = set(role_ids) - set(policy.allowed_role_ids)
        if disallowed_roles:
            msg = f"DM request includes role IDs outside the allowed policy: {sorted(disallowed_roles)}"
            raise DmSafetyError(msg)

    async def _resolve_audience(
        self,
        guild: discord.Guild,
        *,
        user_ids: tuple[int, ...],
        role_ids: tuple[int, ...],
    ) -> AudiencePreview:
        recipients_by_id: dict[int, discord.Member] = {}
        skipped_ids: list[int] = []

        for user_id in user_ids:
            member = await self._resolve_member(guild, user_id)
            if member is None:
                skipped_ids.append(user_id)
                continue
            recipients_by_id[member.id] = member

        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role is None:
                skipped_ids.append(role_id)
                continue
            if role == guild.default_role:
                msg = "The @everyone role cannot be used for DMs."
                raise DmSafetyError(msg)
            for member in role.members:
                recipients_by_id[member.id] = member

        if not recipients_by_id:
            msg = "No recipients were resolved. Use explicit users or non-default roles."
            raise DmSafetyError(msg)

        return AudiencePreview(
            recipients=list(recipients_by_id.values()),
            skipped_ids=skipped_ids,
            source_user_ids=user_ids,
            source_role_ids=role_ids,
        )

    def _validate_send_policy(self, policy: Policy, preview: AudiencePreview) -> None:
        if preview.recipient_count > policy.max_recipients:
            msg = (
                f"Resolved audience has {preview.recipient_count} recipients, "
                f"which exceeds the cap of {policy.max_recipients}."
            )
            raise DmSafetyError(msg)

    async def _resolve_member(self, guild: discord.Guild, user_id: int) -> discord.Member | None:
        member = guild.get_member(user_id)
        if member is not None:
            return member

        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None


_MESSENGER = DirectMessenger()


async def compose(
    guild: discord.Guild,
    content: str,
    *,
    user_ids: tuple[int, ...] = (),
    role_ids: tuple[int, ...] = (),
    policy: Policy | None = None,
) -> Draft:
    """Compose a DM draft through the shared messenger."""
    return await _MESSENGER.compose(guild, content, user_ids=user_ids, role_ids=role_ids, policy=policy)


async def compose_to_user(
    guild: discord.Guild,
    user_id: int,
    content: str,
    *,
    policy: Policy | None = None,
) -> Draft:
    """Compose a DM draft for a single user."""
    return await _MESSENGER.compose_to_user(guild, user_id, content, policy=policy)


async def compose_to_users(
    guild: discord.Guild,
    user_ids: tuple[int, ...],
    content: str,
    *,
    policy: Policy | None = None,
) -> Draft:
    """Compose a DM draft for explicit users."""
    return await _MESSENGER.compose_to_users(guild, user_ids, content, policy=policy)


async def compose_to_role(
    guild: discord.Guild,
    role_id: int,
    content: str,
    *,
    policy: Policy | None = None,
) -> Draft:
    """Compose a DM draft for a single role."""
    return await _MESSENGER.compose_to_role(guild, role_id, content, policy=policy)


async def compose_to_roles(
    guild: discord.Guild,
    role_ids: tuple[int, ...],
    content: str,
    *,
    policy: Policy | None = None,
) -> Draft:
    """Compose a DM draft for explicit roles."""
    return await _MESSENGER.compose_to_roles(guild, role_ids, content, policy=policy)


async def send(guild: discord.Guild, draft: Draft) -> SendResult:
    """Send a previously composed draft through the shared messenger."""
    return await _MESSENGER.send(guild, draft)


def render_preview(draft: Draft) -> str:
    """Render a compact preview for a draft."""
    return _MESSENGER.render_preview(draft)
