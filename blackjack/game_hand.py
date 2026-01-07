from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

from .game_cards import Card

@dataclass
class Hand:
    cards: List[Card] = field(default_factory=list)
    bet: float = 0.0
    is_split_aces: bool = False
    is_split: bool = False
    surrendered: bool = False

    def add_card(self, card: Card) -> None:
        self.cards.append(card)

    @property
    def values(self) -> List[int]:
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
    def is_blackjack(self) -> bool:
        return len(self.cards) == 2 and self.best_value == 21

    @property
    def is_bust(self) -> bool:
        return min(self.values) > 21

    @property
    def can_split(self) -> bool:
        return len(self.cards) == 2 and self.cards[0].rank == self.cards[1].rank
