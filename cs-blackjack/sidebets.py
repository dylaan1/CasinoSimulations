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
    """Player's first two cards + dealer's up card, evaluated as a 3-card poker hand.

    Trips is checked ahead of straight/flush: with 2+ decks in the shoe, a
    trips hand can also be a flush (three same-rank cards that happen to
    share a suit), and trips now pays more (25:1) than a plain flush (3:1),
    so it must win the priority order, not just lose to flush by being
    checked later.
    """
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
        return ("Straight Flush", 40)
    if is_trips:
        return ("Trips", 25)
    if is_straight:
        return ("Straight", 10)
    if is_flush:
        return ("Flush", 3)
    return None


def evaluate_star21(player_cards: List[Card], dealer_up: Card) -> Result:
    """Standard (3+ deck) Star21 table: player's first two cards + dealer's
    up card, summed like a 21 total (Ace=11)."""
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
        return ("Suited 21", 30)
    if all_sevens:
        return ("Unsuited 7-7-7", 50)
    if is_678:
        return ("Unsuited 6-7-8", 20)
    if total == 21:
        return ("Unsuited 21", 8)
    if total == 20:
        return ("Any 20", 4)
    if total == 19:
        return ("Any 19", 3)
    return None


def evaluate_star21_double_deck(player_cards: List[Card], dealer_up: Card) -> Result:
    """Double-deck (exactly 2 decks) Star21 table -- no 7-7-7 categories at
    all; a 7-7-7 hand (which also totals 21) just pays as a plain 21."""
    cards = list(player_cards[:2]) + [dealer_up]
    ranks = [c.rank for c in cards]
    total = sum(c.value for c in cards)
    suited = len({c.suit for c in cards}) == 1
    is_678 = set(ranks) == {"6", "7", "8"}

    if is_678 and suited:
        return ("Suited 6-7-8", 500)
    if total == 21 and suited:
        return ("Suited 21", 50)
    if is_678:
        return ("Unsuited 6-7-8", 40)
    if total == 21:
        return ("Unsuited 21", 10)
    if total == 20:
        return ("Any 20", 4)
    if total == 19:
        return ("Any 19", 3)
    return None


_BUSTER_PAYTABLE = {3: 2, 4: 3, 5: 12, 6: 50, 7: 100}


def evaluate_dealer_buster(dealer_hand: Hand, num_decks: int = 6) -> Result:
    if not dealer_hand.is_bust:
        return None
    n = len(dealer_hand.cards)
    if n >= 8:
        return ("8+ Card Bust", 500 if num_decks == 1 else 250)
    payout = _BUSTER_PAYTABLE.get(n)
    if payout is None:
        return None
    return (f"{n} Card Bust", payout)


def power_poker_allowed(num_decks: int) -> bool:
    """Power Poker needs 3+ decks in the shoe -- with fewer, the 3-card odds
    swing too far in the player's favor to stay firmly disabled below that."""
    return num_decks >= 3


def star21_allowed(num_decks: int) -> bool:
    """Star21 needs 2+ decks; exactly 2 uses the double-deck paytable
    (evaluate_star21_double_deck), 3+ uses the standard one."""
    return num_decks >= 2


def side_bet_allowed(key: str, num_decks: int) -> bool:
    if key == "power_poker":
        return power_poker_allowed(num_decks)
    if key == "star21":
        return star21_allowed(num_decks)
    return True  # dealer_buster has no deck-count restriction
