from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict
import json

from .hand import Hand

Action = str  # 'hit', 'stand', 'double', 'split', 'surrender'


@dataclass
class BasicStrategy:
    """Strategy based on a matrix loaded from JSON.

    The JSON file is expected to contain three top level objects: ``hard``,
    ``soft`` and ``pair``.  Each maps a player's total (or pair rank) to a
    mapping of dealer up cards (``"2"``..``"10"``, ``"A"``) and the
    recommended action (``hit``, ``stand``, ``double``, ``split`` or
    ``surrender``).
    """

    hard: Dict[int, Dict[str, Action]] = field(default_factory=dict)
    soft: Dict[int, Dict[str, Action]] = field(default_factory=dict)
    pair: Dict[str, Dict[str, Action]] = field(default_factory=dict)

    @classmethod
    def from_json(
        cls, path: str, allow_surrender: bool = True
    ) -> "BasicStrategy":  # pragma: no cover - CLI helper
        """Create a strategy instance from ``path``.

        Missing sections in the JSON default to empty dictionaries which
        effectively cause the strategy to stand on every hand.
        ``allow_surrender`` replaces any "surrender" recommendations with
        "hit" when set to ``False``.
        """
        with open(path, "r", encoding="utf8") as f:
            data = json.load(f)
        hard = {int(k): v for k, v in data.get("hard", {}).items()}
        soft = {int(k): v for k, v in data.get("soft", {}).items()}
        pair = data.get("pair") or data.get("split") or {}
        if not allow_surrender:
            for table in (hard, soft, pair):
                for row in table.values():
                    for dealer, action in list(row.items()):
                        if action == "surrender":
                            row[dealer] = "hit"
        return cls(hard=hard, soft=soft, pair=pair)

    def _lookup(self, table: Dict, key, dealer_up: str) -> Action | None:
        row = table.get(key)
        if row:
            return row.get(dealer_up)
        return None

    def decide(self, hand: Hand, dealer_up: str, options: Dict[str, bool]) -> Action:
        """Return the recommended action for *hand* against *dealer_up*.

        ``options`` controls availability of ``double``, ``split`` and
        ``surrender``.
        """
        # Check for pair/split actions first
        if options.get("can_split") and hand.can_split:
            rank = hand.cards[0].rank
            action = self._lookup(self.pair, rank, dealer_up)
            if action == "split":
                return "split"

        total = hand.best_value
        soft = any(v <= 21 and v != total for v in hand.values)
        table = self.soft if soft else self.hard
        action = self._lookup(table, total, dealer_up)

        # Fallback when action requires an unavailable option
        if action == "double" and not options.get("can_double"):
            action = "hit"
        if action == "surrender" and not options.get("can_surrender"):
            action = "hit"

        return action or "stand"
