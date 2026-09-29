"""Stats come from the history database: the one-time import of an older game's lifetime numbers (a SYNTHETIC
state file -- never anyone's real one), how the import combines with what the database already holds, the
incremental lifetime cache against a full rescan, session vs lifetime figures, and the removed hardreset."""
import json
import random
from pathlib import Path

from _support import *  # noqa: F401,F403
import _support as S

check = S.Checker()

# a made-up "older version" state file: lifetime stats kept in the file itself, before there was a database
LEGACY = {
    "schema_version": 2,
    "bankroll": 5321.5,
    "rules": {},
    "wagers": [25, 0, 0],
    "stats": {
        "hands_lifetime": 1000, "player_wins": 430, "dealer_wins": 480, "pushes": 60, "surrenders_lifetime": 30,
        "sessions_played": 12,
        "lifetime_main_wagered": 25000.0, "lifetime_main_pl": -750.0,
        "lifetime_sidebet_pl": 120.0, "lifetime_power_poker_pl": 100.0, "lifetime_star21_pl": 20.0,
        "sidebet_occurrences": {"power_poker:flush": 9, "dealer_buster:8+": 4},
        "sidebet_wins": {"power_poker:flush": 3},
        "royal_flushes": 2,                      # an even older special-cased counter -> power_poker:royalflush
    },
}


def open_game(hist=None):
    bankroll, rules, wagers, sbw = persist.load_state()
    hist = hist or history.HistoryDB.open()
    hist.import_pending_legacy_stats()
    s = engine.GameSession(bankroll, rules, wagers, sbw, history=hist)
    s.ensure_shoe_ready()
    return s, hist


def play(s, n, seed=0, wager=10):
    rng = random.Random(seed)
    for _ in range(n):
        s.wagers[0] = wager
        r, err = S.play_round(s, rng, "basic")
        assert r, err
        s.history.record_round(s, r)
        s.ensure_shoe_ready()


def rescan(hist):
    """The lifetime figures recomputed from scratch, bypassing the incremental cache."""
    hist._life_cache = None
    return hist.load_stats()


LIFE = [*history._LIFETIME_COUNTS, *history._LIFETIME_MONEY]


def same_stats(a, b):
    return (all(abs(getattr(a, n) - getattr(b, n)) < 1e-6 for n in LIFE)
            and a.sidebet_occurrences == b.sidebet_occurrences and a.sidebet_wins == b.sidebet_wins)


# ------------------------------------------------------------------ a fresh install has nothing to import
S.reset_data()
s, hist = open_game()
check(persist.pending_legacy_stats() is None, "no state file -> nothing to import")
check(s.stats.hands_lifetime == 0 and s.stats.lifetime_main_pl == 0 and s.stats.sessions_played == 1, "a fresh install starts every lifetime figure at zero (this session counts as session 1)")
hist.close(s)

# ------------------------------------------------------------------ the one-time import
S.reset_data()
Path(persist.STATE_PATH).write_text(json.dumps(LEGACY))
s, hist = open_game()
check(persist.pending_legacy_stats() is None, "after the import, nothing is left waiting in memory")
st = s.stats
check((st.hands_lifetime, st.player_wins, st.dealer_wins, st.pushes, st.surrenders_lifetime) == (1000, 430, 480, 60, 30),
      "the hand tallies come across exactly")
check(st.sessions_played == 12 + 1, f"sessions played = the 12 the old game counted + this new one ({st.sessions_played})")
check(abs(st.lifetime_main_wagered - 25000) < 1e-9 and abs(st.lifetime_main_pl + 750) < 1e-9 and abs(st.lifetime_sidebet_pl - 120) < 1e-9
      and abs(st.lifetime_power_poker_pl - 100) < 1e-9 and abs(st.lifetime_star21_pl - 20) < 1e-9, "the money figures come across exactly")
check(st.sidebet_occurrences == {"power_poker:flush": 9, "dealer_buster:8+": 4, "power_poker:royalflush": 2},
      f"side-bet occurrences come across, including the oldest special-cased counter: {st.sidebet_occurrences}")
check(st.sidebet_wins == {"power_poker:flush": 3}, "side-bet wins come across")
check(st.hands_this_session == 0 and st.session_main_pl == 0, "the imported numbers are lifetime only -- this session starts at zero")
check(abs(st.ev_percent() - (-750 / 25000 * 100)) < 1e-9, f"EV% works from the imported baseline ({st.ev_percent():.2f}%)")
rows = hist.conn.execute("select count(*) from imported_stats").fetchone()[0]
check(rows > 0, f"the baseline is stored in the database (imported_stats: {rows} rows), where MySQL can see it")
persist.save_state(s.bankroll, s.rules, s.wagers, s.side_bet_wagers)
check("stats" not in json.loads(persist.STATE_PATH.read_text()), "...and the next save drops it from the state file")
check(abs(st.lifetime_power_poker_pl - 100) < 1e-9 and st.lifetime_main_pl < 0, "(a NEGATIVE imported figure keeps its sign: main P/L -750 is not clamped to zero)")

# new play adds on top; the baseline is never double counted
play(s, 40, seed=3)
n_hands = hist.conn.execute("select count(*) from hands where outcome <> 'abandoned'").fetchone()[0]
check(s.stats.hands_lifetime == 1000 + n_hands and s.stats.hands_this_session == n_hands, f"1000 imported + {n_hands} new = {s.stats.hands_lifetime}")
pl = hist.conn.execute("select sum(main_pl) from hands").fetchone()[0]
check(abs(s.stats.lifetime_main_pl - (-750 + pl)) < 1e-6, "lifetime P/L = imported + the log")
check(same_stats(s.stats, rescan(hist)), "the incrementally-updated lifetime figures equal a full rescan of the table")
hist.close(s)

# reopening does not import a second time, even if the old block reappears in the state file
Path(persist.STATE_PATH).write_text(json.dumps({**LEGACY, "bankroll": s.bankroll}))
s2, hist2 = open_game()
check(s2.stats.hands_lifetime == 1000 + n_hands, "a second launch does not import again (the baseline is only ever taken once)")
check(hist2.conn.execute("select count(*) from imported_stats").fetchone()[0] == rows, "...the baseline rows are unchanged")
hist2.close(s2)

# ------------------------------------------------------------------ the import only takes what the database doesn't already hold
S.reset_data()
s, hist = open_game()
play(s, 25, seed=7)
db_hands = s.stats.hands_lifetime
db_pl = s.stats.lifetime_main_pl
hist.close(s)
bigger = json.loads(json.dumps(LEGACY))
bigger["stats"]["hands_lifetime"] = db_hands + 500            # the old counters kept counting alongside the database
bigger["stats"]["lifetime_main_pl"] = db_pl - 300
Path(persist.STATE_PATH).write_text(json.dumps(bigger))
s, hist = open_game()
check(s.stats.hands_lifetime == db_hands + 500, f"old total {db_hands + 500} vs {db_hands} already logged -> imports only the 500 missing ({s.stats.hands_lifetime})")
check(abs(s.stats.lifetime_main_pl - (db_pl - 300)) < 1e-6, "...and likewise the money")
hist.close(s)

S.reset_data()
s, hist = open_game()
play(s, 25, seed=8)
db_hands = s.stats.hands_lifetime
hist.close(s)
smaller = json.loads(json.dumps(LEGACY))
smaller["stats"]["hands_lifetime"] = 3                        # the old file claims LESS than the database holds
Path(persist.STATE_PATH).write_text(json.dumps(smaller))
s, hist = open_game()
check(s.stats.hands_lifetime == db_hands, f"an older total below what the database already holds imports nothing for it, never a negative ({s.stats.hands_lifetime} vs {db_hands})")
hist.close(s)

# ------------------------------------------------------------------ negative money figures survive the import (regression)
S.reset_data()
neg = json.loads(json.dumps(LEGACY))
neg["stats"].update(lifetime_main_pl=-1234.5, lifetime_sidebet_pl=-80.0, lifetime_power_poker_pl=-705.0, lifetime_star21_pl=-15.0)
Path(persist.STATE_PATH).write_text(json.dumps(neg))
s, hist = open_game()
check((s.stats.lifetime_main_pl, s.stats.lifetime_sidebet_pl, s.stats.lifetime_power_poker_pl, s.stats.lifetime_star21_pl) == (-1234.5, -80.0, -705.0, -15.0),
      f"losing figures import as losses, not as zero: {(s.stats.lifetime_main_pl, s.stats.lifetime_sidebet_pl, s.stats.lifetime_power_poker_pl, s.stats.lifetime_star21_pl)}")
play(s, 20, seed=5)
pp = hist.conn.execute("select sum(power_poker_pl) from hands").fetchone()[0]
check(abs(s.stats.lifetime_power_poker_pl - (-705.0 + pp)) < 1e-6 and same_stats(s.stats, rescan(hist)), "...and new play adds to the negative baseline correctly")
hist.close(s)

# ------------------------------------------------------------------ an import that can't happen leaves the block untouched
S.reset_data()
Path(persist.STATE_PATH).write_text(json.dumps(LEGACY))
bankroll, rules, w, sb = persist.load_state()
dead = history.HistoryDB.open(Path(HOME) / "nope-file" / "x.db") if (Path(HOME) / "nope-file").write_text("x") else None
check(dead.import_pending_legacy_stats() is False and persist.pending_legacy_stats() is not None, "with no usable database the import reports False and keeps the block for later")
persist.save_state(bankroll, rules, w, sb)
check(json.loads(persist.STATE_PATH.read_text()).get("stats", {}).get("hands_lifetime") == 1000, "...and the state file keeps the old stats safe meanwhile")
s, hist = open_game()
check(s.stats.hands_lifetime == 1000, "the next launch with a working database imports them")
hist.close(s)

# ------------------------------------------------------------------ a state file with an empty stats block imports nothing
S.reset_data()
Path(persist.STATE_PATH).write_text(json.dumps({**LEGACY, "stats": {"hands_lifetime": 0, "player_wins": 0}}))
persist.load_state()
check(persist.pending_legacy_stats() is None, "an all-zero stats block is not treated as history")

# ------------------------------------------------------------------ session vs lifetime, newsession, and a fresh slate
S.reset_data()
Path(persist.STATE_PATH).write_text(json.dumps(LEGACY))
s, hist = open_game()
play(s, 30, seed=13)
first_session_hands = s.stats.hands_this_session
check(first_session_hands > 0 and s.stats.hands_lifetime == 1000 + first_session_hands, "session hands count only this session; lifetime adds them to the baseline")
lifetime_before = s.stats.hands_lifetime
s.reset_session()
check(s.stats.hands_this_session == 0 and s.stats.shoes_played == 1 and s.stats.hands_lifetime == lifetime_before,
      "newsession: the session panel starts over, lifetime is untouched")
check(s.stats.sessions_played == 12 + 2, f"...and sessions played went up by one ({s.stats.sessions_played})")
play(s, 10, seed=14)
check(s.stats.hands_lifetime == lifetime_before + s.stats.hands_this_session, "play after a newsession accumulates into lifetime again")
old = hist.conn.execute("select hands_played from sessions order by session_id limit 1").fetchone()[0]
check(old == first_session_hands, f"the first session's own row kept its {old} hands")
check(same_stats(s.stats, rescan(hist)), "cached lifetime still equals a full rescan after a newsession")

bank = s.bankroll
commands.handle_command("bank reset", s)
check(s.pending_confirmation == "bank_reset" and s.bankroll == bank, "'bank reset' asks for confirmation first")
s.pending_confirmation = None
s.reset_bankroll()
check(s.bankroll == s.rules.default_bankroll and s.stats.hands_lifetime == lifetime_before + s.stats.hands_this_session, "resetting the bankroll changes the bankroll and nothing else")
msg = commands.handle_command("hardreset", s)
check(msg.startswith("Unknown command: 'hardreset'"), f"'hardreset' no longer exists: {msg}")
check(not any("hardreset" in line for line in commands.HELP_LINES), "...and is out of the help text")
hist.close(s)

# a new database file is the way to start from a clean slate: nothing carries over
fresh_path = Path(HOME) / "fresh-slate.db"
hist_new = history.HistoryDB.open(fresh_path)
bankroll, rules, w, sb = persist.load_state()
persist.set_legacy_stats(None)
s_new = engine.GameSession(bankroll, rules, w, sb, history=hist_new)
s_new.ensure_shoe_ready()
check(s_new.stats.hands_lifetime == 0 and s_new.stats.lifetime_main_pl == 0 and s_new.stats.sessions_played == 1, "a brand-new database file shows lifetime zero, while the old database is untouched")
check(hist.path != hist_new.path and history.HistoryDB.open().conn.execute("select count(*) from hands").fetchone()[0] > 0, "...the original file still holds all its hands")
hist_new.close(s_new)

# ------------------------------------------------------------------ what counts: abandoned rounds, side bets
S.reset_data()
s, hist = open_game()
s.rules.dealer_buster.enabled = True
s.rules.dealer_buster.max_bet = 100
rng = random.Random(17)
s.wagers[0] = 10
s.side_bet_wagers[0]["dealer_buster"] = 5
r, _ = S.play_round(s, rng, "basic")
hist.record_round(s, r)
s.ensure_shoe_ready()
s.wagers[0] = 20                                        # an unfinished round, cut off by quitting
r2, err = engine.try_start_round(s)
assert r2, err
bank_mid = s.bankroll
hist.record_round(s, r2)
row = hist.conn.execute("select outcome, main_pl from hands order by hand_id desc limit 1").fetchone()
if row["outcome"] == "abandoned":
    st = hist.load_stats()
    check(st.hands_lifetime == hist.conn.execute("select count(*) from hands where outcome <> 'abandoned'").fetchone()[0],
          "an abandoned (cut-off) hand is not counted as a played hand...")
    check(abs(st.lifetime_main_pl - hist.conn.execute("select sum(main_pl) from hands").fetchone()[0]) < 1e-9 and row["main_pl"] < 0,
          "...but its forfeited wager is in the money figures, because that money really left the bankroll")
else:
    check(True, "(round 2 resolved on the deal -- abandoned-hand accounting exercised by check_audit instead)")
hist.close(s)

check.finish("check_stats_and_import")
