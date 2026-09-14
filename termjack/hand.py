from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .cards import Card, TEN_VALUE_RANKS


@dataclass
class Hand:
    cards: List[Card] = field(default_factory=list)
    bet: float = 0.0

    # Lineage / status flags. All start False and are set by the engine as
    # the round progresses.
    is_split: bool = False
    is_split_aces: bool = False
    doubled: bool = False
    surrendered: bool = False
    stood: bool = False
    is_insured: bool = False
    even_money_taken: bool = False

    def add_card(self, card: Card) -> None:
        self.cards.append(card)

    @property
    def values(self) -> List[int]:
        """All distinct totals achievable by treating each Ace as 1 or 11."""
        totals = [0]
        for card in self.cards:
            if card.rank == "A":
                totals = [t + 1 for t in totals] + [t + 11 for t in totals]
            else:
                totals = [t + card.value for t in totals]
        return sorted(set(totals))

    @property
    def best_value(self) -> int:
        valid = [v for v in self.values if v <= 21]
        return max(valid) if valid else min(self.values)

    @property
    def is_soft(self) -> bool:
        """True if the best total counts an Ace as 11 (i.e. could still drop to a hard total)."""
        if not any(c.rank == "A" for c in self.cards):
            return False
        hard_total = sum(1 if c.rank == "A" else c.value for c in self.cards)
        return hard_total + 10 <= 21 and self.best_value == hard_total + 10

    @property
    def is_blackjack(self) -> bool:
        return len(self.cards) == 2 and not self.is_split and self.best_value == 21

    @property
    def is_bust(self) -> bool:
        return min(self.values) > 21

    @property
    def is_21(self) -> bool:
        return self.best_value == 21

    @property
    def can_split(self) -> bool:
        if len(self.cards) != 2:
            return False
        a, b = self.cards
        if a.rank == b.rank:
            return True
        return a.rank in TEN_VALUE_RANKS and b.rank in TEN_VALUE_RANKS

    @property
    def can_double(self) -> bool:
        return len(self.cards) == 2 and not self.doubled

    @property
    def is_resolved(self) -> bool:
        """True once no further player action is possible on this hand.

        This is the purely mechanical check. Whether a split-aces hand with
        two cards can be *resplit* depends on table rules (RSA, split max)
        that this class doesn't know about -- that's decided by the engine.
        """
        return (
            self.surrendered
            or self.stood
            or self.doubled
            or self.is_bust
            or self.is_blackjack
            or self.even_money_taken
        )

    def render_cards(self) -> str:
        return " ".join(str(c) for c in self.cards)
