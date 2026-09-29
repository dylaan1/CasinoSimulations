"""The real game, in a pseudo-terminal: deck-size rules and their messages, no hand lock, a genuine mid-hand
reshuffle on screen, and the data written when the game is quit or killed. Needs `pyte` (pip install pyte);
skipped without it. Takes about a minute -- it types at human speed so the curses screen keeps up."""
import importlib.util
import os
import signal
import sqlite3
import sys
import tempfile
import time

missing = [m for m in ("pty", "pyte") if importlib.util.find_spec(m) is None]   # pty is Unix-only; pyte is a pip package
if missing:
    print(f"check_ui: SKIPPED ({missing[0]} not available -- pip install pyte)")
    sys.exit(0)

from ui_support import FORCED_LAUNCHER, LEFT, RIGHT, Game

fails = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def db(home):
    c = sqlite3.connect(os.path.join(home, ".cs-blackjack", "blackjack.db"))
    c.row_factory = sqlite3.Row
    return c


def quit_game(g):
    g.send("\x1b", 1.3)
    g.command("quit", 1.5)
    return g.wait_exit()


# =============================================================== A. deck-size rules through the UI
home = tempfile.mkdtemp(prefix="csbj-ui-")
g = Game(home)
g.pump(2.5)
check("6 DECK  •  75%" in g.text(), "starts as the default 6-deck, 75% game")

g.command("decks 1")
msg = g.line_with("single-deck limits")
check(msg is not None and "24 cards" in msg and "at most 2 hands" in msg, f"'decks 1' explains the limits: {msg[:120] if msg else None}")
g.command("newshoe", 0.5)
g.send("\r", 3.0)
check("1 DECK  •  54%" in g.text(), "single-deck header shows the real cut depth: 1 DECK • 54%")
g.command("hands 3")
check(g.line_with("Single-deck games are limited to 2 hands") is not None, "'hands 3' is refused on a single deck")

# fund Hand #2 through the grid -> 2 hands; play a round; then go back to 1 hand mid-shoe
g.send("\x1b", 1.3)
g.send(LEFT, 0.4); g.send("10", 0.4); g.send("\r", 0.8)
check(g.wager_row() is not None and g.wager_row()[0] == "10", f"Hand #2 funded through the grid: {g.wager_row()}")
g.send("\r", 4.0)
g.to_idle()
g.command("hands 1")
check(g.line_with("Playing 1 hand(s) per round") is not None and g.line_with("locked") is None,
      "AFTER a round on this shoe, 'hands 1' is accepted (there is no lock any more)")
g.send("\r", 4.0)
g.to_idle()
g.command("hands 2")
check(g.line_with("Playing 2 hand(s) per round") is not None, "...and back to 2 hands, mid-shoe")
g.send("\r", 4.0)
g.to_idle()

# clearing Hand #2's wager through the grid used to be refused while locked; now it's allowed
g.send("\x1b", 1.3)
g.send(LEFT, 0.4); g.send("0", 0.4); g.send("\r", 0.8)
check(g.line_with("locked") is None and g.wager_row() is not None and g.wager_row()[0] == "0", f"clearing Hand #2 through the grid is allowed: {g.wager_row()}")
g.send(RIGHT, 0.4); g.send(RIGHT, 0.4); g.send("10", 0.4); g.send("\r", 0.8)
check(g.line_with("Single-deck games are limited to 2 hands") is not None, "...but funding Hand #3 is still refused")

g.command("gamerules", 1.0)
scr = g.text()
check("SINGLE-DECK LIMITS" in scr and "at least 24 cards left" in scr and "RUNNING OUT OF CARDS" in scr
      and "locked at" not in scr and "until the next shuffle" not in scr and "changeable any time" in scr,
      "gamerules: shows the 24-card minimum and the failsafe note, and no hand-lock text (only the side-bet deck locks remain)")
g.send(" ", 0.6)

g.command("decks 2", 0.5)
g.command("newshoe", 0.5)
g.send("\r", 3.0)
check("2 DECK  •  75%" in g.text(), "two decks at the default deckpen: 2 DECK • 75%")
g.command("deckpen 0.95")
msg = g.line_with("Deck penetration set")
check(msg is not None and "capped at 0.80" in msg, f"'deckpen 0.95' on two decks: {msg}")
g.command("newshoe", 0.5)
g.send("\r", 3.0)
check("2 DECK  •  80%" in g.text(), "...and the header shows the 80% cap")

# three or more decks: the floor scales with the hands in play
g.command("decks 6", 0.5)
g.command("newshoe", 0.5)
g.send("\r", 3.0)
g.command("deckpen 0.99")
msg = g.line_with("Deck penetration set")
check(msg is not None and "fewer than 28 cards" in msg, f"'deckpen 0.99' on six decks with 1 hand names the 28-card floor: {msg}")
g.command("hands 2")
g.command("deckpen 0.99")
msg = g.line_with("Deck penetration set")
check(msg is not None and "fewer than 40 cards" in msg, f"...and with 2 hands, 40: {msg}")
g.command("newshoe", 0.5)
g.send("\r", 3.0)
check("6 DECK  •  87%" in g.text(), "the header shows the depth that actually applies at 2 hands (1 - 40/312 = 87%)")
g.command("gamerules", 1.0)
scr = g.text()
check("MINIMUM CARDS" in scr and "28 / 40 / 52 for 1 / 2 / 3 hands" in scr and "RUNNING OUT OF CARDS" in scr, "gamerules: shows the per-hand floors (28 / 40 / 52) and the failsafe note")
g.send(" ", 0.6)

check(quit_game(g), "clean exit")
c = db(home)
check(c.execute("pragma integrity_check").fetchone()[0] == "ok" and c.execute("pragma user_version").fetchone()[0] == 3, "database intact, schema v3")
rows = c.execute("select card_order, retired_at from shoes").fetchall()
check(all("|" in r[0] and r[1] for r in rows), f"every shoe retired with its '|' marker ({len(rows)} shoes)")
check(c.execute("select count(*) from hands").fetchone()[0] >= 3 and c.execute("select count(*) from hands where reshuffled_mid_round=1").fetchone()[0] == 0,
      "rounds were logged, none flagged as reshuffled (nothing ran out)")
spots = [r[0] for r in c.execute("select count(distinct spot_number) from hands group by round_id")]
check(1 in spots and 2 in spots, f"the rounds alternated between 1 and 2 hands on the same single-deck shoe ({sorted(set(spots))})")
c.close()

# =============================================================== B. a real mid-hand reshuffle on screen
home = tempfile.mkdtemp(prefix="csbj-ui-rs-")
g = Game(home, cmd=[sys.executable, str(FORCED_LAUNCHER)])
g.pump(2.5)
check(g.alive(), "launched with a five-card first shoe")
g.send("\r", 4.0)                                  # deal 2♣ / 9♦ / 3♣ / 8♦
check("SPACE Hit" in g.text(), "the round is in the player's turn")
g.send(" ", 1.5)                                   # hit: takes the spare 4♥ (player 9); the shoe is now empty
check("mid-hand" not in g.text(), "after the first hit the shoe is empty but nothing has happened yet")
os.write(g.fd, b" ")                               # hit again: needs a card that isn't there
seen = None
t_end = time.time() + 8
while time.time() < t_end and seen is None:
    g.pump(0.25)
    seen = g.line_with("mid-hand")
check(seen is not None and "reshuffled" in seen, f"the player is told what happened: {seen}")
check(b"Traceback" not in g.raw and g.alive(), "no crash: the game is still running")
g.send("\r", 3.0)                                  # stand
g.to_idle()
check("[RETURN] to Deal" in g.text(), "the round finished normally and the game is back at the betting screen")
check(quit_game(g), "clean exit")
c = db(home)
flagged = c.execute("select count(*), min(shoe_id) from hands where reshuffled_mid_round=1").fetchone()
mid = c.execute("select shoe_id, cut_reason from shoes where cut_reason='mid_round'").fetchall()
check(flagged[0] >= 1 and len(mid) == 1, f"the database flagged the round ({flagged[0]} hand row(s)) and opened one mid_round shoe (id {mid[0][0] if mid else None})")
check(mid and flagged[1] == mid[0][0] - 1, "...and that round's rows point at the shoe it started on, not the new one")
old = c.execute("select card_order from shoes where shoe_id=?", (flagged[1],)).fetchone()[0]
check(old.endswith("|"), "the exhausted shoe was closed off with its '|' marker and an empty never-dealt tail")
check(c.execute("select count(*) from shoes where retired_at is null").fetchone()[0] == 0, "every shoe is retired after quit")
c.close()

# =============================================================== C. what survives being closed or killed
for label, sig in (("SIGTERM (kill)", signal.SIGTERM), ("SIGHUP (terminal window closed)", signal.SIGHUP)):
    home = tempfile.mkdtemp(prefix="csbj-ui-sig-")
    g = Game(home)
    g.pump(2.5)
    g.send("\r", 4.0)
    g.to_idle()
    g.send("\r", 4.0)                                   # a second round, so cards have been dealt
    g.kill(sig)
    check(g.wait_exit(10), f"{label}: the game exits")
    c = db(home)
    shoe = c.execute("select * from shoes order by shoe_id desc limit 1").fetchone()
    dealt, bar, tail = shoe["card_order"].partition("|")
    check(bool(bar) and len(dealt) == 2 * shoe["cards_dealt"] and len(tail) > 0 and shoe["retired_at"] is not None,
          f"{label}: the shoe is retired with its dealt cards, '|', and the never-dealt tail ({len(dealt) // 2} + {len(tail) // 2} cards)")
    check(len(dealt + tail) == 2 * 312, f"{label}: dealt + never-dealt account for all 312 cards")
    check(c.execute("select count(*) from sessions where ended_at is null").fetchone()[0] == 0, f"{label}: the session was closed")
    check(c.execute("select count(*) from hands").fetchone()[0] >= 1, f"{label}: the rounds played were kept")
    c.close()

# =============================================================== D. --db starts from a clean slate
home = tempfile.mkdtemp(prefix="csbj-ui-db-")
fresh = os.path.join(home, "practice.db")
g = Game(home, args=("--db", fresh))
g.pump(2.5)
g.send("\r", 4.0)
g.to_idle()
check(quit_game(g), "--db: clean exit")
check(os.path.exists(fresh) and not os.path.exists(os.path.join(home, ".cs-blackjack", "blackjack.db")), "--db FILE: history goes to that file, and the default database was not created")
c = sqlite3.connect(fresh)
check(c.execute("select count(*) from hands").fetchone()[0] >= 1, "...and it holds the rounds played")
c.close()

print()
print("check_ui: FAILED" if fails else "check_ui: ALL UI CHECKS PASSED", *fails, sep="\n  - " if fails else "")
sys.exit(1 if fails else 0)
