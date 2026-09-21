from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

# Bet-key prefix for sidebet_occurrences' dict keys, e.g. "power_poker:royalflush".
_OCCURRENCE_KEY = "{bet}:{category}"


@dataclass
class Stats:
    """Lifetime counters (persisted across runs) plus this-session bookkeeping.

    Lifetime: P/L broken out by main wagers, side bets overall, and Power
    Poker/Star 21 individually; EV% (realized edge on main blackjack wagers
    only -- side bets have very different variance and would muddy that
    number); win/loss/push/surrender tallies; total hands ever played;
    sessions played; and, for every payout category across all three side
    bets, how many times it's actually occurred (regardless of whether it
    was wagered on that round) -- see sidebet_occurrences, meant to inform
    future payout tuning via the "<sidebet> <category> <payout>" command.

    Session (reset every 'newsession'/hardreset): win/loss/push/surrender/
    double/split tallies, aces- and tens-split counts, Greg Specials (the
    dealer hitting to a non-blackjack 21), player/dealer blackjacks dealt,
    shoes played, dealer busts and the most cards any one of them took.
    """

    # ---- Lifetime ----
    hands_lifetime: int = 0
    player_wins: int = 0
    dealer_wins: int = 0
    pushes: int = 0
    surrenders_lifetime: int = 0
    sessions_played: int = 1

    lifetime_main_wagered: float = 0.0  # sum of main-hand bets settled, for EV%
    lifetime_main_pl: float = 0.0
    lifetime_sidebet_pl: float = 0.0
    lifetime_power_poker_pl: float = 0.0
    lifetime_star21_pl: float = 0.0

    # "<bet_key>:<category_key>" -> lifetime occurrence count, e.g.
    # "star21:suited777d" -- covers every category on all three payout
    # tables (Power Poker, Star 21, Dealer Buster), independent of whether
    # that spot actually had a wager riding on it.
    sidebet_occurrences: Dict[str, int] = field(default_factory=dict)

    # ---- Session ----
    hands_this_session: int = 0
    surrenders: int = 0
    doubles: int = 0
    splits: int = 0
    aces_split: int = 0  # times the player split a pair of aces (not the # of aces involved)
    tens_split: int = 0  # times the player split a pair of ten-value cards
    player_blackjacks: int = 0
    dealer_blackjacks: int = 0
    greg_specials: int = 0  # dealer hits their hand up to a non-blackjack 21
    dealer_busts: int = 0
    most_cards_for_dealer_bust: int = 0
    shoes_played: int = 1

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

    def record_side_bet(self, wager: float, win_amount: float, bet_key: Optional[str] = None) -> None:
        pl = win_amount - wager
        self.lifetime_sidebet_pl += pl
        self.session_sidebet_pl += pl
        if bet_key == "power_poker":
            self.lifetime_power_poker_pl += pl
        elif bet_key == "star21":
            self.lifetime_star21_pl += pl

    def record_sidebet_occurrence(self, bet_key: str, category_key: str) -> None:
        k = _OCCURRENCE_KEY.format(bet=bet_key, category=category_key)
        self.sidebet_occurrences[k] = self.sidebet_occurrences.get(k, 0) + 1

    def sidebet_occurrence_count(self, bet_key: str, category_key: str) -> int:
        return self.sidebet_occurrences.get(_OCCURRENCE_KEY.format(bet=bet_key, category=category_key), 0)

    def record_double(self) -> None:
        self.doubles += 1

    def record_split(self) -> None:
        self.splits += 1

    def record_aces_split(self) -> None:
        self.aces_split += 1

    def record_tens_split(self) -> None:
        self.tens_split += 1

    def record_player_blackjack(self) -> None:
        self.player_blackjacks += 1

    def record_dealer_blackjack(self) -> None:
        self.dealer_blackjacks += 1

    def record_greg_special(self) -> None:
        self.greg_specials += 1

    def record_dealer_bust(self, card_count: int) -> None:
        self.dealer_busts += 1
        self.most_cards_for_dealer_bust = max(self.most_cards_for_dealer_bust, card_count)

    def record_shoe_cut(self) -> None:
        self.shoes_played += 1

    def reset_session(self) -> None:
        """Zero every session-scoped counter; lifetime counters are untouched."""
        self.sessions_played += 1
        self.hands_this_session = 0
        self.surrenders = 0
        self.doubles = 0
        self.splits = 0
        self.aces_split = 0
        self.tens_split = 0
        self.player_blackjacks = 0
        self.dealer_blackjacks = 0
        self.greg_specials = 0
        self.dealer_busts = 0
        self.most_cards_for_dealer_bust = 0
        self.shoes_played = 1
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
        self.sessions_played = 1
        self.lifetime_main_wagered = 0.0
        self.lifetime_main_pl = 0.0
        self.lifetime_sidebet_pl = 0.0
        self.lifetime_power_poker_pl = 0.0
        self.lifetime_star21_pl = 0.0
        self.sidebet_occurrences = {}

    def ev_percent(self) -> Optional[float]:
        if self.lifetime_main_wagered <= 0:
            return None
        return self.lifetime_main_pl / self.lifetime_main_wagered * 100.0

    def total_lifetime_pl(self) -> float:
        return self.lifetime_main_pl + self.lifetime_sidebet_pl

    def session_pl(self) -> float:
        return self.session_main_pl + self.session_sidebet_pl

    def to_dict(self) -> dict:
        return {
            "hands_lifetime": self.hands_lifetime,
            "player_wins": self.player_wins,
            "dealer_wins": self.dealer_wins,
            "pushes": self.pushes,
            "surrenders_lifetime": self.surrenders_lifetime,
            "sessions_played": self.sessions_played,
            "lifetime_main_wagered": self.lifetime_main_wagered,
            "lifetime_main_pl": self.lifetime_main_pl,
            "lifetime_sidebet_pl": self.lifetime_sidebet_pl,
            "lifetime_power_poker_pl": self.lifetime_power_poker_pl,
            "lifetime_star21_pl": self.lifetime_star21_pl,
            "sidebet_occurrences": dict(self.sidebet_occurrences),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Stats":
        stats = cls()
        stats.hands_lifetime = int(data.get("hands_lifetime", 0))
        stats.player_wins = int(data.get("player_wins", 0))
        stats.dealer_wins = int(data.get("dealer_wins", 0))
        stats.pushes = int(data.get("pushes", 0))
        stats.surrenders_lifetime = int(data.get("surrenders_lifetime", 0))
        stats.sessions_played = int(data.get("sessions_played", 1))
        stats.lifetime_main_wagered = float(data.get("lifetime_main_wagered", 0.0))
        stats.lifetime_main_pl = float(data.get("lifetime_main_pl", 0.0))
        stats.lifetime_sidebet_pl = float(data.get("lifetime_sidebet_pl", 0.0))
        stats.lifetime_power_poker_pl = float(data.get("lifetime_power_poker_pl", 0.0))
        stats.lifetime_star21_pl = float(data.get("lifetime_star21_pl", 0.0))
        occurrences = data.get("sidebet_occurrences") or {}
        stats.sidebet_occurrences = {str(k): int(v) for k, v in occurrences.items()}
        # Migrate the old, special-cased lifetime counters (pre-dating the
        # generic per-category tracking) into their equivalent occurrence
        # keys, so an existing save file doesn't lose that history.
        legacy = {
            "dealer_busts_8plus": "dealer_buster:8+",
            "blazing_sevens": "star21:suited777d",
            "royal_flushes": "power_poker:royalflush",
        }
        for old_key, occ_key in legacy.items():
            if old_key in data and occ_key not in stats.sidebet_occurrences:
                stats.sidebet_occurrences[occ_key] = int(data[old_key])
        # session fields intentionally left at their fresh defaults
        return stats
