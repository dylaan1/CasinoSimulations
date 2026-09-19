from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Stats:
    """Lifetime counters (persisted across runs) plus this-session bookkeeping.

    Lifetime: main-wager P/L $, side-bet P/L $, EV% (realized edge on main
    blackjack wagers only -- side bets have very different variance and
    would muddy that number), win/loss/push/surrender tallies, and total
    hands ever played.

    Session (reset every run): the same shape as lifetime, plus doubles,
    splits, and blackjacks dealt to either side.
    """

    hands_lifetime: int = 0
    player_wins: int = 0
    dealer_wins: int = 0
    pushes: int = 0
    surrenders_lifetime: int = 0
    dealer_busts_8plus: int = 0  # dealer busts on an 8th (or later) card
    blazing_sevens: int = 0  # Star 21 hits on Suited 7-7-7 Diamonds
    royal_flushes: int = 0  # Power Poker hits on a suited A-K-Q (Royal Flush) on the deal

    lifetime_main_wagered: float = 0.0  # sum of main-hand bets settled, for EV%
    lifetime_main_pl: float = 0.0
    lifetime_sidebet_pl: float = 0.0

    hands_this_session: int = 0
    surrenders: int = 0
    doubles: int = 0
    splits: int = 0
    player_blackjacks: int = 0
    dealer_blackjacks: int = 0

    session_main_pl: float = 0.0
    session_sidebet_pl: float = 0.0
    session_player_wins: int = 0
    session_dealer_wins: int = 0
    session_pushes: int = 0

    def record_hand_outcome(self, outcome: str, bet: float, payout: float) -> None:
        self.hands_lifetime += 1
        self.hands_this_session += 1
        self.lifetime_main_wagered += bet
        pl = payout - bet
        self.lifetime_main_pl += pl
        self.session_main_pl += pl
        if outcome == "player_win":
            self.player_wins += 1
            self.session_player_wins += 1
        elif outcome == "dealer_win":
            self.dealer_wins += 1
            self.session_dealer_wins += 1
        elif outcome == "push":
            self.pushes += 1
            self.session_pushes += 1
        elif outcome == "surrender":
            self.surrenders += 1
            self.surrenders_lifetime += 1

    def record_side_bet(self, wager: float, win_amount: float) -> None:
        pl = win_amount - wager
        self.lifetime_sidebet_pl += pl
        self.session_sidebet_pl += pl

    def record_double(self) -> None:
        self.doubles += 1

    def record_split(self) -> None:
        self.splits += 1

    def record_player_blackjack(self) -> None:
        self.player_blackjacks += 1

    def record_dealer_blackjack(self) -> None:
        self.dealer_blackjacks += 1

    def record_dealer_bust_8plus(self) -> None:
        self.dealer_busts_8plus += 1

    def record_blazing_seven(self) -> None:
        self.blazing_sevens += 1

    def record_royal_flush(self) -> None:
        self.royal_flushes += 1

    def reset_session(self) -> None:
        """Zero every session-scoped counter; lifetime counters are untouched."""
        self.hands_this_session = 0
        self.surrenders = 0
        self.doubles = 0
        self.splits = 0
        self.player_blackjacks = 0
        self.dealer_blackjacks = 0
        self.session_main_pl = 0.0
        self.session_sidebet_pl = 0.0
        self.session_player_wins = 0
        self.session_dealer_wins = 0
        self.session_pushes = 0

    def reset_lifetime(self) -> None:
        """Zero every lifetime-scoped counter; session counters are untouched."""
        self.hands_lifetime = 0
        self.player_wins = 0
        self.dealer_wins = 0
        self.pushes = 0
        self.surrenders_lifetime = 0
        self.dealer_busts_8plus = 0
        self.blazing_sevens = 0
        self.royal_flushes = 0
        self.lifetime_main_wagered = 0.0
        self.lifetime_main_pl = 0.0
        self.lifetime_sidebet_pl = 0.0

    def ev_percent(self) -> Optional[float]:
        if self.lifetime_main_wagered <= 0:
            return None
        return self.lifetime_main_pl / self.lifetime_main_wagered * 100.0

    def to_dict(self) -> dict:
        return {
            "hands_lifetime": self.hands_lifetime,
            "player_wins": self.player_wins,
            "dealer_wins": self.dealer_wins,
            "pushes": self.pushes,
            "surrenders_lifetime": self.surrenders_lifetime,
            "dealer_busts_8plus": self.dealer_busts_8plus,
            "blazing_sevens": self.blazing_sevens,
            "royal_flushes": self.royal_flushes,
            "lifetime_main_wagered": self.lifetime_main_wagered,
            "lifetime_main_pl": self.lifetime_main_pl,
            "lifetime_sidebet_pl": self.lifetime_sidebet_pl,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Stats":
        stats = cls()
        stats.hands_lifetime = int(data.get("hands_lifetime", 0))
        stats.player_wins = int(data.get("player_wins", 0))
        stats.dealer_wins = int(data.get("dealer_wins", 0))
        stats.pushes = int(data.get("pushes", 0))
        stats.surrenders_lifetime = int(data.get("surrenders_lifetime", 0))
        stats.dealer_busts_8plus = int(data.get("dealer_busts_8plus", 0))
        stats.blazing_sevens = int(data.get("blazing_sevens", 0))
        stats.royal_flushes = int(data.get("royal_flushes", 0))
        stats.lifetime_main_wagered = float(data.get("lifetime_main_wagered", 0.0))
        stats.lifetime_main_pl = float(data.get("lifetime_main_pl", 0.0))
        stats.lifetime_sidebet_pl = float(data.get("lifetime_sidebet_pl", 0.0))
        # session fields intentionally left at their fresh defaults (0)
        return stats
