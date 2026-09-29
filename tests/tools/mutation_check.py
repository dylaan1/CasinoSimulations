"""Mutation check: inject known bugs into the game and confirm the checks notice each one.
A check that can't fail proves nothing; this proves they can.

    python3 tests/tools/mutation_check.py            # every mutation
    python3 tests/tools/mutation_check.py shoe_id    # just one

Each mutation runs in its own process (so a broken game can't leak into the next) and must make the check script
named for it FAIL. The script exits non-zero if any mutation slips through unnoticed.
"""
import os
import runpy
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent
MUTATIONS = {   # name: (check script that must catch it, what is broken)
    "shoe_id": ("check_audit.py", "rows of a reshuffled round get the NEW shoe's id instead of the shoe the round started on"),
    "flag": ("check_audit.py", "reshuffled_mid_round is never set"),
    "lose_card": ("check_audit.py", "the reshuffle silently drops a card that wasn't on the table"),
    "count": ("check_audit.py", "the running count after a reshuffle forgets the table cards"),
    "retire_order": ("check_audit.py", "the exhausted shoe is retired AFTER it was refilled (wrong dealt/undealt split)"),
    "import_sign": ("check_stats_and_import.py", "the legacy import clamps negative money figures (a losing side bet) to zero"),
    "drop_rounds": ("check_locked_db.py", "rounds queued behind a locked database are discarded when a write fails"),
    "drop_shoes": ("check_locked_db.py", "shoe changes queued behind a locked database are discarded when a write fails"),
}


def apply(which):
    sys.path.insert(0, str(TESTS))
    import _support as S
    history, cards, engine = S.history, S.cards, S.engine
    if which == "shoe_id":
        orig = history.HistoryDB._round_rows

        def bad(self, session, round_):
            round_.history_shoe_id = None
            return orig(self, session, round_)
        history.HistoryDB._round_rows = bad
    elif which == "flag":
        orig = history.HistoryDB._round_rows

        def bad(self, session, round_):
            rows = orig(self, session, round_)
            for r in rows:
                r["reshuffled_mid_round"] = 0
            return rows
        history.HistoryDB._round_rows = bad
    elif which == "lose_card":
        orig = cards.Shoe.reshuffle_around

        def bad(self, table):
            orig(self, table)
            self._cards.pop()
            self._initial_order.pop()
        cards.Shoe.reshuffle_around = bad
    elif which == "count":
        orig = cards.Shoe.reshuffle_around

        def bad(self, table):
            orig(self, table)
            self.running_count = 0
        cards.Shoe.reshuffle_around = bad
    elif which == "retire_order":
        orig = engine.GameSession.reshuffle_mid_round

        def bad(self, round_):
            h = self.history
            self.history = None                    # skip the log's retire/cut inside...
            orig(self, round_)
            self.history = h
            if h is not None:
                round_.history_shoe_id = h.shoe_id
                h.shoe_retired(self)               # ...then retire the REFILLED shoe by mistake
                h.shoe_cut(self, "mid_round")
        engine.GameSession.reshuffle_mid_round = bad
    elif which == "import_sign":
        stats_orig = S.stats_m.Stats.from_legacy_dict.__func__

        def clamped(cls, data):
            st = stats_orig(cls, data)
            for name in history._LIFETIME_MONEY:
                setattr(st, name, max(0.0, getattr(st, name)))
            return st
        S.stats_m.Stats.from_legacy_dict = classmethod(clamped)
    elif which == "drop_rounds":
        orig = history.HistoryDB._flush_pending

        def bad(self, session):
            ok = orig(self, session)
            if not ok:
                self._pending_rounds.clear()
            return ok
        history.HistoryDB._flush_pending = bad
    elif which == "drop_shoes":
        orig = history.HistoryDB._flush_shoe_ops

        def bad(self):
            ok = orig(self)
            if not ok:
                self._pending_shoe_ops.clear()
            return True
        history.HistoryDB._flush_shoe_ops = bad
    else:
        raise SystemExit(f"unknown mutation {which!r}")


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        apply(sys.argv[2])
        script = MUTATIONS[sys.argv[2]][0]
        os.environ.setdefault("CSBJ_AUDIT_ROUNDS", "2500")
        sys.argv = [script]
        runpy.run_path(str(TESTS / script), run_name="__main__")
        return
    chosen = sys.argv[1:] or list(MUTATIONS)
    slipped = []
    for name in chosen:
        res = subprocess.run([sys.executable, __file__, "--child", name], capture_output=True, text=True)
        caught = res.returncode != 0 and "Traceback" not in res.stderr     # a failed check, not a mutation that merely crashed the script
        print(f"{'caught' if caught else 'MISSED':<7} {name:<13} {MUTATIONS[name][1]}")
        if not caught:
            slipped.append(name)
    print()
    print("every mutation was caught" if not slipped else f"MISSED: {', '.join(slipped)}")
    sys.exit(1 if slipped else 0)


if __name__ == "__main__":
    main()
