from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

from .rules import Rules
from .stats import Stats

STATE_PATH = Path.home() / ".termjack_state.json"
DEFAULT_BANKROLL = 10_000.0


def load_state() -> Tuple[float, Rules, Stats]:
    """Return (bankroll, rules, stats). Falls back to fresh defaults on any
    missing or corrupt state file rather than crashing the game."""
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf8"))
            bankroll = float(data.get("bankroll", DEFAULT_BANKROLL))
            rules = Rules.from_dict(data.get("rules", {})) if data.get("rules") else Rules()
            stats = Stats.from_dict(data.get("stats", {}), session_start_bankroll=bankroll)
            return bankroll, rules, stats
        except (json.JSONDecodeError, ValueError, TypeError, KeyError):
            pass
    return DEFAULT_BANKROLL, Rules(), Stats(session_start_bankroll=DEFAULT_BANKROLL)


def save_state(bankroll: float, rules: Rules, stats: Stats) -> None:
    data = {
        "bankroll": bankroll,
        "rules": rules.to_dict(),
        "stats": stats.to_dict(),
    }
    try:
        STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf8")
    except OSError:
        pass
