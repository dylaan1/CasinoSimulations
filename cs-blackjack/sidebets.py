from __future__ import annotations

from typing import List, Optional, Tuple

from .cards import Card
from .hand import Hand

RANK_ORDER = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10,
    "J": 11, "Q": 12, "K": 13, "A": 14,
}

Result = Optional[Tuple[str, float]]  # (label, payout multiplier), None = no win


def evaluate_power_poker(player_cards: List[Card], dealer_up: Card) -> Result:
    """Player's first two cards + dealer's up card, evaluated as a 3-card poker hand."""
    cards = list(player_cards[:2]) + [dealer_up]
    ranks = [c.rank for c in cards]
    suits = {c.suit for c in cards}
    values = sorted(RANK_ORDER[r] for r in ranks)

    is_flush = len(suits) == 1
    is_straight = (values[1] - values[0] == 1 and values[2] - values[1] == 1) or values == [2, 3, 14]
    is_trips = len(set(ranks)) == 1

    if is_straight and is_flush:
        if set(values) == {12, 13, 14}:
            return ("Royal Flush", 50)
        return ("Straight Flush", 30)
    if is_flush:
        return ("Flush", 15)
    if is_straight:
        return ("Straight", 9)
    if is_trips:
        return ("Trips", 3)
    return None


def evaluate_star21(player_cards: List[Card], dealer_up: Card) -> Result:
    """Player's first two cards + dealer's up card, summed like a 21 total (Ace=11)."""
    cards = list(player_cards[:2]) + [dealer_up]
    ranks = [c.rank for c in cards]
    total = sum(c.value for c in cards)
    suited = len({c.suit for c in cards}) == 1
    all_diamonds = all(c.suit == "diamonds" for c in cards)
    all_sevens = all(r == "7" for r in ranks)
    is_678 = set(ranks) == {"6", "7", "8"}

    if all_sevens and all_diamonds:
        return ("Suited 7-7-7 Diamonds", 5000)
    if all_sevens and suited:
        return ("Suited 7-7-7", 500)
    if is_678 and suited:
        return ("Suited 6-7-8", 100)
    if total == 21 and suited:
        return ("Suited 21", 40)
    if all_sevens:
        return ("Unsuited 7-7-7", 20)
    if is_678:
        return ("Unsuited 6-7-8", 15)
    if total == 21:
        return ("Unsuited 21", 5)
    if total == 20:
        return ("Any 20", 3)
    if total == 19:
        return ("Any 19", 2)
    return None


_BUSTER_PAYTABLE = {3: 2, 4: 3, 5: 12, 6: 50, 7: 100}


def evaluate_dealer_buster(dealer_hand: Hand) -> Result:
    if not dealer_hand.is_bust:
        return None
    n = len(dealer_hand.cards)
    if n >= 8:
        return ("8+ Cards", 250)
    payout = _BUSTER_PAYTABLE.get(n)
    if payout is None:
        return None
    return (f"{n} Cards", payout)
