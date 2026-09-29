from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

# Bet-key prefix for sidebet_occurrences' dict keys, e.g. "power_poker:royalflush".
_OCCURRENCE_KEY = "{bet}:{category}"


@dataclass
class Stats:
    """A snapshot of the numbers the game shows, read from the history
    database (HistoryDB.load_stats) -- nothing in the game increments these.
    Lifetime totals cover everything in the database (plus any older play
    imported from before the database existed); the session block covers just
    the current session. A fresh Stats() is all zeros, which is also what the
    game shows if the database can't be opened.

    Lifetime: P/L broken out by main wagers, side bets overall, and Power
    Poker/Star 21 individually; EV% (realized edge on main blackjack wagers
    only -- side bets have very different variance and would muddy that
    number); win/loss/push/surrender tallies; total hands ever played;
    sessions played; and, for every payout category across all three side
    bets, how many times it's actually occurred (regardless of whether it
    was wagered on that round) and how many times it actually paid out (it
    occurred *and* the player had a wager riding on it) -- see
    sidebet_occurrences/sidebet_wins, shown in their own per-bet tables on
    the 'stats' screen to help gauge whether a payout (adjustable via the
    "<sidebet> <category> <payout>" command) is priced the way you want it.

    Session (this session only): win/loss/push/surrender/double/split
    tallies, aces- and tens-split counts, Dealer Pulled 21s (the dealer
    hitting to a non-blackjack 21), player/dealer blackjacks dealt, shoes
    played, dealer busts, the player's current win/loss streak (consecutive
    hands, push/surrender leave it unchanged) and the longest win and loss
    streaks reached.
    """

    # ---- Lifetime ----
    hands_lifetime: int = 0
    player_wins: int = 0
    dealer_wins: int = 0
    pushes: int = 0
    surrenders_lifetime: int = 0
    sessions_played: int = 0

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
    # Same keying, but only counts an occurrence that actually paid out --
    # i.e. it happened *and* the player had a wager on that bet that round.
    sidebet_wins: Dict[str, int] = field(default_factory=dict)

    # ---- Session ----
    hands_this_session: int = 0
    surrenders: int = 0
    doubles: int = 0
    splits: int = 0
    aces_split: int = 0  # times the player split a pair of aces (not the # of aces involved)
    tens_split: int = 0  # times the player split a pair of ten-value cards
    player_blackjacks: int = 0
    dealer_blackjacks: int = 0
    greg_specials: int = 0  # "Dealer Pulled 21s" -- dealer hits their hand up to a non-blackjack 21
    dealer_busts: int = 0
    # Consecutive player_win/dealer_win hands (push/surrender don't touch
    # it): positive N = an N-hand win streak, negative N = an N-hand losing
    # streak, 0 = no streak yet this session. Displayed as "W2"/"L3"/"-".
    current_streak: int = 0
    longest_win_streak: int = 0  # best current_streak reached this session
    longest_loss_streak: int = 0  # worst (as a positive count) current_streak reached this session
    shoes_played: int = 0

    session_main_pl: float = 0.0
    session_sidebet_pl: float = 0.0
    session_player_wins: int = 0
    session_dealer_wins: int = 0
    session_pushes: int = 0

    def sidebet_occurrence_count(self, bet_key: str, category_key: str) -> int:
        return self.sidebet_occurrences.get(_OCCURRENCE_KEY.format(bet=bet_key, category=category_key), 0)

    def sidebet_win_count(self, bet_key: str, category_key: str) -> int:
        return self.sidebet_wins.get(_OCCURRENCE_KEY.format(bet=bet_key, category=category_key), 0)

    def ev_percent(self) -> Optional[float]:
        if self.lifetime_main_wagered <= 0:
            return None
        return self.lifetime_main_pl / self.lifetime_main_wagered * 100.0

    def total_lifetime_pl(self) -> float:
        return self.lifetime_main_pl + self.lifetime_sidebet_pl

    def session_pl(self) -> float:
        return self.session_main_pl + self.session_sidebet_pl

    @classmethod
    def from_legacy_dict(cls, data: dict) -> "Stats":
        """Read the lifetime numbers out of the `stats` block of an older
        ~/.cs-blackjack_state.json, from when the game counted them itself.
        Only used once, to import them into the history database -- see
        HistoryDB.import_legacy_stats. Session fields are left at zero."""
        stats = cls()
        stats.hands_lifetime = int(data.get("hands_lifetime", 0))
        stats.player_wins = int(data.get("player_wins", 0))
        stats.dealer_wins = int(data.get("dealer_wins", 0))
        stats.pushes = int(data.get("pushes", 0))
        stats.surrenders_lifetime = int(data.get("surrenders_lifetime", 0))
        stats.sessions_played = int(data.get("sessions_played", 0))
        stats.lifetime_main_wagered = float(data.get("lifetime_main_wagered", 0.0))
        stats.lifetime_main_pl = float(data.get("lifetime_main_pl", 0.0))
        stats.lifetime_sidebet_pl = float(data.get("lifetime_sidebet_pl", 0.0))
        stats.lifetime_power_poker_pl = float(data.get("lifetime_power_poker_pl", 0.0))
        stats.lifetime_star21_pl = float(data.get("lifetime_star21_pl", 0.0))
        occurrences = data.get("sidebet_occurrences") or {}
        stats.sidebet_occurrences = {str(k): int(v) for k, v in occurrences.items()}
        wins = data.get("sidebet_wins") or {}
        stats.sidebet_wins = {str(k): int(v) for k, v in wins.items()}
        # Migrate the even older, special-cased lifetime counters (pre-dating
        # the generic per-category tracking) into their equivalent occurrence
        # keys.
        legacy = {
            "dealer_busts_8plus": "dealer_buster:8+",
            "blazing_sevens": "star21:suited777d",
            "royal_flushes": "power_poker:royalflush",
        }
        for old_key, occ_key in legacy.items():
            if old_key in data and occ_key not in stats.sidebet_occurrences:
                stats.sidebet_occurrences[occ_key] = int(data[old_key])
        return stats
