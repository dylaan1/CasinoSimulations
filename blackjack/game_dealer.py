from __future__ import annotations
from dataclasses import dataclass

from .game_cards import Shoe
from .game_hand import Hand

@dataclass
class Dealer:
    hit_soft_17: bool = False

    def play(self, hand: Hand, shoe: Shoe) -> Hand:
        while True:
            value = hand.best_value
            soft = any(v <= 21 and v != value for v in hand.values)
            if value < 17 or (value == 17 and soft and self.hit_soft_17):
                hand.add_card(shoe.draw())
                continue
            break
        return hand
