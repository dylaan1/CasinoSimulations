"""SQLite history log: every hand, session, and shoe ever played.

The database lives at ~/.cs-blackjack/blackjack.db and is meant to be read
from outside the game (sqlite3, DB Browser for SQLite, DBeaver, pandas...)
without launching it. Three tables, joined by ids:

  sessions  one row per session -- from launch, or from a 'newsession',
            until the next of those or quit
  shoes     one row per unique shuffle, with its deck count, penetration,
            and the exact card order (card_order)
  hands     one row per player hand settled (a split spot logs one row per
            resulting hand); round_id groups the hands dealt together

plus imported_stats (lifetime numbers from before the database existed) and
two read-only views (hand_type_summary, bet_size_summary). Every number the
game shows on its stats panels is computed from these tables -- see
HistoryDB.load_stats -- so the database is the single source of truth.

Conventions:
  * Timestamps are UTC ISO-8601 text ("2026-09-29T15:04:05Z"); in SQLite,
    datetime(col, 'localtime') converts them.
  * Booleans are 0/1 integers, money is REAL dollars.
  * A card is a two-character token -- rank (T = ten) then suit glyph, e.g.
    "T♦" -- and a card sequence is those tokens run together, "K♣T♦3♠".
  * shoes.card_order is the shuffle in dealing order. The order is only ever
    held in memory while a shoe is in play: each round appends the cards it
    dealt, and once the shoe is retired -- on a reshuffle, or on any way of
    leaving the game short of the process being killed outright -- the cards
    that were never dealt are added after a "|", so "K♣T♦3♠|7♥A♠..." reads
    dealt | never dealt. No "|" means the shoe is still in play, or was cut
    off by a hard kill (power loss, SIGKILL) that gave the game no chance to
    write the rest.
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
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from . import persist
from .cards import cards_to_string
from .hand import Hand
from .stats import Stats

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

# The lifetime Stats fields, split by whether they're counts or dollar amounts
# (the counters an imported pre-database baseline can add to).
_LIFETIME_COUNTS = (
    "hands_lifetime", "player_wins", "dealer_wins", "pushes", "surrenders_lifetime", "sessions_played",
)
_LIFETIME_MONEY = (
    "lifetime_main_wagered", "lifetime_main_pl", "lifetime_sidebet_pl", "lifetime_power_poker_pl", "lifetime_star21_pl",
)
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
    end_reason          TEXT,                -- quit | newsession | restore | abandoned (crashed or killed); older versions also wrote hardreset
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
    cut_reason       TEXT    NOT NULL,   -- start | penetration | newshoe | newsession | mid_round (shoe ran out during a round) | restore (older versions also wrote hardreset)
    num_decks        INTEGER NOT NULL,
    penetration      REAL    NOT NULL,   -- fraction of the shoe dealt before it is reshuffled
    total_cards      INTEGER NOT NULL,
    cards_dealt      INTEGER NOT NULL DEFAULT 0,
    blackjack_payout REAL    NOT NULL,   -- 1.5 = 3:2, 1.2 = 6:5, as active for this shoe
    hit_soft_17      INTEGER NOT NULL,
    rules_json       TEXT    NOT NULL,   -- every table rule and side-bet payout as of the cut
    card_order       TEXT    NOT NULL    -- dealt cards in order, then "|", then the never-dealt rest (see module doc)
);

CREATE TABLE hands (
    hand_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id               INTEGER NOT NULL,
    session_id             INTEGER REFERENCES sessions (session_id),
    shoe_id                INTEGER REFERENCES shoes (shoe_id),   -- the shoe the round STARTED on (see reshuffled_mid_round)
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

# v2: lifetime stats now come from the database, so the numbers an older
# version of the game counted itself (before there was a database) get a home;
# and card_order gains its dealt|never-dealt marker -- every v1 row already
# holds its whole shuffle, so it just needs the "|" put in at cards_dealt.
_SCHEMA_V2 = """
CREATE TABLE imported_stats (
    stat_key    TEXT PRIMARY KEY,   -- a lifetime counter (hands_lifetime, lifetime_main_pl, ...) or occurrence:<bet>:<category> / win:<bet>:<category>
    stat_value  REAL NOT NULL,
    imported_at TEXT NOT NULL
);

UPDATE shoes
SET card_order = substr(card_order, 1, 2 * cards_dealt) || '|' || substr(card_order, 2 * cards_dealt + 1)
WHERE instr(card_order, '|') = 0;
"""

# v3: a shoe that runs out of cards mid-round is reshuffled around the cards on
# the table and the round finishes (Round._draw). That round's hands then
# straddle two shoes, so they're flagged: shoe_id and the *_before columns
# (running/true count, cards dealt) describe the shoe the round STARTED on,
# and the cards drawn after the reshuffle came from the next shoe row
# (cut_reason 'mid_round'). For strict count-versus-bet analysis, filter these
# rounds out with WHERE reshuffled_mid_round = 0.
_SCHEMA_V3 = """
ALTER TABLE hands ADD COLUMN reshuffled_mid_round INTEGER NOT NULL DEFAULT 0;
"""

_MIGRATIONS = [_SCHEMA_V1, _SCHEMA_V2, _SCHEMA_V3]
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


def _merge_counts(a: Dict[str, int], b: Dict[str, int]) -> Dict[str, int]:
    merged = dict(a)
    for key, n in b.items():
        merged[key] = merged.get(key, 0) + n
    return merged


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


# ---- MySQL dump ----------------------------------------------------------
# The MySQL table definitions are generated from the SQLite ones (PRAGMA
# table_info and friends) rather than written out by hand, so they can never
# drift from the real schema as it grows.

_MYSQL_TABLE_ORDER = ("sessions", "shoes", "hands")  # parents before children; anything else follows
_MYSQL_ROWS_PER_INSERT = 250
_MYSQL_ESCAPES = {"\\": "\\\\", "'": "''", "\0": "\\0", "\n": "\\n", "\r": "\\r", "\x1a": "\\Z"}


def _mysql_quote(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _mysql_string(value: str) -> str:
    return "'" + "".join(_MYSQL_ESCAPES.get(ch, ch) for ch in value) + "'"


def _mysql_literal(value: Any, column: str) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value) if value == value and value not in (float("inf"), float("-inf")) else "NULL"
    text = str(value)
    if column.endswith("_at"):  # UTC ISO-8601 text -> a MySQL DATETIME literal
        text = text.replace("T", " ").rstrip("Z")
    return _mysql_string(text)


def _mysql_table_ddl(conn: sqlite3.Connection, table: str) -> str:
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    pk_columns = [c["name"] for c in columns if c["pk"]]
    lines = []
    for c in columns:
        name, declared = c["name"], (c["type"] or "").upper()
        if name.endswith("_at"):
            sql_type = "DATETIME"
        elif "INT" in declared:
            sql_type = "INT"
        elif declared in ("REAL", "FLOAT", "DOUBLE"):
            sql_type = "DOUBLE"
        else:
            sql_type = "VARCHAR(255)" if c["pk"] else "TEXT"  # MySQL can't key a bare TEXT column
        parts = [_mysql_quote(name), sql_type]
        if c["notnull"] or c["pk"]:
            parts.append("NOT NULL")
        if c["pk"] and sql_type == "INT" and len(pk_columns) == 1:
            parts.append("AUTO_INCREMENT")
        if c["dflt_value"] is not None and sql_type != "TEXT":
            parts.append(f"DEFAULT {c['dflt_value']}")
        lines.append("  " + " ".join(parts))
    if pk_columns:
        lines.append("  PRIMARY KEY (" + ", ".join(_mysql_quote(n) for n in pk_columns) + ")")
    for idx in conn.execute(f"PRAGMA index_list({table})").fetchall():
        if idx["origin"] != "c":  # only the CREATE INDEX ones; primary keys are declared above
            continue
        cols = [r["name"] for r in conn.execute(f"PRAGMA index_info({idx['name']})").fetchall()]
        lines.append(f"  KEY {_mysql_quote(idx['name'])} (" + ", ".join(_mysql_quote(n) for n in cols) + ")")
    for fk in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
        child, parent, parent_col = fk["from"], fk["table"], fk["to"]
        lines.append(
            f"  CONSTRAINT {_mysql_quote('fk_' + table + '_' + child)} "
            f"FOREIGN KEY ({_mysql_quote(child)}) REFERENCES {_mysql_quote(parent)} ({_mysql_quote(parent_col)})"
        )
    return (
        f"CREATE TABLE {_mysql_quote(table)} (\n" + ",\n".join(lines) + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
    )


def _mysql_dump(conn: sqlite3.Connection):
    """Yield the dump script piece by piece (rows are streamed, not held)."""
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    tables.sort(key=lambda t: (_MYSQL_TABLE_ORDER.index(t) if t in _MYSQL_TABLE_ORDER else len(_MYSQL_TABLE_ORDER), t))
    views = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'view' ORDER BY name").fetchall()

    yield (
        "-- cs-blackjack history export for MySQL / MariaDB\n"
        f"-- Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} from {DB_NAME}. All timestamps are UTC.\n"
        "--\n"
        "-- Load it into an EMPTY schema you've chosen (it drops and recreates these tables):\n"
        "--   mysql -u USER -p SCHEMA_NAME < this-file.sql\n"
        "-- or in MySQL Workbench: Server > Data Import > Import from Self-Contained File,\n"
        "-- with the target schema selected.\n\n"
        "SET NAMES utf8mb4;\n"
        "SET SESSION sql_mode = REPLACE(@@sql_mode, 'NO_BACKSLASH_ESCAPES', '');\n"
        "SET SESSION time_zone = '+00:00';\n"
        "SET FOREIGN_KEY_CHECKS = 0;\n\n"
    )
    for view in views:
        yield f"DROP VIEW IF EXISTS {_mysql_quote(view['name'])};\n"
    for table in reversed(tables):
        yield f"DROP TABLE IF EXISTS {_mysql_quote(table)};\n"
    yield "\n"
    for table in tables:
        yield _mysql_table_ddl(conn, table) + "\n"
        columns = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        header = f"INSERT INTO {_mysql_quote(table)} (" + ", ".join(_mysql_quote(c) for c in columns) + ") VALUES\n"
        cursor = conn.execute(f"SELECT * FROM {table} ORDER BY 1")
        while True:
            batch = cursor.fetchmany(_MYSQL_ROWS_PER_INSERT)
            if not batch:
                break
            rows = ",\n".join(
                "(" + ", ".join(_mysql_literal(row[i], columns[i]) for i in range(len(columns))) + ")" for row in batch
            )
            yield header + rows + ";\n"
        yield "\n"
    for view in views:
        yield view["sql"].rstrip().rstrip(";") + ";\n\n"
    yield "SET FOREIGN_KEY_CHECKS = 1;\n"


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
        self._life_cache: Optional[Dict[str, Any]] = None  # lifetime aggregates over the hands table, see _lifetime_metrics
        # Rounds whose rows are ready but not yet in the database because a
        # write failed (typically another program holding the database
        # locked). They're kept, in order, and written with the next
        # successful write -- a round is never dropped just because the
        # database was busy for a moment.
        self._pending_rounds: List[List[Dict[str, Any]]] = []
        # The same goes for shoe changes (a shoe closing, the next one being
        # cut): they wait here, in order, until they can be written. A shoe
        # whose row couldn't be created yet has a provisional (negative) id,
        # which rounds played on it carry until the real one is known.
        self._pending_shoe_ops: List[Tuple[str, int, Dict[str, Any]]] = []
        self._shoe_ids: Dict[int, int] = {}  # provisional id -> real id, once written
        self._provisional_shoe_id = 0
        self._flush_failed = False

    @property
    def pending_rounds(self) -> int:
        return len(self._pending_rounds)

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
            self._life_cache = None
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
        self._refresh_stats(session)

    def _session_fields(self, session: "GameSession", track: _Tracking) -> Dict[str, Any]:
        """The session row's current values, all computed from the session's
        own hand rows (call inside the transaction that wrote them) -- the
        same numbers, from the same code, that the stats panels show -- plus
        the bankroll figures tracked as the session goes."""
        m = self._session_metrics(self.session_id)
        return {
            "ending_bankroll": session.bankroll,
            "peak_bankroll": track.peak_bankroll,
            "lowest_bankroll": track.lowest_bankroll,
            "max_drawdown": track.max_drawdown,
            "rounds_played": track.rounds,
            "hands_played": m["hands_this_session"],
            "hands_won": m["session_player_wins"],
            "hands_lost": m["session_dealer_wins"],
            "hands_pushed": m["session_pushes"],
            "hands_surrendered": m["surrenders"],
            "doubles": m["doubles"],
            "splits": m["splits"],
            "aces_split": m["aces_split"],
            "tens_split": m["tens_split"],
            "player_blackjacks": m["player_blackjacks"],
            "dealer_blackjacks": m["dealer_blackjacks"],
            "dealer_pulled_21s": m["greg_specials"],
            "dealer_busts": m["dealer_busts"],
            "shoes_played": m["shoes_played"],
            "main_wagered": m["main_wagered"],
            "main_pl": m["session_main_pl"],
            "sidebet_pl": m["session_sidebet_pl"],
            "net_pl": m["session_main_pl"] + m["session_sidebet_pl"],
            "longest_win_streak": m["longest_win_streak"],
            "longest_loss_streak": m["longest_loss_streak"],
        }

    @_guarded(default=False)
    def end_session(self, session: "GameSession", reason: str) -> bool:
        if self.session_id is None:
            return True
        if not self._flush_pending(session):
            return False
        fields = self._session_fields(session, self._track)
        fields.update(ended_at=_now(), end_reason=reason)
        with self.conn:
            self._update("sessions", "session_id", self.session_id, fields)
        self.session_id = None
        return True

    # ---- shoes ----

    @_guarded()
    def shoe_cut(self, session: "GameSession", reason: str) -> None:
        shoe = session.shoe
        fields = {
            "session_id": self.session_id,
            "cut_at": _now(),
            "cut_reason": reason,
            "num_decks": shoe.num_decks,
            "penetration": shoe.effective_penetration,
            "total_cards": shoe.total_cards,
            "blackjack_payout": session.active_rules.blackjack_payout,
            "hit_soft_17": int(session.active_rules.hit_soft_17),
            "rules_json": json.dumps(session.rules.to_dict(), sort_keys=True),
            # The shuffle exists only in memory for now: cards are
            # written as they're dealt, the rest when the shoe retires.
            "card_order": "",
        }
        # If the database is busy the row can't be created yet; the shoe
        # carries a provisional id until it can (see _flush_shoe_ops).
        self._provisional_shoe_id -= 1
        self.shoe_id = self._provisional_shoe_id
        self._pending_shoe_ops.append(("cut", self.shoe_id, fields))
        self._flush_shoe_ops()
        self._refresh_stats(session)

    @_guarded(default=False)
    def shoe_retired(self, session: "GameSession") -> bool:
        """The shoe is done with: record how much of it was dealt and, at
        last, the cards that never were -- after a "|" so they can't be
        mistaken for dealt ones. Returns whether it was written (if not, it
        is kept and written as soon as the database allows)."""
        if self.shoe_id is None:
            return True
        shoe = session.shoe
        fields = {
            "cards_dealt": shoe.cards_dealt,
            "penetration": shoe.effective_penetration,
            "card_order": f"{shoe.dealt_string()}|{shoe.undealt_string()}",
            "retired_at": _now(),
        }
        # (a retry for the same shoe replaces the earlier attempt)
        self._pending_shoe_ops = [op for op in self._pending_shoe_ops if not (op[0] == "retire" and op[1] == self.shoe_id)]
        self._pending_shoe_ops.append(("retire", self.shoe_id, fields))
        return self._flush_shoe_ops()

    def _flush_shoe_ops(self) -> bool:
        """Write the queued shoe changes, in order, in one transaction. Returns
        True when none are left waiting. Until it has succeeded the shoe rows
        just stay as they were, and nothing is mixed up: a shoe that couldn't
        be created yet keeps its provisional id, and the cards dealt from it
        are written to its own row once it exists."""
        if not self._pending_shoe_ops:
            return True
        if self.conn is None:
            return False
        created: Dict[int, int] = {}
        try:
            with self.conn:
                for kind, ref, fields in self._pending_shoe_ops:
                    if kind == "cut":
                        created[ref] = self._insert("shoes", fields)
                    else:
                        real = created.get(ref, self._shoe_ids.get(ref, ref))
                        self._update("shoes", "shoe_id", real, fields)
        except (sqlite3.Error, OSError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self._flush_failed = True
            return False
        self._shoe_ids.update(created)
        self._pending_shoe_ops.clear()
        if self.shoe_id in self._shoe_ids:
            self.shoe_id = self._shoe_ids[self.shoe_id]
        if self._flush_failed and not self._pending_rounds:
            self.error = None
            self._flush_failed = False
        return True

    @_guarded()
    def close(self, session: "GameSession", reason: str = "quit") -> None:
        # This is the last chance to write anything, so if the database is
        # busy (another program holds it), try a second time before giving up.
        for attempt in range(2):
            if self._flush_pending(session) and self.shoe_retired(session) and self.end_session(session, reason):
                break
            if attempt == 0:
                time.sleep(0.5)
        self.conn.close()
        self.conn = None

    # ---- stats: every number on the stats panels, computed from the tables ----

    def _refresh_stats(self, session: "GameSession") -> None:
        """Replace session.stats with a fresh read of the database."""
        stats = self.load_stats()
        if stats is not None:
            session.stats = stats

    @_guarded()
    def load_stats(self) -> Stats:
        """Build the Stats the game displays: lifetime totals over everything
        in the database (plus the imported pre-database baseline) and this
        session's own numbers. Hand tallies count settled hands only; the
        money figures also include the forfeited wager of a hand still
        unsettled when the game was quit ('abandoned'), since that money is
        genuinely gone from the bankroll."""
        stats = Stats()
        life = self._lifetime_metrics()
        base_numeric, base_occurrences, base_wins = self._baseline()
        for name in _LIFETIME_COUNTS:
            setattr(stats, name, int(life[name] + base_numeric.get(name, 0)))
        for name in _LIFETIME_MONEY:
            setattr(stats, name, float(life[name] + base_numeric.get(name, 0.0)))
        stats.sidebet_occurrences = _merge_counts(life["sidebet_occurrences"], base_occurrences)
        stats.sidebet_wins = _merge_counts(life["sidebet_wins"], base_wins)
        if self.session_id is not None:
            for name, value in self._session_metrics(self.session_id).items():
                if hasattr(stats, name):
                    setattr(stats, name, value)
        return stats

    def _session_metrics(self, sid: int) -> Dict[str, Any]:
        """One session's numbers, keyed by the Stats field they fill (plus
        main_wagered, which only the sessions table keeps)."""
        c = self.conn
        hands, won, lost, pushed, surrendered, doubles, blackjacks, wagered, main_pl, side_pl = c.execute(
            """SELECT COALESCE(SUM(outcome <> 'abandoned'), 0), COALESCE(SUM(outcome = 'win'), 0),
                      COALESCE(SUM(outcome = 'loss'), 0), COALESCE(SUM(outcome = 'push'), 0),
                      COALESCE(SUM(outcome = 'surrender'), 0), COALESCE(SUM(doubled), 0),
                      COALESCE(SUM(player_blackjack), 0), COALESCE(SUM(final_bet), 0),
                      COALESCE(SUM(main_pl), 0), COALESCE(SUM(sidebet_pl), 0)
               FROM hands WHERE session_id = ?""",
            (sid,),
        ).fetchone()

        def splits(where: str) -> int:
            # A spot that ends up with n hands was split n - 1 times.
            return c.execute(
                f"""SELECT COALESCE(SUM(n - 1), 0) FROM
                      (SELECT COUNT(*) AS n FROM hands WHERE session_id = ? AND {where}
                       GROUP BY round_id, spot_number)""",
                (sid,),
            ).fetchone()[0]

        dealer_bj, dealer_21, dealer_bust = c.execute(
            """SELECT COUNT(DISTINCT CASE WHEN dealer_blackjack = 1 THEN round_id END),
                      COUNT(DISTINCT CASE WHEN dealer_total = 21 AND dealer_blackjack = 0 AND dealer_bust = 0
                                          THEN round_id END),
                      COUNT(DISTINCT CASE WHEN dealer_bust = 1 THEN round_id END)
               FROM hands WHERE session_id = ? AND outcome <> 'abandoned'""",
            (sid,),
        ).fetchone()

        streak = longest_win = longest_loss = 0
        for (outcome,) in c.execute(
            "SELECT outcome FROM hands WHERE session_id = ? AND outcome IN ('win', 'loss') ORDER BY hand_id", (sid,)
        ):
            if outcome == "win":
                streak = streak + 1 if streak >= 0 else 1
                longest_win = max(longest_win, streak)
            else:
                streak = streak - 1 if streak <= 0 else -1
                longest_loss = max(longest_loss, -streak)

        return {
            "hands_this_session": hands,
            "session_player_wins": won,
            "session_dealer_wins": lost,
            "session_pushes": pushed,
            "surrenders": surrendered,
            "doubles": doubles,
            "splits": splits("is_split = 1"),
            "aces_split": splits("is_split_aces = 1"),
            "tens_split": splits("is_split = 1 AND is_split_aces = 0 AND substr(player_cards, 1, 1) IN ('T', 'J', 'Q', 'K')"),
            "player_blackjacks": blackjacks,
            "dealer_blackjacks": dealer_bj,
            "greg_specials": dealer_21,
            "dealer_busts": dealer_bust,
            "current_streak": streak,
            "longest_win_streak": longest_win,
            "longest_loss_streak": longest_loss,
            "shoes_played": c.execute("SELECT COUNT(*) FROM shoes WHERE session_id = ?", (sid,)).fetchone()[0],
            "main_wagered": wagered,
            "session_main_pl": main_pl,
            "session_sidebet_pl": side_pl,
        }

    def _lifetime_metrics(self) -> Dict[str, Any]:
        """Lifetime totals from the tables alone (no imported baseline),
        keyed by Stats field, with the per-category side-bet dicts.

        The whole hands table is scanned once; after that each recorded round
        just adds its own rows (_add_round_to_lifetime), so this stays fast
        however large the database grows."""
        if self._life_cache is None:
            self._life_cache = self._scan_lifetime("")
        metrics = dict(self._life_cache)
        metrics["sessions_played"] = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        return metrics

    def _scan_lifetime(self, where: str, params: tuple = ()) -> Dict[str, Any]:
        """The lifetime aggregates over the hands rows matching `where` (all of
        them when empty)."""
        c = self.conn
        hands, won, lost, pushed, surrendered, wagered, main_pl, side_pl, pp_pl, s21_pl = c.execute(
            f"""SELECT COALESCE(SUM(outcome <> 'abandoned'), 0), COALESCE(SUM(outcome = 'win'), 0),
                       COALESCE(SUM(outcome = 'loss'), 0), COALESCE(SUM(outcome = 'push'), 0),
                       COALESCE(SUM(outcome = 'surrender'), 0), COALESCE(SUM(final_bet), 0),
                       COALESCE(SUM(main_pl), 0), COALESCE(SUM(sidebet_pl), 0),
                       COALESCE(SUM(power_poker_pl), 0), COALESCE(SUM(star21_pl), 0)
                FROM hands {where}""",
            params,
        ).fetchone()
        occurrences: Dict[str, int] = {}
        wins: Dict[str, int] = {}
        # Power Poker and Star 21 log their category on each spot's first hand
        # (wagered or not); Dealer Buster is one event per round however many
        # spots there were, but pays out per wagered spot.
        for bet, counted in (
            ("power_poker", "COUNT(*)"),
            ("star21", "COUNT(*)"),
            ("dealer_buster", "COUNT(DISTINCT round_id)"),
        ):
            clause = f"{where + ' AND' if where else 'WHERE'} {bet}_category IS NOT NULL"
            for category, n, paid in c.execute(
                f"""SELECT {bet}_category, {counted}, COALESCE(SUM({bet}_wager > 0), 0) FROM hands
                    {clause} GROUP BY {bet}_category""",
                params,
            ):
                occurrences[f"{bet}:{category}"] = n
                if paid:
                    wins[f"{bet}:{category}"] = paid
        return {
            "hands_lifetime": hands,
            "player_wins": won,
            "dealer_wins": lost,
            "pushes": pushed,
            "surrenders_lifetime": surrendered,
            "lifetime_main_wagered": wagered,
            "lifetime_main_pl": main_pl,
            "lifetime_sidebet_pl": side_pl,
            "lifetime_power_poker_pl": pp_pl,
            "lifetime_star21_pl": s21_pl,
            "sidebet_occurrences": occurrences,
            "sidebet_wins": wins,
        }

    def _add_round_to_lifetime(self, round_id: int) -> None:
        """Fold one just-recorded round into the cached lifetime totals."""
        if self._life_cache is None:
            return  # nothing cached yet: the next read scans everything, this round included
        delta = self._scan_lifetime("WHERE round_id = ?", (round_id,))
        merged: Dict[str, Any] = {}
        for key, value in self._life_cache.items():
            if key in ("sidebet_occurrences", "sidebet_wins"):
                merged[key] = _merge_counts(value, delta[key])
            else:
                merged[key] = value + delta[key]
        self._life_cache = merged

    def _baseline(self) -> Tuple[Dict[str, float], Dict[str, int], Dict[str, int]]:
        """The imported pre-database lifetime numbers: (counters, side-bet
        occurrences, side-bet wins)."""
        numeric: Dict[str, float] = {}
        occurrences: Dict[str, int] = {}
        wins: Dict[str, int] = {}
        for key, value in self.conn.execute("SELECT stat_key, stat_value FROM imported_stats"):
            if key.startswith("occurrence:"):
                occurrences[key[len("occurrence:"):]] = int(value)
            elif key.startswith("win:"):
                wins[key[len("win:"):]] = int(value)
            else:
                numeric[key] = value
        return numeric, occurrences, wins

    def import_pending_legacy_stats(self) -> bool:
        """Take in the lifetime stats an older version of the game kept in its
        state file (before there was a database), once. Returns True when
        nothing is left waiting -- either there was nothing, or it's now in
        the database -- and False if it couldn't be imported (it then stays in
        the state file, untouched, for the next launch).

        The older counters also kept counting alongside the database for any
        play logged since it was introduced, so only the part the database
        doesn't already hold is imported: for each figure, the older total
        minus what the tables now say. Counts are never taken below zero;
        money figures can validly be negative (a losing side bet), so they
        keep their sign."""
        block = persist.pending_legacy_stats()
        if not block:
            return True
        if self.conn is None:
            return False
        try:
            with self.conn:
                if self.conn.execute("SELECT COUNT(*) FROM imported_stats").fetchone()[0] == 0:
                    legacy = Stats.from_legacy_dict(block)
                    db = self._lifetime_metrics()
                    now = _now()
                    rows: Dict[str, float] = {}
                    for name in _LIFETIME_COUNTS:
                        rows[name] = max(0, getattr(legacy, name) - db[name])
                    for name in _LIFETIME_MONEY:
                        rows[name] = getattr(legacy, name) - db[name]
                    for prefix, legacy_counts, db_counts in (
                        ("occurrence", legacy.sidebet_occurrences, db["sidebet_occurrences"]),
                        ("win", legacy.sidebet_wins, db["sidebet_wins"]),
                    ):
                        for key, n in legacy_counts.items():
                            rows[f"{prefix}:{key}"] = max(0, n - db_counts.get(key, 0))
                    self.conn.executemany(
                        "INSERT INTO imported_stats (stat_key, stat_value, imported_at) VALUES (?, ?, ?)",
                        [(k, float(v), now) for k, v in rows.items() if abs(v) > 1e-9],
                    )
        except (sqlite3.Error, ValueError, TypeError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return False
        persist.clear_legacy_stats()
        return True

    # ---- rounds / hands ----

    def _round_rows(self, session: "GameSession", round_: "Round") -> List[Dict[str, Any]]:
        dealer = round_.dealer_hand
        common: Dict[str, Any] = {
            "session_id": self.session_id,
            # The shoe the round STARTED on -- if the shoe ran out mid-round
            # the log has moved on to a new one, and the *_before figures
            # below belong to the old one.
            "shoe_id": round_.history_shoe_id if round_.history_shoe_id is not None else self.shoe_id,
            "reshuffled_mid_round": int(round_.reshuffled_mid_round),
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
        rows = self._round_rows(session, round_)   # a plain snapshot of the round, taken now
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

        # From here the round is safely in hand: it's queued, so even if the
        # write below fails it stays queued for the next attempt.
        self._track = track
        self._last_round = round_
        self._pending_rounds.append(rows)
        self._flush_pending(session)

    def _flush_pending(self, session: "GameSession") -> bool:
        """Write every queued round, in order, in one transaction, and bring
        the session and shoe rows up to date. Returns True if nothing is
        left waiting (which includes there having been nothing to write)."""
        if not self._pending_rounds:
            return self._flush_shoe_ops()
        if self.conn is None:
            return False
        if not self._flush_shoe_ops():  # the shoes first: the rounds refer to them
            return False
        round_ids: List[int] = []
        try:
            with self.conn:
                for rows in self._pending_rounds:
                    round_id = self.conn.execute("SELECT COALESCE(MAX(round_id), 0) + 1 FROM hands").fetchone()[0]
                    for row in rows:
                        shoe_id = self._shoe_ids.get(row["shoe_id"], row["shoe_id"])
                        self._insert("hands", {**row, "round_id": round_id, "shoe_id": shoe_id})
                    round_ids.append(round_id)
                self._update("sessions", "session_id", self.session_id, self._session_fields(session, self._track))
                if self.shoe_id is not None:
                    self._update(
                        "shoes", "shoe_id", self.shoe_id,
                        {
                            "cards_dealt": session.shoe.cards_dealt,
                            "penetration": session.shoe.effective_penetration,
                            "card_order": session.shoe.dealt_string(),  # the cards dealt so far, in order
                        },
                    )
        except (sqlite3.Error, OSError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self._flush_failed = True
            return False
        self._pending_rounds.clear()
        for round_id in round_ids:
            self._add_round_to_lifetime(round_id)
        self._refresh_stats(session)
        if self._flush_failed:  # a problem earlier, and the queue has now cleared: recovered
            self.error = None
            self._flush_failed = False
        return True

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

    def export_mysql(self) -> Path:
        """Write ~/.cs-blackjack/exports/mysql-<timestamp>.sql: the whole
        database as a self-contained MySQL/MariaDB script (tables, rows,
        views) that recreates it in an empty schema."""
        if self.conn is None:
            raise HistoryError(f"History database is unavailable ({self.error}).")
        out = EXPORT_DIR / f"mysql-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sql"
        try:
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf8", newline="\n") as fh:
                for chunk in _mysql_dump(self.conn):
                    fh.write(chunk)
        except (sqlite3.Error, OSError) as exc:
            out.unlink(missing_ok=True)
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
                persist.save_state(session.bankroll, session.rules, session.wagers, session.side_bet_wagers)
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

        if not self.end_session(session, "restore"):
            raise HistoryError("The history database is busy -- nothing was changed. Try again in a moment.")
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
        # A backup made before stats moved into the database carries its
        # lifetime numbers in its state file; the same one-time import applies.
        persist.set_legacy_stats(persist.read_legacy_stats(persist.STATE_PATH))
        self.import_pending_legacy_stats()
        return state
