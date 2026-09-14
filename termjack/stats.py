from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Stats:
    """Lifetime counters (persisted across runs) plus this-session bookkeeping."""

    session_start_bankroll: float = 0.0
    hands_this_session: int = 0
    hands_last_session: int = 0

    player_wins: int = 0
    dealer_wins: int = 0
    pushes: int = 0
    surrenders: int = 0
    doubles: int = 0
    splits: int = 0
    player_blackjacks: int = 0
    dealer_blackjacks: int = 0

    def record_hand_outcome(self, outcome: str) -> None:
        self.hands_this_session += 1
        if outcome == "player_win":
            self.player_wins += 1
        elif outcome == "dealer_win":
            self.dealer_wins += 1
        elif outcome == "push":
            self.pushes += 1
        elif outcome == "surrender":
            self.surrenders += 1

    def record_double(self) -> None:
        self.doubles += 1

    def record_split(self) -> None:
        self.splits += 1

    def record_player_blackjack(self) -> None:
        self.player_blackjacks += 1

    def record_dealer_blackjack(self) -> None:
        self.dealer_blackjacks += 1

    def pl_dollars(self, bankroll: float) -> float:
        return bankroll - self.session_start_bankroll

    def pl_percent(self, bankroll: float) -> float:
        if self.session_start_bankroll <= 0:
            return 0.0
        return self.pl_dollars(bankroll) / self.session_start_bankroll * 100.0

    def to_dict(self) -> dict:
        return {
            "player_wins": self.player_wins,
            "dealer_wins": self.dealer_wins,
            "pushes": self.pushes,
            "surrenders": self.surrenders,
            "doubles": self.doubles,
            "splits": self.splits,
            "player_blackjacks": self.player_blackjacks,
            "dealer_blackjacks": self.dealer_blackjacks,
            "hands_last_session": self.hands_this_session,
        }

    @classmethod
    def from_dict(cls, data: dict, session_start_bankroll: float) -> "Stats":
        stats = cls(session_start_bankroll=session_start_bankroll)
        for key in (
            "player_wins", "dealer_wins", "pushes", "surrenders", "doubles",
            "splits", "player_blackjacks", "dealer_blackjacks",
        ):
            setattr(stats, key, int(data.get(key, 0)))
        stats.hands_last_session = int(data.get("hands_last_session", 0))
        return stats
