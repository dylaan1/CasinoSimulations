from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict

from .sidebets import default_payouts

# "deckpen rand" re-rolls Rules.penetration to somewhere in this range every
# time a fresh shoe is actually cut -- see GameSession._roll_penetration.
RANDOM_PENETRATION_RANGE = (0.65, 0.80)

# A round can run out of cards part-way through (the dealer's hand included)
# if a shoe is cut too deep for the number of hands in play. If it ever does,
# the discards are shuffled back in and the round finishes (see
# Round._draw / GameSession.reshuffle_mid_round) -- the same thing a casino
# does -- but the rules below make that a rarity:
#
# Every shoe is cut when fewer than a minimum number of cards would be left
# for the next round (min_cards_to_deal below): 24 on a single deck, 15 on two
# decks -- which are also never cut deeper than DOUBLE_DECK_MAX_PENETRATION --
# and on three or more decks an amount that grows with the number of hands in
# play. The per-hand figures come from measurement: over 200,000 simulated
# rounds each, the most cards one round ever used was 14/21/24 (1/2/3 hands,
# basic strategy) and 25/37/44 for a player who splits and hits everything.
MIN_CARDS_TO_DEAL = 15
SINGLE_DECK_MIN_CARDS = 24
DOUBLE_DECK_MAX_PENETRATION = 0.80
MULTI_DECK_MIN_CARDS_BASE = 16
MULTI_DECK_MIN_CARDS_PER_HAND = 12  # 16 + 12/hand = 28, 40, 52 cards for 1, 2, 3 hands


def min_cards_to_deal(num_decks: int, num_hands: int) -> int:
    """Fewest cards a `num_decks` shoe may be left with before it's cut, given
    the number of hands being played."""
    if num_decks == 1:
        return SINGLE_DECK_MIN_CARDS
    if num_decks == 2:
        return MIN_CARDS_TO_DEAL
    return MULTI_DECK_MIN_CARDS_BASE + MULTI_DECK_MIN_CARDS_PER_HAND * max(num_hands, 1)

# A single deck is also held to fewer hands: at most SINGLE_DECK_MAX_HANDS
# hands per round (1 or 2, changeable any time), and one split per hand -- a
# pair split into up to four hands, each hit repeatedly, is what used to run
# a single deck dry (see GameSession.split_hand_limit).
SINGLE_DECK_MAX_HANDS = 2
SINGLE_DECK_MAX_SPLIT_HANDS = 2  # hands one spot may split into: the original plus one split


def format_blackjack_payout(payout: float) -> str:
    return "3:2" if abs(payout - 1.5) < 1e-9 else "6:5"


@dataclass
class SideBetRules:
    enabled: bool = False
    min_bet: float = 0.0
    max_bet: float = 100.0


@dataclass
class Rules:
    num_decks: int = 6
    penetration: float = 0.75  # fraction of shoe dealt before reshuffle
    # If True, `penetration` above is re-rolled to a random value in
    # [RANDOM_PENETRATION_RANGE] every time a fresh shoe is actually cut
    # (see GameSession._roll_penetration) -- set via "deckpen rand"; a plain
    # "deckpen 0.NN" turns this back off and pins the value to N.
    random_penetration: bool = False
    das: bool = True  # double after split allowed
    rsa: bool = False  # resplit aces allowed
    rsa_max_hands: int = 4  # max individual hands from resplitting aces (only matters if rsa is on)
    blackjack_payout: float = 1.5  # 1.5 = 3:2, 1.2 = 6:5
    surrender: str = "late"  # "late" | "early" | "off"
    hit_soft_17: bool = False  # False = dealer stands soft 17 (S17), True = hits (H17)
    split_max_hands: int = 4  # max individual hands resulting from splitting non-ace pairs
    double_facedown: bool = False  # if True, a double-down card is dealt face down until dealer/settlement reveal
    rsa_facedown: bool = False  # if True (only settable while rsa is off), split-ace cards are dealt face down
    double_blackjack: bool = False  # if True, a player dealt a natural blackjack is offered a double instead of an automatic 3:2 payout
    show_hilo: bool = True  # if False, the running/true count (and their labels) are hidden from the red bar -- counting still happens internally

    table_min: float = 0.0  # min main wager on a single hand (0 = no minimum)
    table_max: float = 5000.0  # max main wager on a single hand
    default_bet: float = 10.0
    default_bankroll: float = 10_000.0  # bankroll 'bank reset' resets to
    num_hands: int = 1  # simultaneous hands to play, 1-3

    power_poker: SideBetRules = field(default_factory=SideBetRules)
    star21: SideBetRules = field(default_factory=SideBetRules)
    dealer_buster: SideBetRules = field(default_factory=SideBetRules)

    # Every side bet's payout odds, adjustable live via e.g. "star21
    # suited777d 3000" or "buster 8+ 300" -- see sidebets.default_payouts()
    # for the shape (table key -> {category key -> multiplier}) and
    # commands._sidebet_payout_command for the command itself.
    payouts: Dict[str, Dict[str, float]] = field(default_factory=default_payouts)

    @property
    def surrender_late(self) -> bool:
        return self.surrender == "late"

    @property
    def surrender_early(self) -> bool:
        return self.surrender == "early"

    @property
    def surrender_enabled(self) -> bool:
        return self.surrender in ("late", "early")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Rules":
        data = dict(data)
        pp = data.pop("power_poker", None) or {}
        s21 = data.pop("star21", None) or {}
        buster = data.pop("dealer_buster", None) or {}
        saved_payouts = data.pop("payouts", None) or {}
        rules = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        rules.power_poker = SideBetRules(**pp) if pp else SideBetRules()
        rules.star21 = SideBetRules(**s21) if s21 else SideBetRules()
        rules.dealer_buster = SideBetRules(**buster) if buster else SideBetRules()
        # Merge onto a fresh set of defaults rather than trusting the saved
        # dict's own shape -- an older save file (or one saved before a new
        # payout category existed) may be missing whole tables or keys, and
        # the evaluators index into these dicts directly with no fallback.
        merged = default_payouts()
        for table, rows in saved_payouts.items():
            if table in merged and isinstance(rows, dict):
                for key, value in rows.items():
                    if key in merged[table]:
                        try:
                            merged[table][key] = float(value)
                        except (TypeError, ValueError):
                            pass
        rules.payouts = merged
        return rules

    def blackjack_payout_label(self) -> str:
        return format_blackjack_payout(self.blackjack_payout)
