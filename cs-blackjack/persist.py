from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .rules import Rules

STATE_PATH = Path.home() / ".cs-blackjack_state.json"
DEFAULT_BANKROLL = 10_000.0
SIDE_BET_KEYS = ("power_poker", "star21", "dealer_buster")

# Bumped whenever the shape of the saved JSON changes in a way an older copy
# of the game couldn't read. Version 1 files (everything written before this
# key existed) simply lack it -- load_state() treats a missing key as 1.
# Version 3 stopped saving lifetime/session stats here: they live in the
# history database now. A `stats` block found in an older file is carried
# along untouched until the database has imported it (see legacy stats below).
STATE_SCHEMA_VERSION = 3

State = Tuple[float, Rules, List[float], List[Dict[str, float]]]

_load_warning: Optional[str] = None
# The `stats` block of an older state file that the history database hasn't
# imported yet. Kept and written back on every save until then, so that
# lifetime numbers from before the database existed can never be lost just
# because the database was unavailable for a launch.
_pending_legacy_stats: Optional[dict] = None


def take_load_warning() -> Optional[str]:
    """A one-time note about anything load_state() had to work around (a
    corrupt save file set aside), for the UI to show once; None otherwise."""
    global _load_warning
    warning, _load_warning = _load_warning, None
    return warning


def _default_wagers(default_bet: float) -> List[float]:
    return [default_bet, 0.0, 0.0]


def _default_side_bet_wagers() -> List[Dict[str, float]]:
    return [{key: 0.0 for key in SIDE_BET_KEYS} for _ in range(3)]


def _default_state() -> State:
    rules = Rules()
    return (
        DEFAULT_BANKROLL,
        rules,
        _default_wagers(rules.default_bet),
        _default_side_bet_wagers(),
    )


def pending_legacy_stats() -> Optional[dict]:
    return _pending_legacy_stats


def set_legacy_stats(block: Optional[dict]) -> None:
    global _pending_legacy_stats
    _pending_legacy_stats = block or None


def clear_legacy_stats() -> None:
    """Called once the history database has imported the legacy stats."""
    set_legacy_stats(None)


def read_legacy_stats(path: Path) -> Optional[dict]:
    """The `stats` block of a state file if it holds any play history at
    all, else None. Never raises."""
    try:
        block = json.loads(path.read_text(encoding="utf8")).get("stats")
    except (ValueError, OSError, AttributeError):
        return None
    if isinstance(block, dict) and any(block.values()):
        return block
    return None


def read_state_file(path: Path) -> State:
    """Parse one saved-state file. Raises ValueError/TypeError/KeyError/
    AttributeError/OSError if it's unreadable or malformed -- callers decide
    whether that's fatal (a backup restore) or just falls back to defaults
    (load_state)."""
    data = json.loads(path.read_text(encoding="utf8"))
    # data["schema_version"] (absent = 1) needs no migration yet: version 2
    # only added the key itself. Future format changes upgrade `data` here,
    # before anything below reads it.
    bankroll = float(data.get("bankroll", DEFAULT_BANKROLL))
    rules = Rules.from_dict(data.get("rules", {})) if data.get("rules") else Rules()

    wagers = data.get("wagers")
    wagers = [float(w) for w in wagers] if wagers and len(wagers) == 3 else _default_wagers(rules.default_bet)

    raw_sb = data.get("side_bet_wagers")
    if raw_sb and len(raw_sb) == 3:
        side_bet_wagers = [{key: float(d.get(key, 0.0)) for key in SIDE_BET_KEYS} for d in raw_sb]
    else:
        side_bet_wagers = _default_side_bet_wagers()

    return bankroll, rules, wagers, side_bet_wagers


def load_state() -> State:
    """Return (bankroll, rules, wagers, side_bet_wagers).

    Falls back to fresh defaults on any missing or corrupt state file
    rather than crashing the game. A corrupt file is renamed aside first
    (never left in place to be silently overwritten by the next save), and
    take_load_warning() reports where it went.
    """
    global _load_warning
    if STATE_PATH.exists():
        try:
            state = read_state_file(STATE_PATH)
            set_legacy_stats(read_legacy_stats(STATE_PATH))
            return state
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            aside = STATE_PATH.with_name(f"{STATE_PATH.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
            try:
                os.replace(STATE_PATH, aside)
                _load_warning = f"Saved state was unreadable -- set aside as {aside.name}; starting fresh."
            except OSError:
                _load_warning = "Saved state was unreadable; starting fresh."
    return _default_state()


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then rename over the
    target -- a crash or full disk mid-write leaves the previous file
    intact instead of a truncated one."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def save_state(
    bankroll: float,
    rules: Rules,
    wagers: List[float],
    side_bet_wagers: List[Dict[str, float]],
) -> bool:
    """Persist everything; returns False (rather than raising) if the write
    failed, so a read-only disk never takes the game down with it."""
    data = {
        "schema_version": STATE_SCHEMA_VERSION,
        "bankroll": bankroll,
        "rules": rules.to_dict(),
        "wagers": list(wagers),
        "side_bet_wagers": [dict(d) for d in side_bet_wagers],
    }
    if _pending_legacy_stats:
        data["stats"] = _pending_legacy_stats  # not imported into the database yet -- keep it safe
    try:
        atomic_write_text(STATE_PATH, json.dumps(data, indent=2))
    except OSError:
        return False
    return True
