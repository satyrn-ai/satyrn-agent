"""Satyrn runtime decode-policy ownership."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ds4py.engine.decode import PlainStep

from .config import DFlashMode
from .dflash import DFlashStep
from .errors import DFlashUnavailable

if TYPE_CHECKING:
    from ds4py.engine.decode import DecodeStep

    from ._native import DFlashNative
    from .config import SatyrnConfig


def select_step(
    native: DFlashNative,
    config: SatyrnConfig,
    engine_raw: int,
    session_raw: int,
    backend: str,
) -> DecodeStep:
    """Resolve auto/on/off once; never reinterpret policy during a round."""
    if config.dflash is DFlashMode.OFF or config.drafter_path is None:
        return PlainStep()
    reason: str | None = None
    rows = 0
    if missing := native.missing_dflash:
        reason = f"DFlash bindings are missing: {', '.join(missing)}"
    elif backend != "metal":
        reason = f"DFlash requires Metal, not {backend}"
    elif not native.has_dflash(engine_raw):
        reason = "DFlash requires a loaded drafter"
    else:
        rows = native.verify_rows(engine_raw)
        if rows == 0:
            reason = "DFlash requires at least one verify row"
    if reason is not None:
        if config.dflash is DFlashMode.ON:
            raise DFlashUnavailable(reason)
        return PlainStep()
    native.set_verify_mode(session_raw, 1)
    return DFlashStep(native, draft_tokens=config.draft_tokens, verify_rows=rows)
