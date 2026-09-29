"""Another program holds the history database locked (a MySQL/SQLite browser with a write open, a backup tool...):
the game must carry on, keep every round it plays in order, and write them all once the lock is released."""
import random
import sqlite3
import time

from _support import *  # noqa: F401,F403
import _support as S

check = S.Checker()
S.reset_data()


def new_session(decks=6):
    bankroll, rules, wagers, sbw = persist.load_state()
    rules.num_decks = decks
    hist = history.HistoryDB.open()
    s = engine.GameSession(bankroll, rules, wagers, sbw, history=hist)
    s.ensure_shoe_ready()
    hist.conn.execute("PRAGMA busy_timeout = 60")     # don't wait the full two seconds on every blocked write
    return s, hist


def play(s, n, rng):
    out = []
    for _ in range(n):
        s.wagers[0] = 10
        r, err = S.play_round(s, rng, "basic")
        assert r, err
        s.history.record_round(s, r)
        s.ensure_shoe_ready()
        out.append(r)
    return out


def lock():
    """A second connection that takes the database's write lock and sits on it."""
    other = sqlite3.connect(history.DB_PATH, timeout=0.1, isolation_level=None)
    other.execute("BEGIN EXCLUSIVE")
    return other


def rows(hist, sql="select * from hands order by hand_id"):
    c = sqlite3.connect(history.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


rng = random.Random(41)
s, hist = new_session()
played = play(s, 5, rng)
check(hist.pending_rounds == 0 and hist.error is None, "before the lock: everything written as it goes")

# ------------------------------------------------------------------ a lock across several rounds
other = lock()
bank_at_lock = s.bankroll
blocked = play(s, 6, rng)
check(hist.pending_rounds == 6, f"6 rounds played under the lock are all queued, none dropped ({hist.pending_rounds})")
check(hist.error is not None and "locked" in hist.error, f"the problem is recorded, not raised: {hist.error}")
queued_pl = sum(row["total_pl"] for group in hist._pending_rounds for row in group)
check(abs(s.bankroll - (bank_at_lock + queued_pl)) < 1e-6, "the game itself carried on: the bankroll moved by exactly what the queued rounds won and lost")
other.rollback()
other.close()
play(s, 1, rng)
check(hist.pending_rounds == 0 and hist.error is None, "lock released -> the next write drains the queue and clears the error")
hs = rows(hist)
by_round = {}
for h in hs:
    by_round.setdefault(h["round_id"], []).append(h)
check(len(by_round) == 5 + 6 + 1, f"all {len(by_round)} rounds are in the log (5 before, 6 that were queued, 1 after)")
ids = sorted(by_round)
check(ids == list(range(1, len(ids) + 1)), "...with consecutive round ids, in the order they were played")
chain_ok = True
prev_after = None
for rid in ids:
    grp = sorted(by_round[rid], key=lambda h: (h["spot_number"], h["hand_number"]))
    if prev_after is not None:
        chain_ok = chain_ok and abs(grp[0]["bankroll_before"] - prev_after) < 1e-6
    prev_after = grp[-1]["bankroll_after"] if len(grp) else prev_after
    chain_ok = chain_ok and abs((grp[-1]["bankroll_after"] - grp[0]["bankroll_before"]) - sum(h["total_pl"] for h in grp)) < 1e-6
check(chain_ok, "the bankroll chains from round to round with no gaps, and each round's P/L adds up (queued rounds kept their own snapshot)")
sess = rows(hist, "select * from sessions")[0]
check(sess["rounds_played"] == 12 and sess["hands_played"] == len([h for h in hs if h["outcome"] != "abandoned"]), "the session row was brought fully up to date by the drain")
check(abs(sess["ending_bankroll"] - s.bankroll) < 1e-6, "...including the ending bankroll")
hist._life_cache = None
check(abs(hist.load_stats().lifetime_main_pl - sum(h["main_pl"] for h in hs)) < 1e-6 and hist.load_stats().hands_lifetime == sess["hands_played"], "lifetime stats include the drained rounds")
shoe = rows(hist, "select * from shoes where shoe_id=?".replace("?", str(hist.shoe_id)))[0]
check(shoe["cards_dealt"] == s.shoe.cards_dealt and len(shoe["card_order"]) == 2 * s.shoe.cards_dealt, "the shoe row's dealt cards caught up too")

# ------------------------------------------------------------------ locked for a while, released just before quitting
other = lock()
play(s, 3, rng)
check(hist.pending_rounds == 3, "3 more rounds queued behind a new lock")
other.rollback()
other.close()
hist.close(s)
hs2 = rows(hist)
check(len({h["round_id"] for h in hs2}) == 15, f"closing after the lock is gone writes the queue first: 15 rounds in the log ({len({h['round_id'] for h in hs2})})")
last = rows(hist, "select * from shoes order by shoe_id desc limit 1")[0]
check(last["retired_at"] is not None and "|" in last["card_order"], "...and retires the shoe with its '|' marker")
check(rows(hist, "select end_reason from sessions")[0]["end_reason"] == "quit", "...and closes the session cleanly")

# ------------------------------------------------------------------ still locked when the game quits: nothing hangs or raises
S.reset_data()
s, hist = new_session()
play(s, 4, random.Random(5))
other = lock()
play(s, 2, random.Random(6))
t0 = time.time()
hist.close(s)
took = time.time() - t0
check(took < 5, f"quitting while the database is still locked returns promptly ({took:.1f}s), no exception")
other.rollback()
other.close()
check(len({h["round_id"] for h in rows(hist)}) == 4, "the 4 rounds already written are safe (the 2 unwritten ones are the documented limit of a lock that never lifts)")
h2 = history.HistoryDB.open()
check(h2.error is None and h2.conn.execute("pragma integrity_check").fetchone()[0] == "ok", "the database is intact and opens fine next launch")
check(h2.conn.execute("select end_reason from sessions").fetchone()[0] == "abandoned", "...and the interrupted session shows up as abandoned")
h2.conn.close()

# ------------------------------------------------------------------ a shoe cut while the database is locked
S.reset_data()
S.install_shoe_tracking()
s, hist = new_session()
play(s, 3, random.Random(9))
first_shoe = hist.shoe_id
other = lock()
s.reset_shoe("newshoe")                       # cut a shoe while the write lock is held elsewhere
play(s, 3, random.Random(10))
other.rollback()
other.close()
play(s, 2, random.Random(11))
hist.close(s)
shoes = rows(hist, "select * from shoes order by shoe_id")
ok = True
for sh in shoes:
    dealt, _, undealt = sh["card_order"].partition("|")
    toks = [dealt[i:i + 2] for i in range(0, len(dealt), 2)]
    ok = ok and sh["card_order"].count("|") == 1 and len(toks) == sh["cards_dealt"]
check(ok, f"every shoe row is well-formed dealt|undealt after a cut under lock ({len(shoes)} rows)")
check(len(shoes) >= 2 and shoes[0]["retired_at"] is not None, "the shoe that was in play at the cut is closed, not left open")
first = shoes[0]
check(first["cards_dealt"] == len(S.LOGICAL[0]["drawn"]) and first["card_order"].startswith("".join(S.LOGICAL[0]["drawn"])),
      "its dealt cards are the cards it really dealt -- the new shoe's cards did not leak into it")
hands_by_shoe = {r[0]: r[1] for r in rows(hist, "select shoe_id, count(*) from hands group by shoe_id")}
check(sum(hands_by_shoe.values()) == len(rows(hist)), f"every hand row points at a shoe that exists ({hands_by_shoe})")


# ------------------------------------------------------------------ a mid-round reshuffle (two shoe changes at once) under the lock
def well_formed(shoes_rows, logical):
    """Every shoe row is exactly one logical shoe: the cards it dealt, then '|', then the ones it didn't."""
    if len(shoes_rows) != len(logical):
        return False
    for row, entry in zip(shoes_rows, logical):
        dealt, bar, tail = row["card_order"].partition("|")
        if not bar or dealt != "".join(entry["drawn"]) or dealt + tail != "".join(entry["initial"]) or row["cards_dealt"] != len(entry["drawn"]):
            return False
    return True


S.reset_data()
S.LOGICAL.clear()
s, hist = new_session(decks=1)
rng = random.Random(77)
play(s, 2, rng)
other = lock()
flagged = None
for _ in range(200):
    S.burn_to(s, 6)                                   # so a round can run the shoe dry
    r, _ = S.play_round(s, rng, "greedy")
    hist.record_round(s, r)
    if r.reshuffled_mid_round:
        flagged = r
        break
    s.ensure_shoe_ready()                             # (a normal cut, also under the lock)
check(flagged is not None and hist.pending_rounds > 0 and hist.error and "locked" in hist.error, "a mid-round reshuffle happened while the database was locked; everything is queued")
other.rollback()
other.close()
play(s, 2, rng)
check(hist.pending_rounds == 0 and hist.error is None and hist.shoe_id > 0, "released: the queue drained and the live shoe has a real id")
hist.close(s)
shoes = rows(hist, "select * from shoes order by shoe_id")
check(well_formed(shoes, S.LOGICAL), f"every logical shoe (incl. the mid-round one) has its own row with exactly its own cards ({len(shoes)} rows)")
mid = [x for x in shoes if x["cut_reason"] == "mid_round"]
fl = rows(hist, "select * from hands where reshuffled_mid_round = 1")
check(len(mid) == 1 and fl and all(h["shoe_id"] == mid[0]["shoe_id"] - 1 for h in fl), "the flagged round points at the shoe it started on, and the mid_round shoe follows it")
check(all(x["retired_at"] for x in shoes) and len({x["shoe_id"] for x in shoes}) == len(shoes) and min(x["shoe_id"] for x in shoes) > 0, "no shoe left open; ids are real and unique")
allrows = rows(hist)
check(len({h["shoe_id"] for h in allrows} - {x["shoe_id"] for x in shoes}) == 0, "every hand refers to a real shoe row")

# ------------------------------------------------------------------ several shoe cuts in a row under one lock
S.reset_data()
S.LOGICAL.clear()
s, hist = new_session(decks=2)
rng = random.Random(78)
play(s, 2, rng)
other = lock()
for _ in range(4):
    s.reset_shoe("newshoe")
    play(s, 2, rng)
other.rollback()
other.close()
play(s, 1, rng)
hist.close(s)
shoes = rows(hist, "select * from shoes order by shoe_id")
check(well_formed(shoes, S.LOGICAL) and len(shoes) == 5, f"4 cuts under one lock -> 5 shoe rows (the first + 4 new), each with exactly its own cards ({len(shoes)})")
by_shoe = {r[0]: r[1] for r in rows(hist, "select shoe_id, count(*) from hands group by shoe_id")}
check(sum(by_shoe.values()) == len(rows(hist)) and 2 <= len(by_shoe), f"the rounds played on each shoe are attributed to it: hands per shoe {by_shoe}")
per_round_shoe = rows(hist, "select round_id, count(distinct shoe_id) n from hands group by round_id")
check(all(r["n"] == 1 for r in per_round_shoe), "no round straddles two shoe ids")

# ------------------------------------------------------------------ 'newsession' while locked carries on in the current session
S.reset_data()
S.LOGICAL.clear()
s, hist = new_session()
play(s, 3, random.Random(3))
other = lock()
s.reset_session()
play(s, 2, random.Random(4))
other.rollback()
other.close()
play(s, 1, random.Random(5))
check(len(rows(hist, "select * from sessions")) == 1, "a newsession that couldn't be written is not half-applied: still one session row, nothing orphaned")
check(len({h["session_id"] for h in rows(hist)}) == 1 and len({h["round_id"] for h in rows(hist)}) == 6, "all 6 rounds are in it")
s.reset_session()
play(s, 1, random.Random(6))
check(len(rows(hist, "select * from sessions")) == 2 and rows(hist, "select count(*) c from hands where session_id=2")[0]["c"] >= 1, "once the lock is gone, newsession works normally")
hist.close(s)
check(well_formed(rows(hist, "select * from shoes order by shoe_id"), S.LOGICAL), "and every shoe row across all of that is exact")

# ------------------------------------------------------------------ restoring while the database is locked changes nothing
S.reset_data()
s, hist = new_session()
play(s, 4, random.Random(8))
bname = hist.backup(s, "before")
play(s, 3, random.Random(9))
n = len(rows(hist))
other = lock()
err = s.restore_backup(bname)
other.rollback()
other.close()
check(err is not None and "busy" in err, f"restore under a lock is refused politely: {err}")
check(len(rows(hist)) == n and hist.session_id is not None, "...nothing was changed, and the session is still live")
play(s, 1, random.Random(10))
check(len({h["round_id"] for h in rows(hist)}) == 8, "logging continues normally afterwards")
hist.close(s)

check.finish("check_locked_db")
