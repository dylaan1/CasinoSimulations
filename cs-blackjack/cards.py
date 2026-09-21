from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List
import random

SUITS = ["spades", "hearts", "diamonds", "clubs"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

SUIT_GLYPHS = {"spades": "♠", "hearts": "♥", "diamonds": "♦", "clubs": "♣"}
RED_SUITS = {"hearts", "diamonds"}
TEN_VALUE_RANKS = {"10", "J", "Q", "K"}


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    @property
    def value(self) -> int:
        if self.rank in TEN_VALUE_RANKS:
            return 10
        if self.rank == "A":
            return 11
        return int(self.rank)

    @property
    def glyph(self) -> str:
        return SUIT_GLYPHS[self.suit]

    @property
    def is_red(self) -> bool:
        return self.suit in RED_SUITS

    @property
    def short_rank(self) -> str:
        return "T" if self.rank == "10" else self.rank

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{self.short_rank}{self.glyph}"


def hilo_value(card: Card) -> int:
    """Hi-Lo running-count value of a single card. Public (not just used
    internally by Shoe.draw()) so the UI can recompute a *partial* running
    count over just the cards currently visible to the player, separate
    from the shoe's own fully-advanced internal count."""
    if card.rank in {"2", "3", "4", "5", "6"}:
        return 1
    if card.rank in {"7", "8", "9"}:
        return 0
    return -1  # 10, J, Q, K, A


@dataclass
class Shoe:
    """A multi-deck shoe with a fixed shuffle order determined up front.

    The full shuffled order is generated once (per shuffle) and cards are
    drawn from the front, just like a physical shoe -- nothing about later
    cards is visible to the player, but the order is fixed for the life of
    the shoe.
    """

    num_decks: int
    penetration: float = 0.75
    _cards: List[Card] = field(default_factory=list, init=False)
    drawn_counts: Dict[str, int] = field(
        default_factory=lambda: {rank: 0 for rank in RANKS}, init=False
    )
    running_count: int = field(default=0, init=False)
    cards_dealt: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.shuffle()

    @property
    def total_cards(self) -> int:
        return self.num_decks * 52

    def shuffle(self) -> None:
        self._cards = [Card(rank, suit) for rank in RANKS for suit in SUITS] * self.num_decks
        random.shuffle(self._cards)
        self.drawn_counts = {rank: 0 for rank in RANKS}
        self.running_count = 0
        self.cards_dealt = 0

    def draw(self) -> Card:
        if not self._cards:
            raise RuntimeError("Shoe is empty -- reshuffle before drawing")
        card = self._cards.pop()
        self.drawn_counts[card.rank] += 1
        self.cards_dealt += 1
        self.running_count += hilo_value(card)
        return card

    @property
    def cards_remaining(self) -> int:
        return len(self._cards)

    @property
    def decks_remaining(self) -> float:
        return max(self.cards_remaining, 1) / 52

    @property
    def true_count(self) -> float:
        """Running count divided by decks *remaining*, rounded to nearest 0.5."""
        if self.cards_dealt == 0:
            return 0.0
        raw = self.running_count / self.decks_remaining
        return round(raw * 2) / 2

    @property
    def penetration_reached(self) -> bool:
        return self.cards_dealt / self.total_cards >= self.penetration
