"""How the history log records a shoe that runs dry mid-round, plus the schema upgrades that got us here."""
import random
import sqlite3
from pathlib import Path

from _support import *  # noqa: F401,F403
import _support as S

check = S.Checker()
S.reset_data()


def new_session(decks=1, hands=1):
    bankroll, rules, wagers, sbw = persist.load_state()
    rules.num_decks, rules.num_hands, rules.surrender = decks, hands, "off"
    hist = history.HistoryDB.open()
    s = engine.GameSession(bankroll, rules, wagers, sbw, history=hist)
    s.wagers[:] = [10, 10, 10]
    return s, hist


def until_reshuffle(s, rng, keep, policy="greedy", tries=200):
    """Burn the shoe down to `keep` cards and play until a round hits the failsafe."""
    for _ in range(tries):
        S.burn_to(s, keep)
        r, _ = S.play_round(s, rng, policy)
        if r.reshuffled_mid_round:
            return r
        s.history.record_round(s, r)
        s.ensure_shoe_ready()
    raise AssertionError("never hit the failsafe")


S.install_shoe_tracking()
rng = random.Random(11)
s, hist = new_session()
c = hist.conn
r = until_reshuffle(s, rng, keep=6)

# before the round is recorded, the exhausted shoe is already closed off
old_id = r.history_shoe_id
old = c.execute("select * from shoes where shoe_id=?", (old_id,)).fetchone()
check(r.reshuffled_mid_round and old is not None and old["retired_at"] is not None, "the exhausted shoe was retired the moment it ran dry")
dealt_s, _, tail = old["card_order"].partition("|")
check(len(dealt_s) == 2 * 52 and tail == "" and old["card_order"].endswith("|") and old["cards_dealt"] == 52,
      "...its card_order is all 52 cards dealt, then '|' and NOTHING never-dealt")
check(tally([card(dealt_s[i:i + 2]) for i in range(0, len(dealt_s), 2)]) == tally(FULL), "...and those 52 are exactly the deck")
new = c.execute("select * from shoes order by shoe_id desc limit 1").fetchone()
check(new["shoe_id"] == old_id + 1 and new["cut_reason"] == "mid_round" and new["retired_at"] is None, f"a new shoe row was opened right away, cut_reason 'mid_round' (id {new['shoe_id']})")
check(new["session_id"] == old["session_id"] and new["num_decks"] == 1, "...in the same session")

hist.record_round(s, r)
rows = c.execute("select * from hands where round_id=(select max(round_id) from hands)").fetchall()
check(len(rows) >= 1 and all(x["reshuffled_mid_round"] == 1 for x in rows), f"every hand of the round is flagged reshuffled_mid_round = 1 ({len(rows)} hand(s))")
check(all(x["shoe_id"] == old_id for x in rows), "...and points at the shoe the round STARTED on")
check(all(x["running_count_before"] == r.running_count_before and x["cards_dealt_before"] == r.cards_dealt_before for x in rows),
      "...with the *_before count/depth figures of that starting shoe (not the new one)")
bad = 0
for x in rows:
    b = 0 if x["cards_dealt_before"] == 0 else round(x["running_count_before"] / ((52 - x["cards_dealt_before"]) / 52) * 2) / 2
    bad += abs(b - x["true_count_before"]) > 1e-9
check(bad == 0, "...and a true count consistent with the starting shoe")
new = c.execute("select * from shoes where shoe_id=?", (new["shoe_id"],)).fetchone()
check(new["card_order"] == cards.cards_to_string(r.drawn) and "|" not in new["card_order"] and new["cards_dealt"] == len(r.drawn),
      f"the new shoe's dealt part starts with the {len(r.drawn)} cards that were on the table, in draw order (no '|': still in play)")
b, a, pl = c.execute("select min(bankroll_before), max(bankroll_after), sum(total_pl) from hands where round_id=(select max(round_id) from hands)").fetchone()
check(abs((a - b) - pl) < 1e-6, "bankroll conservation holds across the reshuffled round")

# the next round is unflagged and belongs to the new shoe
s.ensure_shoe_ready()
shoe_before_next = hist.shoe_id
r2, _ = S.play_round(s, rng, "basic")
hist.record_round(s, r2)
rows2 = c.execute("select * from hands where round_id=(select max(round_id) from hands)").fetchall()
check(not r2.reshuffled_mid_round and all(x["reshuffled_mid_round"] == 0 and x["shoe_id"] == shoe_before_next for x in rows2),
      "the next round is unflagged and belongs to the new shoe")
check(all(x["cards_dealt_before"] >= len(r.drawn) for x in rows2), "...counted from the new shoe's own depth (table cards already dealt)")
check(c.execute("select count(*) from hands where reshuffled_mid_round=1").fetchone()[0] == len(rows), "exactly that round is flagged so far")
check(c.execute("select shoes_played from sessions where session_id=?", (hist.session_id,)).fetchone()[0] >= 2, "the session's shoes_played counts the mid-round shoe too")

# closing writes the tail of the shoe in play; every shoe row is a complete, exact deck
hist.close(s)
c2 = sqlite3.connect(history.DB_PATH)
c2.row_factory = sqlite3.Row
allgood = True
for row in c2.execute("select * from shoes"):
    d, _, u = row["card_order"].partition("|")
    toks = [card((d + u)[i:i + 2]) for i in range(0, len(d + u), 2)]
    allgood = allgood and row["card_order"].count("|") == 1 and tally(toks) == tally(FULL * row["num_decks"]) and row["retired_at"]
check(allgood, "after quit, every shoe row (including the mid-round one) is dealt|never-dealt and accounts for every card exactly once")
c2.close()

# a round CUT OFF by quitting right after a reshuffle keeps its flag and starting shoe
S.reset_data()
s, hist = new_session()
r = until_reshuffle(s, random.Random(21), keep=5)
old_id = r.history_shoe_id
hist.record_round(s, r)          # what the shutdown path does
hist.close(s)
c3 = sqlite3.connect(history.DB_PATH)
c3.row_factory = sqlite3.Row
rows = c3.execute("select * from hands where reshuffled_mid_round=1 order by hand_id desc limit 1").fetchall()
check(rows and rows[0]["shoe_id"] == old_id, "a reshuffled round recorded by the shutdown path keeps its flag and starting shoe")
c3.close()

# =============================================================== schema upgrades
S.reset_data()
v2 = Path(HOME) / "v2.db"
conn = sqlite3.connect(v2)
conn.executescript(history._SCHEMA_V1 + history._SCHEMA_V2 + "\nPRAGMA user_version = 2;")
conn.execute("INSERT INTO sessions (started_at, starting_bankroll, ending_bankroll, peak_bankroll, lowest_bankroll) VALUES ('2026-09-01T00:00:00Z',1,1,1,1)")
conn.execute("""INSERT INTO hands (round_id, session_id, played_at, spot_number, hand_number, initial_bet, final_bet, hand_type, initial_total,
     player_cards, player_total, player_soft, player_bust, player_blackjack, is_split, is_split_aces, doubled, surrendered, even_money,
     dealer_up, dealer_cards, dealer_total, dealer_bust, dealer_blackjack, outcome, payout, main_pl, total_pl, running_count_before,
     true_count_before, cards_dealt_before, bankroll_before, bankroll_after)
     VALUES (1,1,'2026-09-01T00:00:00Z',1,1,10,10,'hard',12,'5♠7♥',12,0,0,0,0,0,0,0,0,'T♦','T♦6♣',16,0,0,'loss',0,-10,-10,0,0,0,100,90)""")
conn.commit()
conn.close()
h = history.HistoryDB.open(v2)
check(h.error is None and h.conn.execute("pragma user_version").fetchone()[0] == history.SCHEMA_VERSION == 3, "a v2 database upgrades to v3 on open")
check("reshuffled_mid_round" in [r[1] for r in h.conn.execute("pragma table_info(hands)")], "the hands table gained reshuffled_mid_round")
check(h.conn.execute("select reshuffled_mid_round from hands").fetchone()[0] == 0, "existing rows read 0 (no reshuffle) -- the truth for everything logged before this feature")
h.conn.close()

v1 = Path(HOME) / "v1.db"
conn = sqlite3.connect(v1)
conn.executescript(history._SCHEMA_V1 + "\nPRAGMA user_version = 1;")
sh = cards.Shoe(2)
full = cards.cards_to_string(sh._initial_order)
conn.execute("INSERT INTO sessions (started_at, starting_bankroll, ending_bankroll, peak_bankroll, lowest_bankroll) VALUES ('2026-09-01T00:00:00Z',1,1,1,1)")
conn.execute("""INSERT INTO shoes (session_id, cut_at, cut_reason, num_decks, penetration, total_cards, cards_dealt, blackjack_payout,
                hit_soft_17, rules_json, card_order) VALUES (1, '2026-09-01T00:00:00Z', 'start', 2, 0.75, 104, 10, 1.5, 0, '{}', ?)""", (full,))
conn.commit()
conn.close()
h = history.HistoryDB.open(v1)
check(h.error is None and h.conn.execute("pragma user_version").fetchone()[0] == 3, "a v1 database upgrades all the way to v3")
mig = h.conn.execute("select card_order from shoes").fetchone()[0]
check(mig == full[:20] + "|" + full[20:], "its card_order gets the '|' put in at cards_dealt (10 cards dealt)")
check(h.conn.execute("select count(*) from imported_stats").fetchone()[0] == 0, "imported_stats exists (empty)")
h.conn.close()
h = history.HistoryDB.open(v1)
check(h.conn.execute("select card_order from shoes").fetchone()[0] == mig, "reopening doesn't touch it again (idempotent)")
h.conn.close()

check.finish("check_history_reshuffle")
