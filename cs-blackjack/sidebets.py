from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .cards import Card
from .hand import Hand

RANK_ORDER = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10,
    "J": 11, "Q": 12, "K": 13, "A": 14,
}

Result = Optional[Tuple[str, str, float]]  # (category key, label, payout multiplier), None = no win

# Every payout category, per table variant, as (key, label) -- key is what
# the "<sidebet> <key> <payout>" command and the lifetime occurrence
# counters use; label is the display text shown in banners/payout tables
# (unchanged from before, so existing display formatting -- e.g.
# _display_label's " Diamonds" -> "♦" swap -- keeps working as-is).
POWER_POKER_CATEGORIES: List[Tuple[str, str]] = [
    ("royalflush", "Royal Flush"),
    ("straightflush", "Straight Flush"),
    ("trips", "Trips"),
    ("straight", "Straight"),
    ("flush", "Flush"),
]
STAR21_STANDARD_CATEGORIES: List[Tuple[str, str]] = [
    ("suited777d", "Suited 7-7-7 Diamonds"),
    ("suited777", "Suited 7-7-7"),
    ("suited678", "Suited 6-7-8"),
    ("unsuited777", "Unsuited 7-7-7"),
    ("suited21", "Suited 21"),
    ("unsuited678", "Unsuited 6-7-8"),
    ("unsuited21", "Unsuited 21"),
    ("any20", "Any 20"),
    ("any19", "Any 19"),
]
STAR21_DOUBLE_CATEGORIES: List[Tuple[str, str]] = [
    ("suited678", "Suited 6-7-8"),
    ("suited21", "Suited 21"),
    ("unsuited678", "Unsuited 6-7-8"),
    ("unsuited21", "Unsuited 21"),
    ("any20", "Any 20"),
    ("any19", "Any 19"),
]
BUSTER_CATEGORIES: List[Tuple[str, str]] = [
    ("8+", "8+ Card Bust"),
    ("7", "7 Card Bust"),
    ("6", "6 Card Bust"),
    ("5", "5 Card Bust"),
    ("4", "4 Card Bust"),
    ("3", "3 Card Bust"),
]

# Every mutable payout table, keyed the same way Rules.payouts stores them.
# star21/buster have two variants (deck-count-gated -- see star21_table_key/
# buster_table_key below); Power Poker has just the one.
PAYOUT_TABLE_KEYS = ("power_poker", "star21_standard", "star21_double", "buster_multi", "buster_single")

_DEFAULT_PAYOUTS: Dict[str, Dict[str, float]] = {
    "power_poker": {"royalflush": 50.0, "straightflush": 40.0, "trips": 25.0, "straight": 10.0, "flush": 3.0},
    "star21_standard": {
        "suited777d": 5000.0, "suited777": 500.0, "suited678": 100.0, "unsuited777": 50.0,
        "suited21": 30.0, "unsuited678": 20.0, "unsuited21": 8.0, "any20": 4.0, "any19": 3.0,
    },
    "star21_double": {
        "suited678": 500.0, "suited21": 50.0, "unsuited678": 40.0, "unsuited21": 10.0, "any20": 4.0, "any19": 3.0,
    },
    "buster_multi": {"8+": 250.0, "7": 100.0, "6": 50.0, "5": 12.0, "4": 3.0, "3": 2.0},
    "buster_single": {"8+": 500.0, "7": 100.0, "6": 50.0, "5": 12.0, "4": 3.0, "3": 2.0},
}


def default_payouts() -> Dict[str, Dict[str, float]]:
    """A fresh, independent copy of every payout table's default odds --
    used both for a brand-new Rules object and to backfill any table an
    old save file's JSON doesn't have yet."""
    return {table: dict(rows) for table, rows in _DEFAULT_PAYOUTS.items()}


def star21_table_key(num_decks: int) -> str:
    return "star21_double" if num_decks == 2 else "star21_standard"


def buster_table_key(num_decks: int) -> str:
    return "buster_single" if num_decks == 1 else "buster_multi"


def categories_for_table(table_key: str) -> List[Tuple[str, str]]:
    return {
        "power_poker": POWER_POKER_CATEGORIES,
        "star21_standard": STAR21_STANDARD_CATEGORIES,
        "star21_double": STAR21_DOUBLE_CATEGORIES,
        "buster_multi": BUSTER_CATEGORIES,
        "buster_single": BUSTER_CATEGORIES,
    }[table_key]


def evaluate_power_poker(player_cards: List[Card], dealer_up: Card, payouts: Dict[str, float]) -> Result:
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
            return ("royalflush", "Royal Flush", payouts["royalflush"])
        return ("straightflush", "Straight Flush", payouts["straightflush"])
    if is_trips:
        return ("trips", "Trips", payouts["trips"])
    if is_straight:
        return ("straight", "Straight", payouts["straight"])
    if is_flush:
        return ("flush", "Flush", payouts["flush"])
    return None


def evaluate_star21(player_cards: List[Card], dealer_up: Card, payouts: Dict[str, float]) -> Result:
    """Standard (3+ deck) Star 21 table: player's first two cards + dealer's
    up card, summed like a 21 total (Ace=11)."""
    cards = list(player_cards[:2]) + [dealer_up]
    ranks = [c.rank for c in cards]
    total = sum(c.value for c in cards)
    suited = len({c.suit for c in cards}) == 1
    all_diamonds = all(c.suit == "diamonds" for c in cards)
    all_sevens = all(r == "7" for r in ranks)
    is_678 = set(ranks) == {"6", "7", "8"}

    if all_sevens and all_diamonds:
        return ("suited777d", "Suited 7-7-7 Diamonds", payouts["suited777d"])
    if all_sevens and suited:
        return ("suited777", "Suited 7-7-7", payouts["suited777"])
    if is_678 and suited:
        return ("suited678", "Suited 6-7-8", payouts["suited678"])
    if total == 21 and suited:
        return ("suited21", "Suited 21", payouts["suited21"])
    if all_sevens:
        return ("unsuited777", "Unsuited 7-7-7", payouts["unsuited777"])
    if is_678:
        return ("unsuited678", "Unsuited 6-7-8", payouts["unsuited678"])
    if total == 21:
        return ("unsuited21", "Unsuited 21", payouts["unsuited21"])
    if total == 20:
        return ("any20", "Any 20", payouts["any20"])
    if total == 19:
        return ("any19", "Any 19", payouts["any19"])
    return None


def evaluate_star21_double_deck(player_cards: List[Card], dealer_up: Card, payouts: Dict[str, float]) -> Result:
    """Double-deck (exactly 2 decks) Star 21 table -- no 7-7-7 categories at
    all; a 7-7-7 hand (which also totals 21) just pays as a plain 21."""
    cards = list(player_cards[:2]) + [dealer_up]
    ranks = [c.rank for c in cards]
    total = sum(c.value for c in cards)
    suited = len({c.suit for c in cards}) == 1
    is_678 = set(ranks) == {"6", "7", "8"}

    if is_678 and suited:
        return ("suited678", "Suited 6-7-8", payouts["suited678"])
    if total == 21 and suited:
        return ("suited21", "Suited 21", payouts["suited21"])
    if is_678:
        return ("unsuited678", "Unsuited 6-7-8", payouts["unsuited678"])
    if total == 21:
        return ("unsuited21", "Unsuited 21", payouts["unsuited21"])
    if total == 20:
        return ("any20", "Any 20", payouts["any20"])
    if total == 19:
        return ("any19", "Any 19", payouts["any19"])
    return None


def evaluate_dealer_buster(dealer_hand: Hand, payouts: Dict[str, float]) -> Result:
    if not dealer_hand.is_bust:
        return None
    n = len(dealer_hand.cards)
    key = "8+" if n >= 8 else str(n)
    if key not in payouts:
        return None
    label = "8+ Card Bust" if n >= 8 else f"{n} Card Bust"
    return (key, label, payouts[key])


def power_poker_allowed(num_decks: int) -> bool:
    """Power Poker needs 3+ decks in the shoe -- with fewer, the 3-card odds
    swing too far in the player's favor to stay firmly disabled below that."""
    return num_decks >= 3


def star21_allowed(num_decks: int) -> bool:
    """Star 21 needs 2+ decks; exactly 2 uses the double-deck paytable
    (evaluate_star21_double_deck), 3+ uses the standard one."""
    return num_decks >= 2


def side_bet_allowed(key: str, num_decks: int) -> bool:
    if key == "power_poker":
        return power_poker_allowed(num_decks)
    if key == "star21":
        return star21_allowed(num_decks)
    return True  # dealer_buster has no deck-count restriction
