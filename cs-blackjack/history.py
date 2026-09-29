"""SQLite history log: every hand, session, and shoe ever played.

The database lives at ~/.cs-blackjack/blackjack.db and is meant to be read
from outside the game (sqlite3, DB Browser for SQLite, DBeaver, pandas...)
without launching it. Three tables, joined by ids:

  sessions  one row per session -- from launch, or from a 'newsession'/
            'hardreset', until the next of those or quit
  shoes     one row per unique shuffle, with its deck count, penetration,
            and the exact card order (card_order)
  hands     one row per player hand settled (a split spot logs one row per
            resulting hand); round_id groups the hands dealt together

plus two read-only views (hand_type_summary, bet_size_summary).

Conventions:
  * Timestamps are UTC ISO-8601 text ("2026-09-29T15:04:05Z"); in SQLite,
    datetime(col, 'localtime') converts them.
  * Booleans are 0/1 integers, money is REAL dollars.
  * A card is a two-character token -- rank (T = ten) then suit glyph, e.g.
    "T♦" -- and a card sequence is those tokens run together, "K♣T♦3♠".
  * Side bets and insurance belong to a spot, not to one of its split hands,
    so they're recorded on the spot's first hand (hand_number = 1) and are
    0/NULL on its other hands; summing a column over hands therefore never
    double-counts. Dealer-level facts (dealer_cards, ...) repeat on every
    hand of the round.
  * Column names avoid MySQL reserved words, and types are plain, so the
    tables carry over to other SQL databases with little change.

Nothing here may ever take the game down: every write is guarded, and a
failure just records HistoryDB.error and carries on.
"""

from __future__ import annotations

import csv
import functools
import json
import os
import shutil
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from . import persist
from .cards import cards_to_string
from .hand import Hand

if TYPE_CHECKING:  # pragma: no cover
    from .engine import GameSession, Round

DATA_DIR = Path.home() / ".cs-blackjack"
DB_PATH = DATA_DIR / "blackjack.db"
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = DATA_DIR / "exports"
DB_NAME = "blackjack.db"  # file names inside a backup folder
STATE_NAME = "state.json"

EXPORT_TABLES = ("hands", "sessions", "shoes")
EXPORT_FORMATS = ("csv", "json")

_SIDE_BET_KEYS = ("power_poker", "star21", "dealer_buster")
_OUTCOMES = {"player_win": "win", "dealer_win": "loss", "push": "push", "surrender": "surrender"}


class HistoryError(Exception):
    """A history/backup/export problem worth showing the player."""


# --------------------------------------------------------------------------
# Schema -- _MIGRATIONS[i] upgrades PRAGMA user_version i -> i + 1. Never edit
# a shipped entry; append a new one.
# --------------------------------------------------------------------------

_SCHEMA_V1 = """
CREATE TABLE sessions (
    session_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TEXT    NOT NULL,
    ended_at            TEXT,                -- NULL while the session is still running
    end_reason          TEXT,                -- quit | newsession | hardreset | restore | abandoned (crashed or killed)
    starting_bankroll   REAL    NOT NULL,
    ending_bankroll     REAL    NOT NULL,
    peak_bankroll       REAL    NOT NULL,
    lowest_bankroll     REAL    NOT NULL,
    max_drawdown        REAL    NOT NULL DEFAULT 0,   -- largest peak-to-trough fall in cumulative session P/L
    rounds_played       INTEGER NOT NULL DEFAULT 0,   -- rounds played to completion (not one cut off by quitting)
    hands_played        INTEGER NOT NULL DEFAULT 0,
    hands_won           INTEGER NOT NULL DEFAULT 0,
    hands_lost          INTEGER NOT NULL DEFAULT 0,
    hands_pushed        INTEGER NOT NULL DEFAULT 0,
    hands_surrendered   INTEGER NOT NULL DEFAULT 0,
    doubles             INTEGER NOT NULL DEFAULT 0,
    splits              INTEGER NOT NULL DEFAULT 0,
    aces_split          INTEGER NOT NULL DEFAULT 0,
    tens_split          INTEGER NOT NULL DEFAULT 0,
    player_blackjacks   INTEGER NOT NULL DEFAULT 0,
    dealer_blackjacks   INTEGER NOT NULL DEFAULT 0,
    dealer_pulled_21s   INTEGER NOT NULL DEFAULT 0,
    dealer_busts        INTEGER NOT NULL DEFAULT 0,
    shoes_played        INTEGER NOT NULL DEFAULT 1,
    main_wagered        REAL    NOT NULL DEFAULT 0,   -- money totals are sums over this session's hand rows
    main_pl             REAL    NOT NULL DEFAULT 0,
    sidebet_pl          REAL    NOT NULL DEFAULT 0,   -- side bets plus insurance
    net_pl              REAL    NOT NULL DEFAULT 0,
    longest_win_streak  INTEGER NOT NULL DEFAULT 0,
    longest_loss_streak INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE shoes (
    shoe_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       INTEGER REFERENCES sessions (session_id),
    cut_at           TEXT    NOT NULL,
    retired_at       TEXT,
    cut_reason       TEXT    NOT NULL,   -- start | penetration | newshoe | newsession | hardreset | restore
    num_decks        INTEGER NOT NULL,
    penetration      REAL    NOT NULL,   -- fraction of the shoe dealt before it is reshuffled
    total_cards      INTEGER NOT NULL,
    cards_dealt      INTEGER NOT NULL DEFAULT 0,
    blackjack_payout REAL    NOT NULL,   -- 1.5 = 3:2, 1.2 = 6:5, as active for this shoe
    hit_soft_17      INTEGER NOT NULL,
    rules_json       TEXT    NOT NULL,   -- every table rule and side-bet payout as of the cut
    card_order       TEXT    NOT NULL    -- the whole shuffle, first card dealt first
);

CREATE TABLE hands (
    hand_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id               INTEGER NOT NULL,
    session_id             INTEGER REFERENCES sessions (session_id),
    shoe_id                INTEGER REFERENCES shoes (shoe_id),
    played_at              TEXT    NOT NULL,
    spot_number            INTEGER NOT NULL,   -- 1-3, the on-screen "Hand #"
    hand_number            INTEGER NOT NULL,   -- 1.. within the spot, in split order
    initial_bet            REAL    NOT NULL,   -- before any double
    final_bet              REAL    NOT NULL,
    hand_type              TEXT    NOT NULL,   -- from the first two cards: blackjack | pair | soft | hard
    initial_total          INTEGER NOT NULL,
    player_cards           TEXT    NOT NULL,
    player_total           INTEGER NOT NULL,
    player_soft            INTEGER NOT NULL,
    player_bust            INTEGER NOT NULL,
    player_blackjack       INTEGER NOT NULL,   -- settled as an untouched natural
    is_split               INTEGER NOT NULL,
    is_split_aces          INTEGER NOT NULL,
    doubled                INTEGER NOT NULL,
    surrendered            INTEGER NOT NULL,
    even_money             INTEGER NOT NULL,
    dealer_up              TEXT    NOT NULL,
    dealer_cards           TEXT    NOT NULL,
    dealer_total           INTEGER NOT NULL,
    dealer_bust            INTEGER NOT NULL,
    dealer_blackjack       INTEGER NOT NULL,
    outcome                TEXT    NOT NULL,   -- win | loss | push | surrender | abandoned
    payout                 REAL    NOT NULL,   -- total returned to the bankroll for this hand
    main_pl                REAL    NOT NULL,   -- payout - final_bet
    insurance_wager        REAL    NOT NULL DEFAULT 0,
    insurance_pl           REAL    NOT NULL DEFAULT 0,
    power_poker_wager      REAL    NOT NULL DEFAULT 0,
    power_poker_category   TEXT,               -- what the spot's first two cards + dealer up-card made, wagered or not
    power_poker_pl         REAL    NOT NULL DEFAULT 0,
    star21_wager           REAL    NOT NULL DEFAULT 0,
    star21_category        TEXT,
    star21_pl              REAL    NOT NULL DEFAULT 0,
    dealer_buster_wager    REAL    NOT NULL DEFAULT 0,
    dealer_buster_category TEXT,
    dealer_buster_pl       REAL    NOT NULL DEFAULT 0,
    sidebet_pl             REAL    NOT NULL DEFAULT 0,   -- insurance + all three side bets
    total_pl               REAL    NOT NULL,             -- main_pl + sidebet_pl
    running_count_before   INTEGER NOT NULL,             -- Hi-Lo, as of just before the round was dealt
    true_count_before      REAL    NOT NULL,
    cards_dealt_before     INTEGER NOT NULL,             -- how deep into the shoe the round started
    bankroll_before        REAL    NOT NULL,             -- round-level: before any wager came off
    bankroll_after         REAL    NOT NULL
);

CREATE INDEX idx_hands_round   ON hands (round_id);
CREATE INDEX idx_hands_session ON hands (session_id);
CREATE INDEX idx_hands_shoe    ON hands (shoe_id);
CREATE INDEX idx_shoes_session ON shoes (session_id);

CREATE VIEW hand_type_summary AS
SELECT hand_type,
       COUNT(*)                     AS hands,
       SUM(outcome = 'win')         AS wins,
       SUM(outcome = 'loss')        AS losses,
       SUM(outcome = 'push')        AS pushes,
       SUM(outcome = 'surrender')   AS surrenders,
       ROUND(SUM(final_bet), 2)     AS wagered,
       ROUND(SUM(main_pl), 2)       AS main_pl
FROM hands
WHERE outcome <> 'abandoned'
GROUP BY hand_type;

CREATE VIEW bet_size_summary AS
SELECT initial_bet,
       COUNT(*)                          AS hands,
       SUM(outcome = 'win')              AS wins,
       SUM(outcome = 'loss')             AS losses,
       SUM(outcome = 'push')             AS pushes,
       ROUND(SUM(final_bet), 2)          AS wagered,
       ROUND(SUM(main_pl), 2)            AS main_pl,
       ROUND(AVG(true_count_before), 2)  AS avg_true_count
FROM hands
WHERE outcome <> 'abandoned'
GROUP BY initial_bet;
"""

_MIGRATIONS = [_SCHEMA_V1]
SCHEMA_VERSION = len(_MIGRATIONS)


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise HistoryError(
            f"History database is schema v{version}; this game only understands up to v{SCHEMA_VERSION}."
        )
    for target in range(version, SCHEMA_VERSION):
        # One transaction per step, version bump included, so a crash mid-
        # migration leaves the database exactly at the previous version.
        conn.executescript(f"BEGIN;\n{_MIGRATIONS[target]}\nPRAGMA user_version = {target + 1};\nCOMMIT;")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _guarded(default: Any = None):
    """Wrap a HistoryDB method so a database/disk problem is recorded on
    .error instead of raised, and so it's a silent no-op when there's no
    open database at all."""

    def wrap(fn):
        @functools.wraps(fn)
        def inner(self: "HistoryDB", *args, **kwargs):
            if self.conn is None:
                return default
            try:
                return fn(self, *args, **kwargs)
            except (sqlite3.Error, OSError) as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                return default

        return inner

    return wrap


def _hand_type(hand: Hand) -> Tuple[str, int]:
    """(type, total) judged on the hand's first two cards only. 'pair' is
    anything splittable, so it includes two different ten-value cards."""
    first = Hand(cards=list(hand.cards[:2]), is_split=hand.is_split)
    if first.is_blackjack:
        kind = "blackjack"
    elif first.can_split:
        kind = "pair"
    elif first.is_soft:
        kind = "soft"
    else:
        kind = "hard"
    return kind, first.best_value


def _readonly_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _check_database(path: Path) -> None:
    """Raise HistoryError unless `path` is an intact history database this
    version of the game can read."""
    try:
        conn = sqlite3.connect(_readonly_uri(path), uri=True)
    except sqlite3.Error as exc:
        raise HistoryError(f"Can't open {path.name}: {exc}")
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise HistoryError("Backup database failed its integrity check.")
        if conn.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
            raise HistoryError("Backup database is from a newer version of the game.")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"sessions", "shoes", "hands"} <= tables:
            raise HistoryError("That file isn't a cs-blackjack history database.")
    except sqlite3.DatabaseError as exc:
        raise HistoryError(f"Backup database is unreadable: {exc}")
    finally:
        conn.close()


def _copy_database(src: Path, dst: Path) -> None:
    """A consistent copy via SQLite's own backup API -- correct even while
    the source is open and being written, unlike copying the bare file."""
    src_conn = sqlite3.connect(_readonly_uri(src), uri=True)
    dst_conn = sqlite3.connect(dst)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


@dataclass
class _Tracking:
    """Running figures for the current session that don't live in Stats."""

    peak_bankroll: float = 0.0
    lowest_bankroll: float = 0.0
    cum_pl: float = 0.0  # cumulative P/L; drawdown is measured on this so a 'bank add' can't distort it
    peak_pl: float = 0.0
    max_drawdown: float = 0.0
    rounds: int = 0


# --------------------------------------------------------------------------
# The database
# --------------------------------------------------------------------------


class HistoryDB:
    def __init__(self, path: Path):
        self.path = path
        self.conn: Optional[sqlite3.Connection] = None
        self.error: Optional[str] = None  # the most recent failure, if any
        self.session_id: Optional[int] = None
        self.shoe_id: Optional[int] = None
        self._track = _Tracking()
        self._last_round: Optional["Round"] = None

    @classmethod
    def open(cls, path: Optional[Path] = None) -> "HistoryDB":
        """Open (creating/upgrading as needed) the history database. Never
        raises -- if it can't be opened, the returned object just records
        .error and every method on it becomes a no-op."""
        db = cls(path or DB_PATH)
        db._connect()
        return db

    def _connect(self) -> None:
        conn: Optional[sqlite3.Connection] = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=2.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            _migrate(conn)
            self.conn = conn
            self._close_stale_sessions()
        except (sqlite3.Error, OSError, HistoryError) as exc:
            self.error = f"{type(exc).__name__}: {exc}" if not isinstance(exc, HistoryError) else str(exc)
            if conn is not None:
                conn.close()
            self.conn = None

    @_guarded()
    def _close_stale_sessions(self) -> None:
        """A session still open at launch belongs to a run that crashed or
        was killed -- mark it (and its last shoe) closed as of its final
        recorded hand, so 'still running' only ever means running right now."""
        with self.conn:
            self.conn.execute(
                """UPDATE sessions
                   SET ended_at = COALESCE((SELECT MAX(played_at) FROM hands h
                                            WHERE h.session_id = sessions.session_id), started_at),
                       end_reason = 'abandoned'
                   WHERE ended_at IS NULL"""
            )
            self.conn.execute(
                """UPDATE shoes
                   SET retired_at = (SELECT ended_at FROM sessions s WHERE s.session_id = shoes.session_id)
                   WHERE retired_at IS NULL"""
            )

    # ---- low-level writers (always inside a `with self.conn` block) ----

    def _insert(self, table: str, row: Dict[str, Any]) -> int:
        cols = ", ".join(row)
        marks = ", ".join(f":{k}" for k in row)
        return self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", row).lastrowid

    def _update(self, table: str, key: str, key_value: int, fields: Dict[str, Any]) -> None:
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        self.conn.execute(f"UPDATE {table} SET {sets} WHERE {key} = :_key", {**fields, "_key": key_value})

    # ---- sessions ----

    @_guarded()
    def start_session(self, session: "GameSession") -> None:
        self._track = _Tracking(peak_bankroll=session.bankroll, lowest_bankroll=session.bankroll)
        with self.conn:
            self.session_id = self._insert(
                "sessions",
                {
                    "started_at": _now(),
                    "starting_bankroll": session.bankroll,
                    "ending_bankroll": session.bankroll,
                    "peak_bankroll": session.bankroll,
                    "lowest_bankroll": session.bankroll,
                },
            )

    def _session_fields(self, session: "GameSession", track: _Tracking) -> Dict[str, Any]:
        """The session row's current values. Counts come from the in-game
        session stats; the money totals are summed from the session's own
        hand rows instead (call inside the transaction that wrote them), so
        they always equal SUM() over `hands` -- including a round abandoned
        by quitting, whose forfeited wager the stats never saw."""
        s = session.stats
        wagered, main_pl, sidebet_pl = self.conn.execute(
            """SELECT COALESCE(SUM(final_bet), 0), COALESCE(SUM(main_pl), 0), COALESCE(SUM(sidebet_pl), 0)
               FROM hands WHERE session_id = ?""",
            (self.session_id,),
        ).fetchone()
        return {
            "ending_bankroll": session.bankroll,
            "peak_bankroll": track.peak_bankroll,
            "lowest_bankroll": track.lowest_bankroll,
            "max_drawdown": track.max_drawdown,
            "rounds_played": track.rounds,
            "hands_played": s.hands_this_session,
            "hands_won": s.session_player_wins,
            "hands_lost": s.session_dealer_wins,
            "hands_pushed": s.session_pushes,
            "hands_surrendered": s.surrenders,
            "doubles": s.doubles,
            "splits": s.splits,
            "aces_split": s.aces_split,
            "tens_split": s.tens_split,
            "player_blackjacks": s.player_blackjacks,
            "dealer_blackjacks": s.dealer_blackjacks,
            "dealer_pulled_21s": s.greg_specials,
            "dealer_busts": s.dealer_busts,
            "shoes_played": s.shoes_played,
            "main_wagered": wagered,
            "main_pl": main_pl,
            "sidebet_pl": sidebet_pl,
            "net_pl": main_pl + sidebet_pl,
            "longest_win_streak": s.longest_win_streak,
            "longest_loss_streak": s.longest_loss_streak,
        }

    @_guarded()
    def end_session(self, session: "GameSession", reason: str) -> None:
        if self.session_id is None:
            return
        fields = self._session_fields(session, self._track)
        fields.update(ended_at=_now(), end_reason=reason)
        with self.conn:
            self._update("sessions", "session_id", self.session_id, fields)
        self.session_id = None

    # ---- shoes ----

    @_guarded()
    def shoe_cut(self, session: "GameSession", reason: str) -> None:
        shoe = session.shoe
        with self.conn:
            self.shoe_id = self._insert(
                "shoes",
                {
                    "session_id": self.session_id,
                    "cut_at": _now(),
                    "cut_reason": reason,
                    "num_decks": shoe.num_decks,
                    "penetration": shoe.penetration,
                    "total_cards": shoe.total_cards,
                    "blackjack_payout": session.active_rules.blackjack_payout,
                    "hit_soft_17": int(session.active_rules.hit_soft_17),
                    "rules_json": json.dumps(session.rules.to_dict(), sort_keys=True),
                    "card_order": shoe.order_string(),
                },
            )

    @_guarded()
    def shoe_retired(self, session: "GameSession") -> None:
        if self.shoe_id is None:
            return
        with self.conn:
            self._update(
                "shoes", "shoe_id", self.shoe_id, {"cards_dealt": session.shoe.cards_dealt, "retired_at": _now()}
            )

    @_guarded()
    def close(self, session: "GameSession", reason: str = "quit") -> None:
        self.shoe_retired(session)
        self.end_session(session, reason)
        self.conn.close()
        self.conn = None

    # ---- rounds / hands ----

    def _round_rows(self, session: "GameSession", round_: "Round") -> List[Dict[str, Any]]:
        dealer = round_.dealer_hand
        common: Dict[str, Any] = {
            "session_id": self.session_id,
            "shoe_id": self.shoe_id,
            "played_at": _now(),
            "dealer_up": round_.dealer_up.token,
            "dealer_cards": cards_to_string(dealer.cards),
            "dealer_total": dealer.best_value,
            "dealer_bust": int(dealer.is_bust),
            "dealer_blackjack": int(dealer.is_blackjack),
            "running_count_before": round_.running_count_before,
            "true_count_before": round_.true_count_before,
            "cards_dealt_before": round_.cards_dealt_before,
            "bankroll_before": round_.bankroll_before,
            "bankroll_after": session.bankroll,
        }

        # Settled hands first, in the order they settled (the order the
        # stats and streaks saw them); anything still unsettled -- only
        # possible when the game was quit mid-round -- after that.
        results = {id(r.hand): r for r in round_.results}
        ordered = [(round_.spots[r.spot_index], r.hand) for r in round_.results]
        seen = {id(h) for _, h in ordered}
        for spot in round_.spots:
            ordered.extend((spot, h) for h in spot.hands if id(h) not in seen)

        side_results = {(r.spot_index, r.bet_key): r for r in round_.side_bet_results}

        rows = []
        for spot, hand in ordered:
            position = next(i for i, h in enumerate(spot.hands) if h is hand)  # not .index(): Hand compares by value
            result = results.get(id(hand))
            payout = result.payout if result else 0.0  # an unsettled hand's wager is simply forfeited
            outcome = _OUTCOMES[result.outcome] if result else "abandoned"
            kind, initial_total = _hand_type(hand)
            main_pl = payout - hand.bet

            row: Dict[str, Any] = dict(common)
            row.update(
                spot_number=spot.index + 1,
                hand_number=position + 1,
                initial_bet=hand.bet / 2 if hand.doubled else hand.bet,
                final_bet=hand.bet,
                hand_type=kind,
                initial_total=initial_total,
                player_cards=cards_to_string(hand.cards),
                player_total=hand.best_value,
                player_soft=int(hand.is_soft),
                player_bust=int(hand.is_bust),
                player_blackjack=int(hand.is_blackjack),
                is_split=int(hand.is_split),
                is_split_aces=int(hand.is_split_aces),
                doubled=int(hand.doubled),
                surrendered=int(hand.surrendered),
                even_money=int(hand.even_money_taken),
                outcome=outcome,
                payout=payout,
                main_pl=main_pl,
            )

            # Spot-level side bets ride on the spot's first hand only.
            sidebet_pl = 0.0
            first = hand is spot.hands[0]
            insurance = side_results.get((spot.index, "insurance"))
            insurance_wager = spot.insurance_wager if first else 0.0
            row["insurance_wager"] = insurance_wager
            row["insurance_pl"] = (insurance.win_amount if insurance else 0.0) - insurance_wager
            sidebet_pl += row["insurance_pl"]
            for key in _SIDE_BET_KEYS:
                wager = spot.side_bet_wagers.get(key, 0.0) if first else 0.0
                res = side_results.get((spot.index, key))
                pl = ((res.win_amount if res else 0.0) - wager) if first else 0.0
                row[f"{key}_wager"] = wager
                row[f"{key}_pl"] = pl
                row[f"{key}_category"] = round_.sidebet_categories.get((spot.index, key)) if first else None
                sidebet_pl += pl
            row["sidebet_pl"] = sidebet_pl
            row["total_pl"] = main_pl + sidebet_pl
            rows.append(row)
        return rows

    @_guarded()
    def record_round(self, session: "GameSession", round_: "Round") -> None:
        """Log a round (one row per hand), and bring the session and shoe
        rows up to date -- all in one transaction. Safe to call more than
        once for the same round. Normally called as a round settles; the
        shutdown path also calls it for a round cut off by quitting, where
        any hand not yet settled is logged as 'abandoned' with its wager
        forfeited -- which is what actually happened to the bankroll."""
        if self.session_id is None or round_ is self._last_round:
            return
        rows = self._round_rows(session, round_)
        cut_off = any(r["outcome"] == "abandoned" for r in rows)

        track = replace(self._track)
        round_pl = sum(r["total_pl"] for r in rows)
        track.cum_pl += round_pl
        track.peak_pl = max(track.peak_pl, track.cum_pl)
        track.max_drawdown = max(track.max_drawdown, track.peak_pl - track.cum_pl)
        track.peak_bankroll = max(track.peak_bankroll, session.bankroll)
        track.lowest_bankroll = min(track.lowest_bankroll, session.bankroll)
        if not cut_off:
            track.rounds += 1

        with self.conn:
            round_id = self.conn.execute("SELECT COALESCE(MAX(round_id), 0) + 1 FROM hands").fetchone()[0]
            for row in rows:
                self._insert("hands", {**row, "round_id": round_id})
            self._update("sessions", "session_id", self.session_id, self._session_fields(session, track))
            if self.shoe_id is not None:
                self._update("shoes", "shoe_id", self.shoe_id, {"cards_dealt": session.shoe.cards_dealt})
        self._track = track
        self._last_round = round_

    # ---- read-side, for the in-game stats screen ----

    @_guarded()
    def overview(self) -> Dict[str, Any]:
        """Numbers for the stats screen: this session and all time (bankroll
        range, drawdown, streaks, best/worst hand), row counts, and results
        by hand type."""
        c = self.conn
        counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in EXPORT_TABLES}

        def hand_extremes(where: str, params: tuple) -> Dict[str, float]:
            row = c.execute(
                f"SELECT MAX(main_pl), MIN(main_pl) FROM hands WHERE outcome <> 'abandoned' {where}", params
            ).fetchone()
            return {"biggest_win": max(row[0] or 0.0, 0.0), "biggest_loss": max(-(row[1] or 0.0), 0.0)}

        session: Optional[Dict[str, Any]] = None
        if self.session_id is not None:
            row = c.execute("SELECT * FROM sessions WHERE session_id = ?", (self.session_id,)).fetchone()
            session = dict(row)
            session.update(hand_extremes("AND session_id = ?", (self.session_id,)))

        row = c.execute(
            """SELECT MAX(peak_bankroll), MIN(lowest_bankroll), MAX(max_drawdown),
                      MAX(longest_win_streak), MAX(longest_loss_streak) FROM sessions"""
        ).fetchone()
        all_time: Dict[str, Any] = {
            "peak_bankroll": row[0],
            "lowest_bankroll": row[1],
            "max_drawdown": row[2] or 0.0,
            "longest_win_streak": row[3] or 0,
            "longest_loss_streak": row[4] or 0,
        }
        all_time.update(hand_extremes("", ()))

        # These overlap on purpose (a doubled hand is also a hard or soft
        # hand), so the stats screen labels the table accordingly.
        categories = (
            ("Hard", "hand_type = 'hard'"),
            ("Soft", "hand_type = 'soft'"),
            ("Pairs", "hand_type = 'pair'"),
            ("Blackjacks", "hand_type = 'blackjack'"),
            ("Doubled", "doubled = 1"),
            ("Split hands", "is_split = 1"),
        )
        hand_types = []
        for label, cond in categories:
            r = c.execute(
                f"""SELECT COUNT(*), COALESCE(SUM(outcome = 'win'), 0), COALESCE(SUM(outcome = 'loss'), 0),
                           COALESCE(SUM(outcome = 'push'), 0), COALESCE(SUM(main_pl), 0)
                    FROM hands WHERE outcome <> 'abandoned' AND {cond}"""
            ).fetchone()
            hand_types.append((label, r[0], r[1], r[2], r[3], r[4]))

        return {
            "path": str(self.path),
            "counts": counts,
            "session": session,
            "all_time": all_time,
            "hand_types": hand_types,
        }

    # ---- export ----

    def export(self, what: str = "all", fmt: str = "csv") -> List[Path]:
        """Write history tables to ~/.cs-blackjack/exports/ and return the
        files written. `what` is hands | sessions | shoes | all."""
        if self.conn is None:
            raise HistoryError(f"History database is unavailable ({self.error}).")
        tables = EXPORT_TABLES if what == "all" else (what,)
        if any(t not in EXPORT_TABLES for t in tables):
            raise HistoryError(f"Can't export '{what}' (choose hands, sessions, shoes, stats, or all).")
        if fmt not in EXPORT_FORMATS:
            raise HistoryError(f"Unknown format '{fmt}' (choose csv or json).")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        written = []
        try:
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            for table in tables:
                cur = self.conn.execute(f"SELECT * FROM {table} ORDER BY 1")
                header = [d[0] for d in cur.description]
                out = EXPORT_DIR / f"{table}-{stamp}.{fmt}"
                self._write_rows(out, header, [tuple(r) for r in cur.fetchall()], fmt)
                written.append(out)
        except (sqlite3.Error, OSError) as exc:
            raise HistoryError(f"Export failed: {exc}")
        return written

    def export_stats(self, session: "GameSession", fmt: str = "csv") -> Path:
        """Write the current lifetime + session counters (the numbers on the
        'stats' screen) as one file."""
        if fmt not in EXPORT_FORMATS:
            raise HistoryError(f"Unknown format '{fmt}' (choose csv or json).")
        flat: Dict[str, Any] = {"bankroll": session.bankroll}
        for key, value in asdict(session.stats).items():
            if isinstance(value, dict):
                flat.update({f"{key}.{k}": v for k, v in value.items()})
            else:
                flat[key] = value
        out = EXPORT_DIR / f"stats-{datetime.now().strftime('%Y%m%d-%H%M%S')}.{fmt}"
        try:
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            if fmt == "json":
                with open(out, "w", encoding="utf8") as fh:
                    json.dump(flat, fh, indent=1, ensure_ascii=False)
                    fh.write("\n")
            else:
                self._write_rows(out, ["metric", "value"], list(flat.items()), fmt)
        except OSError as exc:
            raise HistoryError(f"Export failed: {exc}")
        return out

    @staticmethod
    def _write_rows(path: Path, header: List[str], rows: List[tuple], fmt: str) -> None:
        if fmt == "json":
            with open(path, "w", encoding="utf8") as fh:
                json.dump([dict(zip(header, r)) for r in rows], fh, indent=1, ensure_ascii=False)
                fh.write("\n")
        else:
            with open(path, "w", encoding="utf8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
                writer.writerows(rows)

    # ---- backup / restore ----

    def backup(self, session: Optional["GameSession"] = None, label: str = "") -> str:
        """Snapshot the database (a consistent copy, even mid-session) and
        the saved game state into ~/.cs-blackjack/backups/<timestamp>/.
        Passing the session saves its current state first so the snapshot
        is up to date. Returns the backup's name."""
        if self.conn is None:
            raise HistoryError(f"History database is unavailable ({self.error}).")
        base = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{label}" if label else "")
        name, n = base, 1
        while (BACKUP_DIR / name).exists():
            n += 1
            name = f"{base}-{n}"
        dest = BACKUP_DIR / name
        try:
            dest.mkdir(parents=True)
            if session is not None:
                persist.save_state(
                    session.bankroll, session.rules, session.stats, session.wagers, session.side_bet_wagers
                )
            dst = sqlite3.connect(dest / DB_NAME)
            try:
                self.conn.backup(dst)
            finally:
                dst.close()
            if persist.STATE_PATH.exists():
                shutil.copy2(persist.STATE_PATH, dest / STATE_NAME)
        except (sqlite3.Error, OSError) as exc:
            shutil.rmtree(dest, ignore_errors=True)
            raise HistoryError(f"Backup failed: {exc}")
        return name

    def list_backups(self) -> List[Dict[str, Any]]:
        """Backups on disk, newest first."""
        found = []
        try:
            for d in sorted(BACKUP_DIR.iterdir(), reverse=True):
                db_file = d / DB_NAME
                if d.is_dir() and db_file.exists():
                    found.append(
                        {
                            "name": d.name,
                            "db_bytes": db_file.stat().st_size,
                            "has_state": (d / STATE_NAME).exists(),
                        }
                    )
        except OSError:
            pass
        return found

    def find_backup(self, name: str) -> str:
        """Resolve a backup name (exact, or a unique prefix) to its full
        name, or raise HistoryError."""
        names = [b["name"] for b in self.list_backups()]
        if name in names:
            return name
        matches = [n for n in names if n.startswith(name)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise HistoryError(f"No backup named '{name}' (run 'backups' to list them).")
        raise HistoryError(f"'{name}' matches {len(matches)} backups -- type more of the name.")

    def restore(self, session: "GameSession", name: str) -> persist.State:
        """Replace the database and the saved-state file with a backup's and
        return the backup's parsed state for the caller to load. A safety
        backup of the current data is taken first, and the backup is fully
        validated before anything is touched. The caller starts a new
        session/shoe afterward -- the old ids mean nothing in the new
        database, so they're cleared here."""
        if self.conn is None:
            raise HistoryError(f"History database is unavailable ({self.error}).")
        name = self.find_backup(name)
        src = BACKUP_DIR / name
        if not (src / STATE_NAME).exists():
            raise HistoryError(f"Backup '{name}' has no saved game state.")
        try:
            state = persist.read_state_file(src / STATE_NAME)
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            raise HistoryError(f"Backup '{name}' has unreadable saved state.")
        _check_database(src / DB_NAME)

        self.end_session(session, "restore")
        try:
            safety = self.backup(session, label="pre-restore")
        except HistoryError:
            self.start_session(session)  # nothing was touched -- carry on logging into a fresh session row
            raise
        tmp = self.path.with_name(self.path.name + ".restoring")
        try:
            self.conn.close()
            self.conn = None
            _copy_database(src / DB_NAME, tmp)
            for suffix in ("-journal", "-wal", "-shm"):  # leftovers of the database being replaced
                Path(str(self.path) + suffix).unlink(missing_ok=True)
            os.replace(tmp, self.path)
            persist.atomic_write_text(persist.STATE_PATH, (src / STATE_NAME).read_text(encoding="utf8"))
        except (sqlite3.Error, OSError) as exc:
            tmp.unlink(missing_ok=True)
            self._connect()  # whatever is on disk now -- the old database, unless the swap already happened
            self.start_session(session)
            raise HistoryError(f"Restore failed: {exc} -- your previous data is safe in backup '{safety}'.")
        # The old session/shoe ids mean nothing in the restored database.
        self.session_id = None
        self.shoe_id = None
        self._last_round = None
        self._connect()
        return state
