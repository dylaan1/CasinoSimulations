from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from .rules import Rules
from .stats import Stats

STATE_PATH = Path.home() / ".termjack_state.json"
DEFAULT_BANKROLL = 10_000.0
SIDE_BET_KEYS = ("power_poker", "star21", "dealer_buster")


def _default_wagers(default_bet: float) -> List[float]:
    return [default_bet, 0.0, 0.0]


def _default_side_bet_wagers() -> List[Dict[str, float]]:
    return [{key: 0.0 for key in SIDE_BET_KEYS} for _ in range(3)]


def load_state() -> Tuple[float, Rules, Stats, List[float], List[Dict[str, float]]]:
    """Return (bankroll, rules, stats, wagers, side_bet_wagers).

    Falls back to fresh defaults on any missing or corrupt state file
    rather than crashing the game.
    """
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf8"))
            bankroll = float(data.get("bankroll", DEFAULT_BANKROLL))
            rules = Rules.from_dict(data.get("rules", {})) if data.get("rules") else Rules()

            stats_data = data.get("stats") or {}
            if "lifetime_starting_bankroll" not in stats_data:
                stats_data = dict(stats_data)
                stats_data["lifetime_starting_bankroll"] = bankroll
            stats = Stats.from_dict(stats_data)

            wagers = data.get("wagers")
            wagers = [float(w) for w in wagers] if wagers and len(wagers) == 3 else _default_wagers(rules.default_bet)

            raw_sb = data.get("side_bet_wagers")
            if raw_sb and len(raw_sb) == 3:
                side_bet_wagers = [{key: float(d.get(key, 0.0)) for key in SIDE_BET_KEYS} for d in raw_sb]
            else:
                side_bet_wagers = _default_side_bet_wagers()

            return bankroll, rules, stats, wagers, side_bet_wagers
        except (json.JSONDecodeError, ValueError, TypeError, KeyError):
            pass

    rules = Rules()
    stats = Stats(lifetime_starting_bankroll=DEFAULT_BANKROLL)
    return DEFAULT_BANKROLL, rules, stats, _default_wagers(rules.default_bet), _default_side_bet_wagers()


def save_state(
    bankroll: float,
    rules: Rules,
    stats: Stats,
    wagers: List[float],
    side_bet_wagers: List[Dict[str, float]],
) -> None:
    data = {
        "bankroll": bankroll,
        "rules": rules.to_dict(),
        "stats": stats.to_dict(),
        "wagers": list(wagers),
        "side_bet_wagers": [dict(d) for d in side_bet_wagers],
    }
    try:
        STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf8")
    except OSError:
        pass
