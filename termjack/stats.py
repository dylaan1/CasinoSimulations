from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Stats:
    """Lifetime counters (persisted across runs) plus this-session bookkeeping.

    Lifetime: bankroll growth (P/L $ and %), EV% (realized edge on main
    blackjack wagers only -- side bets have very different variance and
    would muddy that number), win/loss/push tallies, and total hands ever
    played.

    Session (reset every run): hands played this session, doubles, splits,
    surrenders, blackjacks dealt to either side. Running/true count aren't
    tracked here -- they live on the Shoe and are inherently session-local.
    """

    lifetime_starting_bankroll: float = 0.0  # captured once, ever; never touched again

    hands_lifetime: int = 0
    player_wins: int = 0
    dealer_wins: int = 0
    pushes: int = 0

    lifetime_main_wagered: float = 0.0  # sum of main-hand bets settled, for EV%
    lifetime_main_pl: float = 0.0  # main-hand payouts minus bets, for EV%
    lifetime_sidebet_pl: float = 0.0  # side bet net, folded into P/L $ but not EV%

    hands_this_session: int = 0
    surrenders: int = 0
    doubles: int = 0
    splits: int = 0
    player_blackjacks: int = 0
    dealer_blackjacks: int = 0

    def record_hand_outcome(self, outcome: str, bet: float, payout: float) -> None:
        self.hands_lifetime += 1
        self.hands_this_session += 1
        self.lifetime_main_wagered += bet
        self.lifetime_main_pl += payout - bet
        if outcome == "player_win":
            self.player_wins += 1
        elif outcome == "dealer_win":
            self.dealer_wins += 1
        elif outcome == "push":
            self.pushes += 1
        elif outcome == "surrender":
            self.surrenders += 1

    def record_side_bet(self, wager: float, win_amount: float) -> None:
        self.lifetime_sidebet_pl += win_amount - wager

    def record_double(self) -> None:
        self.doubles += 1

    def record_split(self) -> None:
        self.splits += 1

    def record_player_blackjack(self) -> None:
        self.player_blackjacks += 1

    def record_dealer_blackjack(self) -> None:
        self.dealer_blackjacks += 1

    def lifetime_pl_dollars(self) -> float:
        return self.lifetime_main_pl + self.lifetime_sidebet_pl

    def lifetime_pl_percent(self) -> float:
        if self.lifetime_starting_bankroll <= 0:
            return 0.0
        return self.lifetime_pl_dollars() / self.lifetime_starting_bankroll * 100.0

    def ev_percent(self) -> Optional[float]:
        if self.lifetime_main_wagered <= 0:
            return None
        return self.lifetime_main_pl / self.lifetime_main_wagered * 100.0

    def to_dict(self) -> dict:
        return {
            "lifetime_starting_bankroll": self.lifetime_starting_bankroll,
            "hands_lifetime": self.hands_lifetime,
            "player_wins": self.player_wins,
            "dealer_wins": self.dealer_wins,
            "pushes": self.pushes,
            "lifetime_main_wagered": self.lifetime_main_wagered,
            "lifetime_main_pl": self.lifetime_main_pl,
            "lifetime_sidebet_pl": self.lifetime_sidebet_pl,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Stats":
        stats = cls()
        stats.lifetime_starting_bankroll = float(data.get("lifetime_starting_bankroll", 0.0))
        stats.hands_lifetime = int(data.get("hands_lifetime", 0))
        stats.player_wins = int(data.get("player_wins", 0))
        stats.dealer_wins = int(data.get("dealer_wins", 0))
        stats.pushes = int(data.get("pushes", 0))
        stats.lifetime_main_wagered = float(data.get("lifetime_main_wagered", 0.0))
        stats.lifetime_main_pl = float(data.get("lifetime_main_pl", 0.0))
        stats.lifetime_sidebet_pl = float(data.get("lifetime_sidebet_pl", 0.0))
        # session fields intentionally left at their fresh defaults (0)
        return stats
