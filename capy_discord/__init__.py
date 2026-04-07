from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from capy_discord.bot import Bot

    instance: Bot | None = None

_instance: Bot | None = None


def __getattr__(name: str) -> object:
    if name == "instance":
        warnings.warn(
            "capy_discord.instance is deprecated. Use dependency injection.",
            DeprecationWarning,
            stacklevel=2,
        )
        return _instance

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
