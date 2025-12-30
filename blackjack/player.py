from __future__ import annotations
from dataclasses import dataclass
from typing import List

from .hand import Hand
from .cards import Shoe
from .strategy import BasicStrategy

@dataclass
class PlayerSettings:
    bankroll: float
    blackjack_payout: float = 1.5
    double_after_split: bool = True
    split_aces_logic: str = "Single"
    surrender: str = "late"
    bet_amount: float = 1.0  # base wager per hand

@dataclass
class Player:
    settings: PlayerSettings
    strategy: BasicStrategy

    def play(
        self, shoe: Shoe, dealer_up: str, initial: Hand, allow_surrender: bool | None = None
    ) -> List[Hand]:
        surrender_allowed = (
            self.settings.surrender.lower() != "none" if allow_surrender is None else allow_surrender
        )
        hands = [initial]
        i = 0
        while i < len(hands):
            hand = hands[i]
            self._play_hand(hand, shoe, dealer_up, hands, surrender_allowed)
            i += 1
            # After the first decision, surrender is no longer available
            surrender_allowed = False
        return hands

    def _play_hand(
        self, hand: Hand, shoe: Shoe, dealer_up: str, hands: List[Hand], allow_surrender: bool
    ) -> None:
        split_logic = self.settings.split_aces_logic.lower()
        carnival_split = split_logic == "carnival"

        # Surrender decision
        can_double = not hand.is_split or self.settings.double_after_split
        action = self.strategy.decide(hand, dealer_up, {
            "can_double": can_double and not hand.is_split_aces,
            "can_split": hand.can_split,
            "can_surrender": allow_surrender and not hand.is_split,
        })
        if action == "surrender":
            hand.surrendered = True
            hand.bet /= 2
            return
        while True:
            if hand.is_blackjack or hand.is_bust:
                return
            if hand.is_split_aces:
                if not carnival_split and len(hand.cards) >= 2:
                    return
                if carnival_split and len(hand.cards) == 2 and hand.cards[1].rank == "A":
                    ace_hands = sum(1 for h in hands if h.is_split_aces)
                    if ace_hands >= 4:
                        return

            can_split = hand.can_split
            if hand.can_split and hand.cards[0].rank == "A":
                ace_hands = sum(1 for h in hands if h.is_split_aces)
                if hand.is_split_aces:
                    can_split = carnival_split and ace_hands < 4
                else:
                    can_split = True
            can_double = len(hand.cards) == 2 and (
                (not hand.is_split or self.settings.double_after_split)
                and (
                    not hand.is_split_aces
                    or (carnival_split and hand.cards[-1].rank != "A")
                )
            )
            action = self.strategy.decide(hand, dealer_up, {
                "can_double": can_double,
                "can_split": can_split,
                "can_surrender": False,
            })
            if action == "stand":
                return
            if action == "double" and len(hand.cards) == 2 and self.settings.bankroll >= hand.bet:
                self.settings.bankroll -= hand.bet
                hand.bet *= 2
                hand.add_card(shoe.draw())
                return
            if action == "split" and can_split and self.settings.bankroll >= hand.bet:
                rank = hand.cards[0].rank
                if rank == "A":
                    ace_hands = sum(1 for h in hands if h.is_split_aces)
                    if hand.is_split_aces and (not carnival_split or ace_hands >= 4):
                        action = "hit"
                    else:
                        self.settings.bankroll -= hand.bet
                        new_hand = Hand(cards=[hand.cards.pop()], bet=hand.bet, is_split_aces=True, is_split=True)
                        hand.is_split_aces = True
                        hand.is_split = True
                        hand.add_card(shoe.draw())
                        new_hand.add_card(shoe.draw())
                        hands.append(new_hand)
                        continue
                else:
                    self.settings.bankroll -= hand.bet
                    new_hand = Hand(cards=[hand.cards.pop()], bet=hand.bet, is_split_aces=False, is_split=True)
                    hand.is_split = True
                    hand.add_card(shoe.draw())
                    new_hand.add_card(shoe.draw())
                    hands.append(new_hand)
                    continue
            hand.add_card(shoe.draw())
