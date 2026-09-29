"""Shared helpers for the check_*.py scripts: an isolated HOME, the game's modules, a round driver,
play policies, sessions with stacked or thinned shoes, per-shoe card tracking, and a tiny checker.

Importing this module points HOME at a fresh temporary directory BEFORE the game is imported (the game
resolves ~/.cs-blackjack at import time), so no test ever touches your real data."""
import importlib
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent


def _isolated_home() -> str:
    if "CSBJ_TEST_HOME" in os.environ:            # a parent process (or an earlier import) already chose one
        return os.environ["CSBJ_TEST_HOME"]
    home = tempfile.mkdtemp(prefix="csbj-test-home-")
    os.environ["CSBJ_TEST_HOME"] = home
    return home


HOME = _isolated_home()
random.seed(int(os.environ.get("CSBJ_SEED", "20260929")))     # the game shuffles with the global RNG: a fixed seed makes a run repeatable (CSBJ_SEED=n varies it)
os.environ["HOME"] = HOME
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))

cb = lambda name: importlib.import_module("cs-blackjack." + name)
engine, rules_m, cards, history, persist, commands, stats_m, ui = (
    cb(n) for n in ("engine", "rules", "cards", "history", "persist", "commands", "stats", "ui"))
Phase = engine.Phase
FULL = [cards.Card(r, s) for r in cards.RANKS for s in cards.SUITS]
hilo = cards.hilo_value


# ---------------------------------------------------------------- results
class Checker:
    """check(cond, message) prints ok/FAIL and remembers failures; finish() sets the exit status."""

    def __init__(self):
        self.failures = []
        self.total = 0

    def __call__(self, cond, msg):
        self.total += 1
        print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            self.failures.append(msg)

    def finish(self, name):
        print()
        if self.failures:
            print(f"{name}: {len(self.failures)} of {self.total} CHECKS FAILED")
            for f in self.failures:
                print("  -", f)
        else:
            print(f"{name}: ALL {self.total} CHECKS PASSED")
        sys.exit(1 if self.failures else 0)


def reset_data():
    """Wipe the isolated data folder and state file so a test starts from a clean install."""
    shutil.rmtree(history.DATA_DIR, ignore_errors=True)
    for f in Path(HOME).glob(".cs-blackjack_state.json*"):
        f.unlink()
    persist.set_legacy_stats(None)


# ---------------------------------------------------------------- cards
def card(tok):
    rank = "10" if tok[0] == "T" else tok[0]
    return cards.Card(rank, {"♠": "spades", "♥": "hearts", "♦": "diamonds", "♣": "clubs"}[tok[1]])


def tally(cs):
    out = {}
    for c in cs:
        t = c.token if hasattr(c, "token") else c
        out[t] = out.get(t, 0) + 1
    return out


# ---------------------------------------------------------------- driving rounds
def choose(policy, rng, r, hand, legal):
    """A play policy: 'basic' (roughly basic strategy), 'random' (a random legal action), or 'greedy'
    (split and hit whenever possible -- the most card-hungry player)."""
    legal = legal - {"surrender"}
    if policy == "random":
        w = {"hit": 4, "stand": 3, "double": 1, "split": 2}
        opts = sorted(legal)
        return rng.choices(opts, [w[o] for o in opts])[0]
    if policy == "greedy":
        for a in ("split", "hit", "double", "stand"):
            if a in legal:
                return a
    up = r.dealer_up.value
    total, soft = hand.best_value, hand.is_soft
    if "split" in legal and hand.cards[0].rank in ("A", "8"):
        return "split"
    if "double" in legal and not soft and total in (10, 11) and up <= 9:
        return "double"
    if soft:
        return "hit" if total <= 17 else "stand"
    if total < 12:
        return "hit"
    if total >= 17:
        return "stand"
    return "stand" if up <= 6 else "hit"


def play_round(session, rng, policy="random"):
    """Play one round to SETTLED through the real engine; returns (round, error)."""
    r, err = engine.try_start_round(session)
    if err:
        return None, err
    guard = 0
    while r.phase != Phase.SETTLED:
        guard += 1
        assert guard < 600, "round did not terminate"
        ph = r.phase
        if ph == Phase.EARLY_SURRENDER:
            r.respond_early_surrender(rng.random() < 0.3)
        elif ph == Phase.INSURANCE:
            r.respond_insurance(rng.random() < 0.5)
        elif ph == Phase.DOUBLE_BLACKJACK:
            r.respond_double_blackjack(rng.random() < 0.5)
        elif ph == Phase.PLAYER_TURN:
            spot, hand = r.current_player_hand()
            assert r.perform_action(choose(policy, rng, r, hand, r.legal_actions(spot, hand))) is None
        elif ph == Phase.DEALER_TURN:
            r.step_dealer()
        elif ph == Phase.REVEAL:
            r.reveal_doubles()
    return r, None


def finish_round(r, policy=None):
    """Finish a round already in progress. `policy(r, spot, hand, legal) -> action`; default: stand."""
    guard = 0
    while r.phase != Phase.SETTLED:
        guard += 1
        assert guard < 300
        ph = r.phase
        if ph == Phase.EARLY_SURRENDER:
            r.respond_early_surrender(False)
        elif ph == Phase.INSURANCE:
            r.respond_insurance(False)
        elif ph == Phase.DOUBLE_BLACKJACK:
            r.respond_double_blackjack(False)
        elif ph == Phase.PLAYER_TURN:
            spot, hand = r.current_player_hand()
            legal = r.legal_actions(spot, hand)
            act = policy(r, spot, hand, legal) if policy else "stand"
            assert r.perform_action(act if act in legal else "stand") is None
        elif ph == Phase.DEALER_TURN:
            r.step_dealer()
        elif ph == Phase.REVEAL:
            r.reveal_doubles()


# ---------------------------------------------------------------- sessions
def make_session(decks=1, hands=1, history_db=None, bankroll=1e12, **rule_kw):
    rule_kw.setdefault("surrender", "off")
    rules = rules_m.Rules(num_decks=decks, num_hands=hands, **rule_kw)
    s = engine.GameSession(bankroll, rules, [10, 10, 10], None, history=history_db)
    return s


def stacked(decks, lead_tokens, hands=1, **rule_kw):
    """A session whose shoe deals `lead_tokens` first (in that order) and is then empty -- so the next draw
    triggers the mid-round reshuffle."""
    s = make_session(decks, hands, **rule_kw)
    lead = [card(t) for t in lead_tokens]
    s.shoe._cards = list(reversed(lead))
    s.shoe._initial_order = lead[:]
    s.shoe.cards_dealt = 0
    return s


def thin_session(decks, keep, hands=1, **rule_kw):
    """A session whose shoe has only `keep` cards left (the rest already dealt), so a round is likely to run
    it dry. The shoe's bookkeeping stays consistent."""
    s = make_session(decks, hands, **rule_kw)
    for _ in range(s.shoe.total_cards - keep):
        s.shoe.draw()
    return s


def burn_to(session, keep):
    while session.shoe.cards_remaining > keep:
        session.shoe.draw()


# ---------------------------------------------------------------- per-shoe card tracking
LOGICAL = []   # one entry per shoe ROW the history should hold (a mid-round reshuffle is its own logical shoe,
               # even though the same Shoe object is rebuilt in place)
_CURRENT = {}


def install_shoe_tracking():
    orig_post, orig_draw, orig_reshuffle = cards.Shoe.__post_init__, cards.Shoe.draw, cards.Shoe.reshuffle_around

    def post(self):
        orig_post(self)
        entry = {"drawn": [], "initial": [c.token for c in self._initial_order], "num_decks": self.num_decks,
                 "penetration": self.penetration, "midround": False}
        LOGICAL.append(entry)
        _CURRENT[id(self)] = entry

    def draw(self):
        c = orig_draw(self)
        _CURRENT[id(self)]["drawn"].append(c.token)
        return c

    def reshuffle(self, table):
        orig_reshuffle(self, table)
        entry = {"drawn": [c.token for c in table], "initial": [c.token for c in self._initial_order],
                 "num_decks": self.num_decks, "penetration": self.penetration, "midround": True}
        LOGICAL.append(entry)
        _CURRENT[id(self)] = entry

    cards.Shoe.__post_init__, cards.Shoe.draw, cards.Shoe.reshuffle_around = post, draw, reshuffle


def shoe_invariants_ok(session, r):
    """After a settled round: every card drawn is on the table exactly once, and the shoe (dealt prefix +
    remainder) is exactly the decks, with a running count that matches the dealt cards."""
    on_table = [c for spot in r.spots for h in spot.hands for c in h.cards] + list(r.dealer_hand.cards)
    shoe = session.shoe
    whole = shoe._initial_order[: shoe.cards_dealt] + list(reversed(shoe._cards))
    return (tally(on_table) == tally(r.drawn)
            and shoe.cards_remaining + shoe.cards_dealt == shoe.total_cards
            and tally(whole) == tally(FULL * shoe.num_decks)
            and shoe.running_count == sum(hilo(c) for c in shoe._initial_order[: shoe.cards_dealt])
            and r.visible_counts() == (shoe.running_count, shoe.true_count))
