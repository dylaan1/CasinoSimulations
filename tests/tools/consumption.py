"""How many cards does one round consume? The distribution over many rounds, by hands in play and play style
(multi-deck rules, default split limits, a Dealer Buster wager so the dealer always plays out). This is the
measurement the minimum-cards floors in rules.py were chosen from.

    python3 tests/tools/consumption.py [rounds per worker, default 25000]"""
import os
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _support import *  # noqa: F401,F403,E402
import _support as S  # noqa: E402

WORKERS = int(os.environ.get("CSBJ_WORKERS", os.cpu_count() or 4))


def run(args):
    hands, policy, n, seed = args
    rng = random.Random(seed)
    random.seed(seed)
    rules = rules_m.Rules(num_decks=8, num_hands=hands, rsa=True, das=True, double_blackjack=True, surrender="late")
    rules.dealer_buster.enabled = True
    rules.dealer_buster.max_bet = 100
    sbw = [{"power_poker": 0, "star21": 0, "dealer_buster": 10} for _ in range(3)]
    s = engine.GameSession(1e12, rules, [10, 10, 10], sbw)
    used = []
    for _ in range(n):
        s.reset_shoe()                       # a full shoe every round: we want the round's own appetite, nothing else
        r, _ = S.play_round(s, rng, policy)
        assert not r.reshuffled_mid_round
        used.append(len(r.drawn))
    return used


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 25000
    t0 = time.time()
    with Pool(WORKERS) as pool:
        print(f"cards drawn in one round, {WORKERS * n:,} rounds per row (8 decks, default splitmax 4 / RSA 4, Dealer Buster forcing the dealer to play)")
        print(f"{'hands':>5} {'policy':<8} {'mean':>6} {'p99':>5} {'p99.9':>6} {'p99.99':>7} {'max':>5}")
        for hands in (1, 2, 3):
            for policy in ("basic", "random", "greedy"):
                used = sorted(x for part in pool.map(run, [(hands, policy, n, 100 + i) for i in range(WORKERS)]) for x in part)
                q = lambda p: used[min(len(used) - 1, int(len(used) * p))]  # noqa: E731
                print(f"{hands:>5} {policy:<8} {sum(used) / len(used):>6.1f} {q(.99):>5} {q(.999):>6} {q(.9999):>7} {used[-1]:>5}", flush=True)
    print("elapsed %.0fs" % (time.time() - t0))
