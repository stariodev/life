import os
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True, slots=True)
class Config:
    """Every setting. A new setting is one field with a default.

    The board size and the tick rate are rules of the game, in `app/life/game.py`.
    `from_env` reads each field from the env var of the same name in capitals
    (`public_url` from `PUBLIC_URL`) and casts it to the type of the default.
    """

    # The address this copy is served at. Share previews need absolute links, so a
    # copy of your own sets it to its own address.
    public_url: str = "https://life.stario.dev"

    @classmethod
    def from_env(cls) -> Config:
        values: dict[str, Any] = {}
        for f in fields(cls):
            raw = os.environ.get(f.name.upper())
            if raw is None:
                continue
            if isinstance(f.default, bool):
                values[f.name] = raw.lower() in ("1", "true", "yes")
            else:
                values[f.name] = type(f.default)(raw)
        return cls(**values)
