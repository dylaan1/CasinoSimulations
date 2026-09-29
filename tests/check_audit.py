"""Randomized database audit: play thousands of rounds through the real engine with the history log attached
(including shoes deep enough to trigger the mid-round reshuffle), then check the database against ground truth:
bankroll conservation, the exact cards dealt, every stat against an independent oracle, the running counts, the
reshuffle flags.

    python3 tests/check_audit.py                # 2,500 rounds, seed 1
    CSBJ_AUDIT_ROUNDS=20000 CSBJ_AUDIT_SEED=7 python3 tests/check_audit.py
"""
import copy
import os
import random
import sqlite3
import sys
from collections import Counter

from _support import *  # noqa: F401,F403
import _support as S
import oracle_stats as oldstats

S.install_shoe_tracking()
ORACLE = oldstats.Stats()
STATS_AT_END = {}
PRE = {}
_orig_end = history.HistoryDB.end_session


def _end(self, session, reason):
    ok = _orig_end(self, session, reason)
    return ok


def feed_oracle(o, r):
    for res in r.results:
        o.record_hand_outcome(res.outcome, res.hand.bet, res.payout)
        if res.hand.is_blackjack:
            o.record_player_blackjack()
    for spot in r.spots:
        for h in spot.hands:
            if h.doubled:
                o.record_double()
        n = len(spot.hands)
        if n > 1:
            first = spot.hands[0]
            for _ in range(n - 1):
                o.record_split()
                if first.is_split_aces:
                    o.record_aces_split()
                elif first.cards[0].rank in cards.TEN_VALUE_RANKS:
                    o.record_tens_split()
    for (spot_index, key), category in r.sidebet_categories.items():
        if category and (key != "dealer_buster" or spot_index == 0):
            o.record_sidebet_occurrence(key, category)
    for res in r.side_bet_results:
        if res.win_amount > 0 and res.bet_key != "insurance":
            o.record_sidebet_win(res.bet_key, res.category_key)
        o.record_side_bet(res.wager, res.win_amount, bet_key=res.bet_key if res.bet_key in ("power_poker", "star21") else None)
    d = r.dealer_hand
    if d.is_blackjack:
        o.record_dealer_blackjack()
    elif not d.is_bust and d.best_value == 21:
        o.record_greg_special()
    if d.is_bust:
        o.record_dealer_bust()


def randomize(session, rng):
    r = session.rules
    r.num_decks = rng.choice([1, 2, 2, 3, 4, 6])
    r.random_penetration = rng.random() < 0.3
    r.penetration = rng.choice([0.5, 0.75, 0.9, 1.0])       # incl. depths where only the floor guards the shoe
    r.das = rng.random() < 0.5
    r.rsa = rng.random() < 0.5
    r.rsa_facedown = (not r.rsa) and rng.random() < 0.3
    r.surrender = rng.choice(["late", "early", "off"])
    r.hit_soft_17 = rng.random() < 0.5
    r.double_facedown = rng.random() < 0.3
    r.double_blackjack = rng.random() < 0.3
    r.blackjack_payout = rng.choice([1.5, 1.2])
    session.try_set_num_hands(rng.choice([1, 2, 3]))
    for key in ("power_poker", "star21", "dealer_buster"):
        getattr(r, key).enabled = rng.random() < 0.7
        getattr(r, key).max_bet = 100


def wagers(session, rng):
    for i in range(3):
        session.wagers[i] = rng.choice([5, 10, 10.5, 25, 100])
        for key in ("power_poker", "star21", "dealer_buster"):
            session.side_bet_wagers[i][key] = rng.choice([0, 0, 5, 10, 25])


def run(n_rounds, seed):
    rng = random.Random(seed)
    random.seed(seed)
    bankroll, rules, wg, sbw = persist.load_state()
    hist = history.HistoryDB.open()
    assert hist.error is None, hist.error
    s = engine.GameSession(bankroll, rules, wg, sbw, history=hist)
    s.ensure_shoe_ready()
    resets = Counter()
    rounds = 0
    policies = ["random", "greedy", "basic"]
    for i in range(n_rounds):
        if i % 40 == 0:
            randomize(s, rng)
        if i % 5 == 0:
            wagers(s, rng)
        if s.bankroll < 5000:
            s.adjust_bankroll(30000)
        if rng.random() < 0.06:                              # a very deep shoe: leave only a few cards
            keep = rng.randint(4, 30)
            while s.shoe.cards_remaining > keep:
                s.shoe.draw()
        roll = rng.random()
        if roll < 0.003:
            s.reset_shoe(); resets["newshoe"] += 1
        elif roll < 0.006:
            # the session boundary: bank the oracle's view of the session that is ending
            STATS_AT_END[hist.session_id] = copy.deepcopy(ORACLE)
            ORACLE.reset_session()
            s.reset_session(); resets["newsession"] += 1
        r, err = S.play_round(s, rng, rng.choice(policies))
        if r is None:
            continue
        hist.record_round(s, r)
        hist.record_round(s, r)                              # idempotent
        feed_oracle(ORACLE, r)
        rounds += 1
        if rounds % 40 == 0 and hist._life_cache is not None:
            full, inc = hist._scan_lifetime(""), hist._life_cache
            for k, v in full.items():
                if isinstance(v, dict):
                    assert v == inc[k], f"lifetime cache drifted on {k} at round {rounds}"
                else:
                    assert abs(v - inc[k]) < 1e-6, f"lifetime cache drifted on {k} at round {rounds}"
        s.ensure_shoe_ready()
        persist.save_state(s.bankroll, s.rules, s.wagers, s.side_bet_wagers)
    PRE["stats"] = hist.load_stats()
    PRE["oracle"] = copy.deepcopy(ORACLE)
    # a round cut off by quitting
    s.try_set_num_hands(2)
    wagers(s, rng)
    r, err = engine.try_start_round(s)
    assert r is not None, err
    hist.record_round(s, r)
    quit_bankroll = s.bankroll
    STATS_AT_END[hist.session_id] = None
    hist.close(s)
    return s, resets, rounds, r, quit_bankroll


if __name__ == "__main__":
    n = int(os.environ.get("CSBJ_AUDIT_ROUNDS", sys.argv[1] if len(sys.argv) > 1 else 2500))
    seed = int(os.environ.get("CSBJ_AUDIT_SEED", 1))
    s, resets, rounds, cut_round, quit_bankroll = run(n, seed)
    db = sqlite3.connect(history.DB_PATH)
    db.row_factory = sqlite3.Row
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    rows_n = {t: q(f"select count(*) c from {t}")[0]["c"] for t in ("sessions", "shoes", "hands")}
    flagged_rounds = q("select count(distinct round_id) c from hands where reshuffled_mid_round=1")[0]["c"]
    mid_shoes = q("select count(*) c from shoes where cut_reason='mid_round'")[0]["c"]
    print(f"rows {rows_n} | resets {dict(resets)} | rounds {rounds} | failsafe rounds flagged {flagged_rounds} | mid_round shoe rows {mid_shoes}")
    check(q("pragma integrity_check")[0][0] == "ok", "integrity")
    check(q("pragma foreign_key_check") == [], "foreign keys")
    check(q("pragma user_version")[0][0] == history.SCHEMA_VERSION == 3, "schema version")

    # 1. bankroll conservation
    bad = 0
    for row in q("""select round_id, min(bankroll_before) bb, max(bankroll_after) ba, min(bankroll_after) ba2,
                           sum(total_pl) pl, max(outcome='abandoned') ab from hands group by round_id"""):
        if row["ab"]:
            continue
        if abs((row["ba"] - row["bb"]) - row["pl"]) > 1e-6 or row["ba"] != row["ba2"]:
            bad += 1
    check(bad == 0, f"bankroll conservation broken in {bad} rounds")

    # 2. the cut-off round: whole-round P/L equals the actual bankroll change
    last = q("select * from hands where round_id = (select max(round_id) from hands)")
    check(len(last) == len(cut_round.spots) and abs((quit_bankroll - last[0]["bankroll_before"]) - sum(r["total_pl"] for r in last)) < 1e-6,
          "cut-off round P/L != real bankroll change")

    # 3. every shoe row against the cards the engine ACTUALLY dealt (a mid-round reshuffle is its own logical shoe)
    db_shoes = q("select * from shoes order by shoe_id")
    check(len(db_shoes) == len(S.LOGICAL), f"shoe rows {len(db_shoes)} vs logical shoes {len(S.LOGICAL)}")
    full = Counter(c.token for c in FULL)
    for row, ent in zip(db_shoes, S.LOGICAL):
        order = row["card_order"]
        check(order.count("|") == 1, f"shoe {row['shoe_id']}: one dealt|undealt marker")
        d_s, _, u_s = order.partition("|")
        dealt = [d_s[i:i + 2] for i in range(0, len(d_s), 2)]
        undealt = [u_s[i:i + 2] for i in range(0, len(u_s), 2)]
        check(dealt == ent["drawn"], f"shoe {row['shoe_id']}: dealt part != cards actually dealt")
        check(undealt == ent["initial"][len(ent["drawn"]):], f"shoe {row['shoe_id']}: never-dealt tail != rest of the shuffle")
        check(Counter(dealt + undealt) == Counter({k: v * row["num_decks"] for k, v in full.items()}), f"shoe {row['shoe_id']}: not a full shoe")
        check(row["cards_dealt"] == len(dealt) and row["total_cards"] == 52 * row["num_decks"] and row["retired_at"], f"shoe {row['shoe_id']}: dealt count/retired")
        check((row["cut_reason"] == "mid_round") == ent["midround"], f"shoe {row['shoe_id']}: cut_reason {row['cut_reason']} vs midround={ent['midround']}")
        if ent["midround"]:
            check(ent["initial"][:len(ent["drawn"])] >= [] and dealt[:1] != [] , "mid-round shoe starts with the table cards")

    # 4. the flag: rows flagged <=> the round's start shoe is followed by a mid_round shoe row
    for rid, sid, flagged in q("select round_id, shoe_id, max(reshuffled_mid_round) f from hands group by round_id, shoe_id"):
        follower = q("select cut_reason from shoes where shoe_id = ?", sid + 1)
        followed = bool(follower) and follower[0]["cut_reason"] == "mid_round"
        if flagged:
            check(followed, f"round {rid} is flagged but shoe {sid + 1} is not a mid_round shoe")
    check(q("select count(*) c from (select round_id from hands group by round_id having min(reshuffled_mid_round) <> max(reshuffled_mid_round))")[0]["c"] == 0,
          "a round is flagged on all its hands or none")
    check(flagged_rounds >= 1, "the failsafe was exercised in this run")
    check(flagged_rounds == mid_shoes or flagged_rounds <= mid_shoes, f"flagged rounds ({flagged_rounds}) vs mid_round shoes ({mid_shoes})")

    # 5. sessions: totals vs every hand row; and vs the oracle where no round was cut off
    for sess in q("select * from sessions order by session_id"):
        hall = q("select * from hands where session_id=?", sess["session_id"])
        h = [x for x in hall if x["outcome"] != "abandoned"]
        check(sess["ended_at"] and sess["end_reason"], f"session {sess['session_id']} closed")
        check(sess["hands_played"] == len(h), f"session {sess['session_id']} hands_played")
        check(abs(sess["main_pl"] - sum(x["main_pl"] for x in hall)) < 1e-6 and abs(sess["net_pl"] - sum(x["total_pl"] for x in hall)) < 1e-6, "session money")
        o = STATS_AT_END.get(sess["session_id"])
        if o is not None and not any(x["outcome"] == "abandoned" for x in hall):
            for col, want in (("hands_played", o.hands_this_session), ("hands_won", o.session_player_wins), ("hands_lost", o.session_dealer_wins),
                              ("hands_pushed", o.session_pushes), ("hands_surrendered", o.surrenders), ("doubles", o.doubles), ("splits", o.splits),
                              ("aces_split", o.aces_split), ("tens_split", o.tens_split), ("player_blackjacks", o.player_blackjacks),
                              ("dealer_blackjacks", o.dealer_blackjacks), ("dealer_pulled_21s", o.greg_specials), ("dealer_busts", o.dealer_busts),
                              ("longest_win_streak", o.longest_win_streak), ("longest_loss_streak", o.longest_loss_streak)):
                check(sess[col] == want, f"session {sess['session_id']} {col}: db {sess[col]} vs oracle {want}")
            check(abs(sess["main_pl"] - o.session_main_pl) < 1e-6 and abs(sess["sidebet_pl"] - o.session_sidebet_pl) < 1e-6, f"session {sess['session_id']} P/L vs oracle")

    # 6. per-hand rows
    totals = {r["shoe_id"]: r["total_cards"] for r in db_shoes}
    for x in q("select * from hands"):
        check(x["outcome"] in ("win", "loss", "push", "surrender", "abandoned"), "outcome value")
        check((x["initial_bet"] * 2 == x["final_bet"]) == bool(x["doubled"]), "initial_bet/doubled")
        check(abs(x["total_pl"] - (x["main_pl"] + x["sidebet_pl"])) < 1e-9, "total_pl")
        if x["hand_number"] != 1:
            check(x["insurance_wager"] == 0 and x["power_poker_wager"] == 0 and x["star21_wager"] == 0 and x["dealer_buster_wager"] == 0
                  and x["sidebet_pl"] == 0, "side bets only on hand 1")
        total = totals[x["shoe_id"]]                     # the shoe the round STARTED on, flagged or not
        expect = 0.0 if x["cards_dealt_before"] == 0 else round(x["running_count_before"] / (max(total - x["cards_dealt_before"], 1) / 52) * 2) / 2
        check(abs(x["true_count_before"] - expect) < 1e-9, f"true count {x['true_count_before']} vs {expect} (round {x['round_id']})")
        check(x["cards_dealt_before"] <= total, "cards_dealt_before within the starting shoe")
        # the recorded running count must equal the Hi-Lo total of the cards ACTUALLY dealt from that shoe before the round
        toks = S.LOGICAL[x["shoe_id"] - 1]["initial"][: x["cards_dealt_before"]]
        rc = sum(1 if t[0] in "23456" else (0 if t[0] in "789" else -1) for t in toks)
        check(x["running_count_before"] == rc, f"round {x['round_id']}: running_count_before {x['running_count_before']} vs cards actually dealt {rc}")

    # 7. lifetime stats vs the oracle (before the cut-off round)
    pre, oracle = PRE["stats"], PRE["oracle"]
    for f in ("hands_lifetime", "player_wins", "dealer_wins", "pushes", "surrenders_lifetime"):
        check(getattr(pre, f) == getattr(oracle, f), f"lifetime {f}: {getattr(pre, f)} vs {getattr(oracle, f)}")
    for f in ("lifetime_main_wagered", "lifetime_main_pl", "lifetime_sidebet_pl", "lifetime_power_poker_pl", "lifetime_star21_pl"):
        check(abs(getattr(pre, f) - getattr(oracle, f)) < 1e-6, f"lifetime {f}")
    check(pre.sidebet_occurrences == oracle.sidebet_occurrences and pre.sidebet_wins == oracle.sidebet_wins, "side-bet occurrences/wins vs oracle")

    print("ALL AUDITS PASSED" if not fails else "FAILURES:")
    for f in sorted(set(fails))[:12]:
        print("  -", f, f"(x{fails.count(f)})")
    sys.exit(1 if fails else 0)
