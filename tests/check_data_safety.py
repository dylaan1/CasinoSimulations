"""Export / backup / restore / crash recovery / corrupt files / atomic writes / an unavailable database."""
import csv
import json
import os
import random
import shutil
import sqlite3
from pathlib import Path

from _support import *  # noqa: F401,F403
import _support as S

check = S.Checker()
S.reset_data()


def new_session(hist=None):
    bankroll, rules, wagers, sbw = persist.load_state()
    hist = hist or history.HistoryDB.open()
    s = engine.GameSession(bankroll, rules, wagers, sbw, history=hist)
    s.ensure_shoe_ready()
    return s, hist


def play(s, n, seed=0):
    rng = random.Random(seed)
    for _ in range(n):
        s.wagers[0] = 10
        r, err = S.play_round(s, rng)
        assert r, err
        s.history.record_round(s, r)
        s.ensure_shoe_ready()
        persist.save_state(s.bankroll, s.rules, s.wagers, s.side_bet_wagers)


cmd = lambda s, text, in_round=False: commands.handle_command(text, s, in_round)
n_rows = lambda hist, table="hands": hist.conn.execute(f"select count(*) from {table}").fetchone()[0]

# ------------------------------------------------------------------ fresh install
check(not history.DATA_DIR.exists(), "a fresh HOME has no ~/.cs-blackjack yet")
s, hist = new_session()
check(history.DB_PATH.exists(), "database created on first launch")
check(n_rows(hist, "sessions") == 1 and n_rows(hist, "shoes") == 1, "one session + one shoe row at launch")
play(s, 30)
check(n_rows(hist) >= 30, f"30 rounds logged ({n_rows(hist)} hand rows)")

# ------------------------------------------------------------------ export
msg = cmd(s, "export")
check(msg.startswith("Exported hands, sessions, shoes (csv) to ~/.cs-blackjack/exports"), f"export message: {msg}")
files = sorted(history.EXPORT_DIR.glob("*.csv"))
check([f.name.split("-")[0] for f in files] == ["hands", "sessions", "shoes"], f"3 csv files: {[f.name for f in files]}")
hands_csv = list(csv.DictReader(open(next(f for f in files if f.name.startswith("hands")), encoding="utf8")))
check(len(hands_csv) == n_rows(hist), "hands.csv row count matches the table")
shoes_csv = list(csv.DictReader(open(next(f for f in files if f.name.startswith("shoes")), encoding="utf8")))
live = shoes_csv[-1]
check("|" not in live["card_order"] and len(live["card_order"]) == 2 * int(live["cards_dealt"]) and any(g in live["card_order"] for g in "♠♥♦♣"),
      "shoes.csv: a shoe still in play holds only its dealt cards (no '|'), suit glyphs intact")
check(cmd(s, "export json shoes").startswith("Exported shoes (json)"), "export json shoes (arguments in either order)")
j = json.load(open(next(history.EXPORT_DIR.glob("shoes-*.json")), encoding="utf8"))
check(isinstance(j, list) and j[0]["shoe_id"] == 1 and "card_order" in j[0], "shoes json is a list of row objects")
check(cmd(s, "export stats").startswith("Exported stats (csv)"), "export stats csv")
check(cmd(s, "export stats json").startswith("Exported stats (json)"), "export stats json")
sj = json.load(open(next(history.EXPORT_DIR.glob("stats-*.json")), encoding="utf8"))
check(sj["hands_lifetime"] == s.stats.hands_lifetime and sj["bankroll"] == s.bankroll, "stats json has the lifetime counters + bankroll")
check(cmd(s, "export bogus").startswith("Usage: export"), "bad export argument -> usage")
check(cmd(s, "export hands xml").startswith("Usage: export"), "bad export format -> usage")
msg = cmd(s, "export mysql")
sqlfile = next(history.EXPORT_DIR.glob("mysql-*.sql"))
sql = sqlfile.read_text(encoding="utf8")
check(msg.startswith("Exported the database for MySQL to ~/.cs-blackjack/exports/mysql-") and "CREATE TABLE `hands`" in sql and "`reshuffled_mid_round` INT NOT NULL DEFAULT 0" in sql,
      f"export mysql writes a script that includes every table and the newest column: {msg}")
check("INSERT INTO `hands`" in sql and "CREATE VIEW" in sql and "FOREIGN KEY" in sql, "...with rows, views, and foreign keys")

# ------------------------------------------------------------------ backup
check(cmd(s, "backup", in_round=True) == "Finish the current round before making a backup.", "backup refused mid-round")
msg = cmd(s, "backup")
check(msg.startswith("Backup '") and "saved to ~/.cs-blackjack/backups/" in msg, f"backup message: {msg}")
b1 = hist.list_backups()[0]["name"]
check(hist.list_backups()[0]["has_state"], "backup includes the saved state")
bdb = sqlite3.connect(history.BACKUP_DIR / b1 / "blackjack.db")
rows_at_backup = bdb.execute("select count(*) from hands").fetchone()[0]
bdb.close()
check(rows_at_backup == n_rows(hist), "backup DB has the same hand rows as live at that moment")
bankroll_at_backup, hands_life_at_backup = s.bankroll, s.stats.hands_lifetime

# ------------------------------------------------------------------ restore
play(s, 25, seed=5)
check(n_rows(hist) > rows_at_backup, "played on after the backup")
check(cmd(s, "restore nosuch").startswith("No backup named"), "restore of an unknown name is rejected")
check(cmd(s, "restore").startswith("Usage: restore"), "restore with no name -> usage")
msg = cmd(s, "restore " + b1[:8])
check(s.pending_restore == b1 and "confirm" in msg, "restore <prefix> resolves the full name and asks to confirm")
err = s.restore_backup(s.pending_restore)
check(err is None, f"restore succeeded ({err})")
hist = s.history
check(n_rows(hist) == rows_at_backup, f"restored DB is back to the backup's {rows_at_backup} hand rows")
check(s.bankroll == bankroll_at_backup and s.stats.hands_lifetime == hands_life_at_backup, "bankroll restored, and the stats (read from the database) match")
check(json.loads(persist.STATE_PATH.read_text())["bankroll"] == bankroll_at_backup, "the state file on disk was restored too")
names = [b["name"] for b in hist.list_backups()]
check(any(n.endswith("pre-restore") for n in names), f"a pre-restore safety backup was taken: {names}")
check(hist.conn.execute("select count(*) from sessions where ended_at is null").fetchone()[0] == 1 and hist.session_id is not None, "exactly one open session after restore (the new one)")
check(hist.conn.execute("select cut_reason from shoes where shoe_id=?", (hist.shoe_id,)).fetchone()[0] == "restore", "the new shoe is logged with reason 'restore'")
check(hist.conn.execute("select count(*) from sessions where end_reason='abandoned'").fetchone()[0] >= 1, "the session open when the backup was taken shows as abandoned")
play(s, 5, seed=9)
check(hist.conn.execute("select count(*) from hands where session_id=?", (hist.session_id,)).fetchone()[0] >= 5, "logging continues after a restore")

pre = [n for n in names if n.endswith("pre-restore")][0]
err = s.restore_backup(pre)
check(err is None and n_rows(s.history) > rows_at_backup, f"restoring the safety backup brings the 'lost' rounds back ({err})")
hist = s.history

# ------------------------------------------------------------------ bad backups touch nothing
before = n_rows(hist)
bad = history.BACKUP_DIR / "20200101-000000-broken"
bad.mkdir()
(bad / "blackjack.db").write_bytes(b"this is not a database" * 50)
(bad / "state.json").write_text(persist.STATE_PATH.read_text())
err = s.restore_backup("20200101-000000-broken")
check(err is not None and n_rows(s.history) == before, f"a corrupt backup database is rejected, live data untouched: {err}")
nostate = history.BACKUP_DIR / "20200102-000000-nostate"
nostate.mkdir()
shutil.copy(history.DB_PATH, nostate / "blackjack.db")
err = s.restore_backup("20200102-000000-nostate")
check(err is not None and "no saved game state" in err, f"a backup without state is rejected: {err}")
badstate = history.BACKUP_DIR / "20200103-000000-badstate"
badstate.mkdir()
shutil.copy(history.DB_PATH, badstate / "blackjack.db")
(badstate / "state.json").write_text("{not json")
err = s.restore_backup("20200103-000000-badstate")
check(err is not None and "unreadable saved state" in err, f"a backup with a corrupt state file is rejected: {err}")
other = sqlite3.connect(bad / "other.db")
other.execute("create table t (x)")
other.commit()
other.close()
foreign = history.BACKUP_DIR / "20200104-000000-foreign"
foreign.mkdir()
shutil.copy(bad / "other.db", foreign / "blackjack.db")
(foreign / "state.json").write_text(persist.STATE_PATH.read_text())
err = s.restore_backup("20200104-000000-foreign")
check(err is not None and "isn't a cs-blackjack history database" in err, f"some other SQLite file is rejected: {err}")
check(s.history.session_id is not None and n_rows(s.history) == before, "the session is still live and the data intact after every rejected restore")
play(s, 3, seed=11)

# ------------------------------------------------------------------ crash recovery: a session left open
open_before = s.history.conn.execute("select session_id from sessions where ended_at is null").fetchall()
check(len(open_before) == 1, "one session is open while 'running'")
sid = open_before[0][0]
last_hand = s.history.conn.execute("select max(played_at) from hands where session_id=?", (sid,)).fetchone()[0]
s.history.conn.close()                          # a kill -9: no close(), no end_session
s2, hist2 = new_session()
row = hist2.conn.execute("select ended_at, end_reason from sessions where session_id=?", (sid,)).fetchone()
check(row["end_reason"] == "abandoned" and row["ended_at"] == last_hand, f"the stale session is closed as abandoned at its last hand: {tuple(row)}")
check(hist2.conn.execute("select count(*) from shoes where retired_at is null").fetchone()[0] == 1, "the stale session's shoe was retired; only the live shoe is open")
check(hist2.conn.execute("select count(*) from sessions where ended_at is null").fetchone()[0] == 1, "only the new session is open")
s2.history.close(s2)

# ------------------------------------------------------------------ a corrupt state file is quarantined, never overwritten
persist.STATE_PATH.write_text('{"bankroll": 123, "rules": ')
bankroll, rules, w, sb = persist.load_state()
warn = persist.take_load_warning()
check(bankroll == persist.DEFAULT_BANKROLL and warn and "set aside" in warn, f"corrupt state -> defaults + a warning: {warn}")
aside = list(Path(HOME).glob(".cs-blackjack_state.json.corrupt-*"))
check(len(aside) == 1 and aside[0].read_text() == '{"bankroll": 123, "rules": ', "the corrupt file is preserved byte for byte")
check(not persist.STATE_PATH.exists(), "...and is no longer at the live path (so it can't be silently overwritten)")
check(persist.take_load_warning() is None, "the warning is one-shot")
persist.STATE_PATH.write_text("[1, 2, 3]")                 # valid JSON, wrong shape
persist.load_state()
check(persist.take_load_warning() is not None, "a valid-JSON-but-wrong-shape file is also quarantined")

# ------------------------------------------------------------------ an older state file still loads; its stats block waits for the import
legacy = {"bankroll": 777.5, "rules": {}, "stats": {"hands_lifetime": 12, "royal_flushes": 3}, "wagers": [25, 0, 0]}
persist.STATE_PATH.write_text(json.dumps(legacy))
bankroll, rules, w, sb = persist.load_state()
check(bankroll == 777.5 and w[0] == 25, "an older state file loads")
check(persist.pending_legacy_stats() == {"hands_lifetime": 12, "royal_flushes": 3}, "...and its stats block waits to be imported")
persist.save_state(bankroll, rules, w, sb)
saved = json.loads(persist.STATE_PATH.read_text())
check(saved["schema_version"] == persist.STATE_SCHEMA_VERSION == 3, "a save writes schema_version 3")
check(saved["stats"] == {"hands_lifetime": 12, "royal_flushes": 3}, "...and carries the not-yet-imported stats through untouched")
persist.clear_legacy_stats()
persist.save_state(bankroll, rules, w, sb)
check("stats" not in json.loads(persist.STATE_PATH.read_text()), "once imported (cleared), the state file carries no stats")

good = persist.STATE_PATH.read_text()
real_replace = os.replace


def boom(*a, **k):
    raise OSError("disk full")


os.replace = boom
try:
    ok = persist.save_state(1.0, rules, w, sb)
finally:
    os.replace = real_replace
check(ok is False and persist.STATE_PATH.read_text() == good, "a failed save returns False and leaves the previous state intact")
check(not persist.STATE_PATH.with_name(persist.STATE_PATH.name + ".tmp").exists(), "...and cleans up its temp file")

# ------------------------------------------------------------------ a database newer than this game
newer = Path(HOME) / "newer.db"
c = sqlite3.connect(newer)
c.execute("pragma user_version = 99")
c.commit()
c.close()
h = history.HistoryDB.open(newer)
check(h.conn is None and "schema v99" in h.error, f"a newer-schema database is refused, not clobbered: {h.error}")

# ------------------------------------------------------------------ an unavailable database: the game must carry on
blocker = Path(HOME) / "iamafile"
blocker.write_text("x")
dead = history.HistoryDB.open(blocker / "sub" / "x.db")      # the parent 'directory' is a file
check(dead.conn is None and dead.error, f"an unopenable path records an error and raises nothing: {dead.error}")
bankroll, rules, w, sb = persist.load_state()
s3 = engine.GameSession(bankroll, rules, w, sb, history=dead)
s3.ensure_shoe_ready()
s3.wagers[0] = 10
r, err = S.play_round(s3, random.Random(3))
dead.record_round(s3, r)
s3.reset_session()
s3.reset_shoe()
dead.close(s3)
check(r is not None and s3.stats.hands_lifetime == 0, "a full game flow works with a dead history database; stats just read zero")
check(cmd(s3, "backup").startswith("History database is unavailable"), "backup says so plainly")
check(cmd(s3, "export").startswith("History database is unavailable"), "export says so plainly")
check(cmd(s3, "restore x").startswith("History database is unavailable"), "restore says so plainly")
check(cmd(s3, "export mysql").startswith("History database is unavailable"), "export mysql says so plainly")

# ------------------------------------------------------------------ resets keep the log
S.reset_data()
s4, h4 = new_session()
play(s4, 10, seed=21)
sessions_before = n_rows(h4, "sessions")
hands_before = s4.stats.hands_lifetime
s4.reset_session()
s4.reset_session()
check(n_rows(h4, "sessions") == sessions_before + 2, "each newsession opens a new session row")
check(n_rows(h4) >= 10, "newsession does not wipe the hand log")
check(s4.stats.hands_lifetime == hands_before and s4.stats.hands_this_session == 0 and s4.stats.shoes_played == 1,
      "after newsession: lifetime unchanged (it comes from the database), the session panel starts over")
check(h4.conn.execute("select count(*) from sessions where end_reason='newsession'").fetchone()[0] >= 2, "end reasons recorded")
check(h4.conn.execute("select count(*) from shoes where session_id is null").fetchone()[0] == 0, "every shoe belongs to a session")
h4.close(s4)

# ------------------------------------------------------------------ overview() feeds the stats screen
S.reset_data()
s5, h5 = new_session()
play(s5, 40, seed=31)
ov = h5.overview()
check(ov["session"] is not None and ov["counts"]["hands"] == n_rows(h5) and len(ov["hand_types"]) == 6, "overview() has the session, the counts, and 6 hand-type rows")
check(ov["all_time"]["peak_bankroll"] >= ov["session"]["peak_bankroll"] - 1e-9, "all-time peak >= this session's peak")
h5.close(s5)

check.finish("check_data_safety")
