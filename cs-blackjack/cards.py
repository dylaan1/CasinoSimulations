from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List
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

    @property
    def token(self) -> str:
        """Fixed two-character form ("T♦", "K♣") used wherever a card is
        stored or exported -- the history database writes card sequences as
        these tokens run together, so they can be split back apart every
        two characters."""
        return f"{self.short_rank}{self.glyph}"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.token


def cards_to_string(cards: Iterable[Card]) -> str:
    """Card tokens run together, e.g. "K♣T♦3♠"."""
    return "".join(c.token for c in cards)


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
    # The shoe is cut when fewer than this many cards would be left for the
    # next round, whatever `penetration` says (see needs_cut).
    min_cards_left: int = 15
    _cards: List[Card] = field(default_factory=list, init=False)
    # The whole shuffle in the order it will be dealt (first card dealt
    # first), frozen when the shoe is shuffled and kept only in memory --
    # _cards above shrinks as cards are drawn, so this is the only place the
    # full order survives. The history log gets the dealt part after each
    # round and the never-dealt remainder only once the shoe is retired.
    _initial_order: List[Card] = field(default_factory=list, init=False, repr=False)
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
        self._initial_order = self._cards[::-1]  # draw() pops from the end, so the end is dealt first
        self.drawn_counts = {rank: 0 for rank in RANKS}
        self.running_count = 0
        self.cards_dealt = 0

    def dealt_string(self) -> str:
        """The cards dealt from this shoe so far, as tokens in dealing order,
        e.g. "K♣T♦3♠"."""
        return cards_to_string(self._initial_order[: self.cards_dealt])

    def undealt_string(self) -> str:
        """The cards still in the shoe, in the order they would have been
        dealt -- the part of the shuffle no round has drawn."""
        return cards_to_string(self._initial_order[self.cards_dealt :])

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

    @property
    def needs_cut(self) -> bool:
        """True once the cut card has been reached, or too few cards remain
        for another round -- whichever comes first."""
        return self.penetration_reached or self.cards_remaining < self.min_cards_left

    @property
    def effective_penetration(self) -> float:
        """How deep this shoe is really cut, as a fraction of the shoe: the
        penetration setting, or -- when that would leave fewer than
        min_cards_left cards -- the depth that leaves exactly that many."""
        return min(self.penetration, (self.total_cards - self.min_cards_left) / self.total_cards)

    def reshuffle_around(self, table_cards: List[Card]) -> None:
        """The failsafe for a shoe that runs dry mid-round: shuffle every card
        that ISN'T on the table back into a fresh order, and carry on dealing
        from it -- exactly what a dealer does with the discards. Rebuilds this
        Shoe in place (a round's dealer loop holds a reference to it), and
        treats the cards on the table as already dealt from the new shuffle,
        so the running count is simply their Hi-Lo total and cards_dealt is
        how many there are.

        table_cards must be every card drawn so far in the round, in the
        order they were drawn; each must belong to this shoe's decks."""
        rest = [Card(rank, suit) for rank in RANKS for suit in SUITS] * self.num_decks
        for card in table_cards:
            rest.remove(card)  # ValueError if a card isn't in the shoe: the caller's bookkeeping is wrong
        random.shuffle(rest)
        self._cards = rest
        self._initial_order = list(table_cards) + rest[::-1]  # the table cards, then the new deal order
        self.drawn_counts = {rank: 0 for rank in RANKS}
        for card in table_cards:
            self.drawn_counts[card.rank] += 1
        self.running_count = sum(hilo_value(card) for card in table_cards)
        self.cards_dealt = len(table_cards)
