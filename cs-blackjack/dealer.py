from __future__ import annotations

from typing import Iterator, Protocol

from .cards import Card
from .hand import Hand


class SupportsDraw(Protocol):
    """Anything that can hand the dealer a card -- the round itself, which
    reshuffles the discards if the shoe runs dry, rather than the shoe."""

    def draw(self) -> Card: ...


def dealer_should_hit(hand: Hand, hit_soft_17: bool) -> bool:
    value = hand.best_value
    if value < 17:
        return True
    if value == 17 and hand.is_soft and hit_soft_17:
        return True
    return False


def play_dealer_hand(hand: Hand, shoe: SupportsDraw, hit_soft_17: bool) -> Iterator[Hand]:
    """Draw cards for the dealer one at a time, yielding after each draw.

    Yielding lets the UI redraw/pause between cards instead of the whole
    dealer hand appearing at once.
    """
    while dealer_should_hit(hand, hit_soft_17):
        hand.add_card(shoe.draw())
        yield hand
