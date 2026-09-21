from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict

from .sidebets import default_payouts


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
    default_bankroll: float = 10_000.0  # bankroll a 'newsession' (or hardreset) resets to
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
