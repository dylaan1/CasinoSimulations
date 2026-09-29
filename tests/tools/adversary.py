"""Adversarial search: for a shuffle and a number of cards left at round start, try EVERY legal line of play
(hit / stand / double / split) through the real engine and report whether any line crashes and whether any line
needs the mid-round reshuffle failsafe. A Dealer Buster wager forces the dealer to play out even after a bust.

A shuffle where no line needs the failsafe is searched exhaustively; the search stops early at the first line
that does (then finishes that round greedily to prove the continuation is safe), and a node cap bounds the
time per shuffle -- shuffles that hit it are reported as 'search-capped' (not exhaustively proven).

    python3 tests/tools/adversary.py [only configs containing this text] [--scale 0.05]
    python3 tests/tools/adversary.py --scale 0.02 --check     # exit status 1 if any crash (used by test_all.py)"""
import os
import random
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _support import *  # noqa: F401,F403,E402
import _support as S  # noqa: E402

WORKERS = int(os.environ.get("CSBJ_WORKERS", os.cpu_count() or 4))


def make(decks, hands, order, remaining):
    rules = rules_m.Rules(num_decks=decks, num_hands=hands, split_max_hands=4, rsa=True, rsa_max_hands=4, das=True,
                          surrender="off", double_blackjack=True)
    rules.dealer_buster.enabled = True
    rules.dealer_buster.max_bet = 100
    sbw = [{"power_poker": 0, "star21": 0, "dealer_buster": 10} for _ in range(3)]
    s = engine.GameSession(1e12, rules, [10, 10, 10], sbw)
    dealt = len(order) - remaining
    s.shoe._cards = list(reversed(order[dealt:]))
    s.shoe._initial_order = list(order)
    s.shoe.cards_dealt = dealt
    return s


def run_path(decks, hands, order, remaining, path):
    random.seed(20260929)   # the failsafe's reshuffle is random: replaying a line of play must see the same shuffle every time
    s = make(decks, hands, order, remaining)
    r, err = engine.try_start_round(s)
    assert r is not None, err
    idx = 0
    while True:
        ph = r.phase
        if ph == Phase.EARLY_SURRENDER:
            r.respond_early_surrender(False)
        elif ph == Phase.INSURANCE:
            r.respond_insurance(False)
        elif ph == Phase.DOUBLE_BLACKJACK:
            r.respond_double_blackjack(True)
        elif ph == Phase.PLAYER_TURN:
            spot, hand = r.current_player_hand()
            legal = sorted(r.legal_actions(spot, hand) - {"surrender"})
            if idx == len(path):
                return "DECIDE", legal, r
            assert r.perform_action(path[idx]) is None
            idx += 1
        elif ph == Phase.DEALER_TURN:
            r.step_dealer()
        elif ph == Phase.REVEAL:
            r.reveal_doubles()
        else:
            return "DONE", None, r


def finish_greedily(r):
    """Complete a round that hit the failsafe by always splitting/hitting (the most card-hungry continuation)."""
    S.finish_round(r, lambda rr, spot, hand, legal: next(a for a in ("split", "hit", "double", "stand") if a in legal - {"surrender"}))


def explore(decks, hands, order, remaining, node_cap=40000):
    stack, nodes = [[]], 0
    while stack:
        path = stack.pop()
        nodes += 1
        if nodes > node_cap:
            return "CAPPED", False
        try:
            status, legal, r = run_path(decks, hands, order, remaining, path)
            if r.reshuffled_mid_round:
                if status == "DECIDE":
                    finish_greedily(r)
                return "DONE", True
        except Exception as exc:   # ANY exception is a crash the failsafe should have prevented
            return "CRASH:" + type(exc).__name__ + ":" + str(exc)[:60] + " @ " + traceback.format_exc().strip().splitlines()[-3][:120], False
        if status == "DECIDE":
            hunger = {"split": 0, "hit": 1, "double": 2, "stand": 3}      # the most card-hungry move is popped (explored) first
            stack.extend(path + [a] for a in sorted(legal, key=lambda x: -hunger[x]))
    return "DONE", False


def job(args):
    decks, hands, remaining, seed = args
    rng = random.Random(seed)
    order = list(S.FULL) * decks
    rng.shuffle(order)
    return explore(decks, hands, order, remaining)


CONFIGS = [  # (label, decks, hands, cards left at the deepest legal round start, shuffles)
    ("1 deck,  1 hand  (24 left)", 1, 1, 24, 4000),
    ("1 deck,  2 hands (24 left)", 1, 2, 24, 4000),
    ("6 decks, 1 hand  (28 left)", 6, 1, 28, 3000),
    ("6 decks, 2 hands (40 left)", 6, 2, 40, 1500),
    ("6 decks, 3 hands (52 left)", 6, 3, 52, 800),
    ("3 decks, 3 hands (52 left)", 3, 3, 52, 800),
]

if __name__ == "__main__":
    from multiprocessing import Pool
    argv = sys.argv[1:]
    check_mode = "--check" in argv
    scale = float(argv[argv.index("--scale") + 1]) if "--scale" in argv else 1.0
    only = next((a for a in argv if not a.startswith("--") and not a.replace(".", "").isdigit()), "")
    t0 = time.time()
    total_crashes = 0
    with Pool(WORKERS) as pool:
        print("every legal line of play, at the deepest legal round start")
        for label, decks, hands, R, n in CONFIGS:
            if only and only not in label:
                continue
            n = max(WORKERS, int(n * scale))
            res = pool.map(job, [(decks, hands, R, 5000 + i) for i in range(n)], chunksize=max(1, n // 64))
            crashes = [r for r in res if r[0].startswith("CRASH")]
            total_crashes += len(crashes)
            fired = sum(1 for r in res if r[1])
            capped = sum(1 for r in res if r[0] == "CAPPED")
            print(f"  {label:<30} {n:>6,} shuffles: crashes {len(crashes)}; some line needs the failsafe in {fired} ({fired / n:.3%}); search-capped {capped}", flush=True)
            if crashes:
                print("    e.g.", crashes[0])
    print("elapsed %.0fs" % (time.time() - t0))
    if check_mode and total_crashes:
        sys.exit(1)
