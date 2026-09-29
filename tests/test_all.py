"""Runs every check script, each in its own process with its own throwaway HOME (so nothing here can touch
~/.cs-blackjack or your saved game), under the standard library's unittest:

    python3 -m unittest discover -s tests -v       # from the repository root
    python3 tests/test_all.py                      # the same thing

    CSBJ_FULL=1 python3 tests/test_all.py          # also: the mutation check and a much longer audit

check_ui.py needs the third-party `pyte` package (pip install pyte) and is skipped without it. Each script can
also be run on its own, e.g. `python3 tests/check_failsafe.py`."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = os.environ.get("CSBJ_FULL") == "1"


def run(script, *args, env=None, timeout=3600):
    child_env = {**os.environ, **(env or {})}
    child_env.pop("CSBJ_TEST_HOME", None)        # never share (or reuse) another run's data folder
    return subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True, env=child_env,
                          timeout=timeout, cwd=str(HERE.parent))


def failure_report(res):
    lines = (res.stdout + res.stderr).splitlines()
    interesting = [l for l in lines if l.startswith(("FAIL", "  - ", "Traceback", "  File")) or "Error" in l]
    return "\n".join((interesting or lines)[-60:])


class Checks(unittest.TestCase):
    def check_script(self, script, *args, env=None):
        res = run(script, *args, env=env)
        if "SKIPPED" in res.stdout:
            self.skipTest(res.stdout.strip().splitlines()[-1])
        self.assertEqual(res.returncode, 0, f"\n{script} failed:\n{failure_report(res)}")


def _add(name, script, *args, env=None):
    setattr(Checks, f"test_{name}", lambda self: self.check_script(script, *args, env=env))


_add("failsafe", "check_failsafe.py")
_add("history_reshuffle", "check_history_reshuffle.py")
_add("split_cap", "check_split_cap.py")
_add("data_safety", "check_data_safety.py")
_add("stats_and_import", "check_stats_and_import.py")
_add("locked_db", "check_locked_db.py")
_add("audit", "check_audit.py", env={"CSBJ_AUDIT_ROUNDS": "20000" if FULL else "2500"})
_add("ui", "check_ui.py")


class Tools(unittest.TestCase):
    """Smoke runs of the analysis tools on small samples: they must run, and a crash (a shoe running dry with no
    failsafe) is a failure. The full-size runs are described in CS-BLACKJACK.md."""

    def tool(self, *args, env=None):
        res = run(str(Path("tools") / args[0]), *args[1:], env=env)
        self.assertEqual(res.returncode, 0, f"\n{args[0]} failed:\n{failure_report(res)}")

    def test_consumption(self):
        self.tool("consumption.py", "100")

    def test_montecarlo_no_crashes(self):
        self.tool("montecarlo.py", "300", "--check")

    def test_adversary_no_crashes(self):
        self.tool("adversary.py", "--scale", "0.01", "--check")

    @unittest.skipUnless(FULL, "slow; set CSBJ_FULL=1")
    def test_mutations_are_caught(self):
        self.tool("mutation_check.py")


if __name__ == "__main__":
    unittest.main(verbosity=2)
