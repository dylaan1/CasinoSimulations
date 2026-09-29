"""Crash and failsafe rates by configuration. Each cell plays many rounds through the real engine at the deepest
penetration the settings allow, with three play styles (basic ~ basic strategy, random, greedy = split and hit
whenever possible), and reports per million rounds: how often a shoe ran dry with NO failsafe (a crash -- must be
0) / how often the mid-round reshuffle fired.

    python3 tests/tools/montecarlo.py [rounds per worker, default 15000] [only configs containing this text]
    python3 tests/tools/montecarlo.py 2000 --check     # exit status 1 if any crash (used by test_all.py)"""
import os
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _support import *  # noqa: F401,F403,E402
import _support as S  # noqa: E402

P = engine.Phase
WORKERS = int(os.environ.get("CSBJ_WORKERS", os.cpu_count() or 4))


def run(args):
    decks, hands, pen, policy, n_rounds, seed = args
    rng = random.Random(seed)
    random.seed(seed)
    rules = rules_m.Rules(num_decks=decks, penetration=pen, num_hands=hands, rsa=True, das=True, double_blackjack=True, surrender="late")
    rules.dealer_buster.enabled = True
    rules.dealer_buster.max_bet = 100
    sbw = [{"power_poker": 0, "star21": 0, "dealer_buster": 10} for _ in range(3)]
    s = engine.GameSession(1e12, rules, [10, 10, 10], sbw)
    s.ensure_shoe_ready()
    crashed = fired = rounds = 0
    for _ in range(n_rounds):
        try:
            r, err = engine.try_start_round(s)
            guard = 0
            while r.phase != P.SETTLED:
                guard += 1
                assert guard < 500
                ph = r.phase
                if ph == P.EARLY_SURRENDER:
                    r.respond_early_surrender(False)
                elif ph == P.INSURANCE:
                    r.respond_insurance(policy == "random" and rng.random() < 0.5)
                elif ph == P.DOUBLE_BLACKJACK:
                    r.respond_double_blackjack(policy != "basic")
                elif ph == P.PLAYER_TURN:
                    sp, h = r.current_player_hand()
                    assert r.perform_action(S.choose(policy, rng, r, h, r.legal_actions(sp, h))) is None
                elif ph == P.DEALER_TURN:
                    r.step_dealer()
                elif ph == P.REVEAL:
                    r.reveal_doubles()
            fired += bool(r.reshuffled_mid_round)
            rounds += 1
            s.ensure_shoe_ready()
        except RuntimeError as exc:
            assert "empty" in str(exc), exc
            crashed += 1
            rounds += 1
            s.reset_shoe()
    return crashed, fired, rounds


CONFIGS = [  # (label, decks, hands, requested penetration)
    (f"{d} deck{'s' if d > 1 else ' '}, {h} hand{'s' if h > 1 else ' '}, deckpen {p}", d, h, p)
    for d, p, hands in ((1, 0.99, (1, 2)), (2, 0.95, (1, 2, 3)), (3, 0.95, (1, 2, 3)), (4, 0.95, (1, 2, 3)), (6, 0.95, (1, 2, 3)), (8, 1.0, (1, 2, 3)))
    for h in hands
]

if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    check_mode = "--check" in sys.argv
    per = int(argv[0]) if argv else 15000
    only = argv[1] if len(argv) > 1 else ""
    t0 = time.time()
    total_crashes = 0
    with Pool(WORKERS) as pool:
        print(f"{per * WORKERS:,} rounds per cell   each cell: crashes / failsafe-reshuffles per million rounds")
        print(f"{'configuration':<34}" + "".join(f"{p:>26}" for p in ("basic", "random", "greedy")))
        for label, decks, hands, pen in CONFIGS:
            if only and only not in label:
                continue
            row = f"{label:<34}"
            for policy in ("basic", "random", "greedy"):
                res = pool.map(run, [(decks, hands, pen, policy, per, 900 + i) for i in range(WORKERS)])
                c, f, n = (sum(x[i] for x in res) for i in range(3))
                total_crashes += c
                row += f"{c / n * 1e6:>10.0f} / {f / n * 1e6:<12.0f}"
            print(row, flush=True)
    print(f"crashes in total: {total_crashes}")
    print("elapsed %.0fs" % (time.time() - t0))
    if check_mode and total_crashes:
        sys.exit(1)
