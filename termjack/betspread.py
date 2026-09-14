from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class BetSpreadRow:
    true_count: float
    hands: int
    wager_per_hand: float


@dataclass
class BetSpreadTable:
    """A player's own count-based bet-sizing reference table.

    Rows are thresholds: the applicable row for a given true count is the
    one with the largest true_count <= that count. The lowest-threshold row
    acts as a floor, catching every count below the next row up -- it's
    displayed as "Below +X" rather than its own (otherwise meaningless)
    threshold value.
    """

    rows: List[BetSpreadRow] = field(default_factory=list)

    def upsert(self, true_count: float, hands: int, wager_per_hand: float) -> None:
        for row in self.rows:
            if abs(row.true_count - true_count) < 1e-9:
                row.hands = hands
                row.wager_per_hand = wager_per_hand
                break
        else:
            self.rows.append(BetSpreadRow(true_count, hands, wager_per_hand))
        self.rows.sort(key=lambda r: r.true_count)

    def to_dict(self) -> dict:
        return {"rows": [{"true_count": r.true_count, "hands": r.hands, "wager_per_hand": r.wager_per_hand} for r in self.rows]}

    @classmethod
    def from_dict(cls, data: dict) -> "BetSpreadTable":
        table = cls()
        for r in (data or {}).get("rows", []) or []:
            try:
                table.rows.append(BetSpreadRow(float(r["true_count"]), int(r["hands"]), float(r["wager_per_hand"])))
            except (KeyError, TypeError, ValueError):
                continue
        table.rows.sort(key=lambda r: r.true_count)
        return table
