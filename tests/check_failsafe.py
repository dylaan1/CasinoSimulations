"""The mid-round reshuffle failsafe, and the rules that make it rare (minimum cards per deck size / hands)."""
import random

from _support import *  # noqa: F401,F403
import _support as S

check = S.Checker()


# =============================================================== A. Shoe.reshuffle_around on its own
bad = 0
for decks in (1, 2, 6):
    for k in (0, 1, 5, 17, 40):
        shoe = cards.Shoe(decks)
        table = [shoe.draw() for _ in range(k)]
        shoe.reshuffle_around(table)
        full = tally(FULL * decks)
        ok = (
            shoe.cards_remaining == shoe.total_cards - k
            and {t: tally(table).get(t, 0) + tally(shoe._cards).get(t, 0) for t in full} == full
            and shoe.dealt_string() == cards.cards_to_string(table)
            and [c.token for c in shoe._initial_order[k:]] == [c.token for c in shoe._cards][::-1]
            and shoe.cards_dealt == k
            and shoe.running_count == sum(hilo(c) for c in table)
            and shoe.drawn_counts == {r: sum(1 for c in table if c.rank == r) for r in cards.RANKS}
            and shoe.cards_remaining + shoe.cards_dealt == shoe.total_cards
        )
        if k < shoe.total_cards:
            ok = ok and shoe.draw() == shoe._initial_order[k]    # the next card dealt follows the recorded order
        bad += not ok
check(bad == 0, "reshuffle_around conserves every card, keeps the table as the dealt prefix, recounts, and the next draw follows the order")
try:
    cards.Shoe(1).reshuffle_around([card("A♠"), card("A♠")])   # two copies of a card that exists once
    check(False, "reshuffle_around rejects a table that can't have come from this shoe")
except ValueError:
    check(True, "reshuffle_around rejects a table that can't have come from this shoe")
s1, s2 = cards.Shoe(6), cards.Shoe(6)
s1.reshuffle_around([]); s2.reshuffle_around([])
check([c.token for c in s1._cards] != [c.token for c in s2._cards], "each reshuffle is a genuinely new random order")


# =============================================================== B. exhaustion forced at every draw site
SITES = {
    "the initial deal (4th card)": (["7♠", "9♦", "3♣"], None),
    "a player hit": (["2♣", "9♦", "3♣", "8♦"], lambda r, sp, h, lg: "hit" if len(h.cards) < 3 else "stand"),
    "a double down": (["5♣", "9♦", "6♣", "8♦"], lambda r, sp, h, lg: "double"),
    "the 1st card of a split": (["8♣", "9♦", "8♥", "7♦"], lambda r, sp, h, lg: "split" if "split" in lg else "stand"),
    "the 2nd card of a split (a card is in transit between hands)": (["8♣", "9♦", "8♥", "7♦", "3♠"], lambda r, sp, h, lg: "split" if "split" in lg else "stand"),
    "a dealer draw": (["T♣", "5♦", "7♣", "6♦"], None),
}
for name, (lead, pol) in SITES.items():
    s = S.stacked(1, lead)
    r, err = engine.try_start_round(s)
    assert r, err
    S.finish_round(r, pol)
    check(r.reshuffled_mid_round, f"shoe ran dry at {name}: the failsafe fired and the round finished ({r.phase.name})")
    check(S.shoe_invariants_ok(s, r), f"   ...{name}: every card accounted for, count and order consistent")
    check([c.token for c in r.drawn[:len(lead)]] == lead[: len(r.drawn)] or len(r.drawn) < len(lead),
          f"   ...{name}: the cards already on the table were kept, in order")

s = S.stacked(1, [c.token for c in FULL])
r, _ = engine.try_start_round(s)
S.finish_round(r)
check(not r.reshuffled_mid_round and r.count_base == (r.running_count_before, r.cards_dealt_before), "a normal round never triggers it")
check(r.visible_counts() == (s.shoe.running_count, s.shoe.true_count), "at settlement the on-screen count equals the shoe's own count (normal round)")

s = S.stacked(1, ["2♣", "9♦", "3♣", "8♦", "4♥"])
r, _ = engine.try_start_round(s)
r.perform_action("hit")
r.perform_action("hit")
assert r.reshuffled_mid_round
run, tc = r.visible_counts()
seen = [c for c in r.spots[0].hands[0].cards] + [r.dealer_up]
check(run == sum(hilo(c) for c in seen) and r.count_base == (0, 0), f"visible count after a reshuffle = Hi-Lo of the cards on view ({run}), measured from zero")
check(r.running_count_before == 0 and r.cards_dealt_before == 0 and r.true_count_before == 0.0,
      "the round's original *_before figures (kept for the history log) are untouched")


# =============================================================== C. randomized: thin shoes, all policies
rng = random.Random(2026)
n_rounds = n_fired = n_bad = 0
for case in range(1500):
    decks = rng.choice([1, 1, 2, 3, 6])
    hands = rng.choice([1, 2, 3]) if decks > 1 else rng.choice([1, 2])
    policy = rng.choice(["random", "greedy", "basic"])
    s = S.thin_session(decks, rng.randint(2, 22), hands=hands, rsa=rng.random() < 0.5, split_max_hands=rng.choice([2, 4, 6]))
    s.rules.das = rng.random() < 0.5
    s.rules.double_blackjack = rng.random() < 0.3
    s.rules.dealer_buster.enabled = True
    for i in range(3):
        s.wagers[i] = 10
        s.side_bet_wagers[i]["dealer_buster"] = rng.choice([0, 10])
    for _ in range(3):
        r, err = S.play_round(s, rng, policy)
        assert r, err
        n_rounds += 1
        n_fired += r.reshuffled_mid_round
        try:
            n_bad += not S.shoe_invariants_ok(s, r)
        except Exception:
            n_bad += 1
        s.ensure_shoe_ready()
check(n_bad == 0, f"randomized: {n_rounds:,} rounds on thin shoes ({n_fired:,} hit the failsafe): no crash, no card lost or duplicated, "
                  "bookkeeping consistent, on-screen count equals the shoe's at settlement")
check(n_fired > 300, f"...and the failsafe path was exercised heavily ({n_fired})")


# =============================================================== D. prevention: the minimum cards a round needs
mc = rules_m.min_cards_to_deal
check([mc(1, 1), mc(1, 2), mc(2, 1), mc(2, 3)] == [24, 24, 15, 15], "single deck needs 24 cards whatever the hands; two decks 15")
check([mc(6, 1), mc(6, 2), mc(6, 3), mc(3, 3), mc(12, 3)] == [28, 40, 52, 52, 52], "3+ decks need 16 + 12 per hand: 28 / 40 / 52 cards for 1 / 2 / 3 hands")


def new(decks, hands=1, **kw):
    return engine.GameSession(1e6, rules_m.Rules(num_decks=decks, num_hands=hands, **kw), [10, 10, 10], None)


s = new(1)
check(s.shoe.min_cards_left == 24 and abs(s.shoe.penetration - 0.75) < 1e-9, "single deck: needs 24 cards left; the deckpen setting itself isn't rewritten")
S.burn_to(s, 24)
check(s.ensure_shoe_ready() is False, "single deck with exactly 24 left: a round CAN start")
S.burn_to(s, 23)
check(s.ensure_shoe_ready() is True, "single deck with 23 left: reshuffled before the next round")
check(abs(new(1).shoe.effective_penetration - 28 / 52) < 1e-9, "a single deck's real depth is 28/52 = 54%, whatever deckpen says")
s = new(1, penetration=0.4)
S.burn_to(s, 32)                                        # 20 dealt = 38%: short of the 0.40 cut card
check(s.ensure_shoe_ready() is False and abs(s.shoe.effective_penetration - 0.4) < 1e-9, "single deck with deckpen 0.40: the cut card (0.40) applies, not the floor")
S.burn_to(s, 31)                                        # 21 dealt = 40.4%: past it
check(s.ensure_shoe_ready() is True, "...and it's cut once that cut card is passed")

s = new(2, penetration=0.95)
check(abs(s.shoe.penetration - 0.80) < 1e-9 and s.shoe.min_cards_left == 15 and not s.has_pending_rule_changes,
      "two decks: deckpen 0.95 is capped at 0.80 (and isn't flagged as a pending change)")
check(abs(new(2, penetration=0.7).shoe.penetration - 0.70) < 1e-9, "two decks: a setting under the cap is left alone")
s = new(2, random_penetration=True)
vals = set()
for _ in range(80):
    s.reset_shoe()
    vals.add(round(s.shoe.penetration, 2))
    assert not s.has_pending_rule_changes
check(max(vals) <= 0.80 and min(vals) >= 0.65 and len(vals) > 5, f"two decks with 'deckpen rand': rolls stay within 0.65-0.80 ({min(vals)}..{max(vals)})")

# 3+ decks: the floor follows the number of hands
for hands, floor in ((1, 28), (2, 40), (3, 52)):
    s = new(6, hands)
    check(s.shoe.min_cards_left == floor, f"6 decks, {hands} hand(s): floor {floor}")
s = new(6, 3, penetration=0.95)
S.burn_to(s, 52)
check(s.ensure_shoe_ready() is False, "6 decks, 3 hands, exactly 52 left: a round can start")
S.burn_to(s, 51)
check(s.ensure_shoe_ready() is True, "...51 left: reshuffled first (deckpen 0.95 would have played on to 15)")
check(abs(new(3, 3, penetration=0.9).shoe.effective_penetration - (156 - 52) / 156) < 1e-9, "3 decks, 3 hands: the real depth is (156-52)/156, not the 0.90 asked for")
check(abs(new(6, 3).shoe.effective_penetration - 0.75) < 1e-9, "6 decks at the default deckpen: still 75% (the floor doesn't bite)")

# changing the hand count re-checks the shoe (before any wager is sized against its count)
s = new(6, 1, penetration=0.95)
S.burn_to(s, 45)                                        # fine for 1 hand (28), too short for 3 (52)
check(s.ensure_shoe_ready() is False, "6 decks, 1 hand, 45 cards left: fine")
msg = commands.handle_command("hands 3", s, round_open=True)
check("new shoe" not in msg and s.shoe.cards_remaining == 45, "'hands 3' while a round is on screen never reshuffles under it")
s.rules.num_hands = 1
msg = commands.handle_command("hands 3", s)
check("new shoe shuffled in" in msg and "3 hand(s)" in msg and s.shoe.cards_remaining == 312, f"'hands 3' with too few cards left reshuffles at once: {msg}")
msg = commands.handle_command("hands 2", s)
check(msg == "Playing 2 hand(s) per round", "...and fewer hands never does")

ui_s = new(1)
check("1 DECK  •  54%" in ui.rules_summary(ui_s), f"the header shows the real depth: {ui.rules_summary(ui_s)[:28]}")
check("2 DECK  •  80%" in ui.rules_summary(new(2, penetration=0.95)), "...80% for two decks")

# ---- hands: no lock, capped at 2 on a single deck
s = make_session = S.make_session(1, 1)
rng = random.Random(5)
ok = True
for want in [1, 2, 2, 1, 2, 1, 1, 2]:
    err = s.try_set_num_hands(want)
    r, err2 = S.play_round(s, rng, "basic")
    ok = ok and err is None and r is not None and len(r.spots) == want
    s.ensure_shoe_ready()
check(ok, "single deck: switching between 1 and 2 hands between any two rounds works, mid-shoe or not")
check(s.try_set_num_hands(3) == "Single-deck games are limited to 2 hands." and s.rules.num_hands == 2, "...3 hands is refused")
check(commands.handle_command("hands 1", s) == "Playing 1 hand(s) per round" and commands.handle_command("hands 2", s) == "Playing 2 hand(s) per round",
      "the 'hands' command has no lock message")
check(not hasattr(s, "shoe_hands") and not hasattr(s, "lock_shoe_hands"), "there is no per-shoe hand lock in the engine")
s6 = new(6, 3)
check(s6.try_set_num_hands(3) is None and s6.try_set_num_hands(1) is None, "multi-deck: any hand count, any time")

# ---- command messages
s = new(6, 3)
msg = commands.handle_command("decks 1", s)
check("24 cards" in msg and "at most 2 hands" in msg and "one split" in msg, f"'decks 1' explains: {msg[:110]}...")
check("80%" in commands.handle_command("decks 2", s), "'decks 2' mentions the 80% cap")
msg = commands.handle_command("decks 3", s)
check("16 + 12 per hand" in msg and "52 for 3 hand(s)" in msg, f"'decks 3' explains the per-hand floor: {msg[-80:]}")
s = new(1)
check("24 cards" in commands.handle_command("deckpen 0.9", s), "'deckpen 0.9' on a single deck explains the 24-card cut")
check(commands.handle_command("deckpen 0.5", s) == "Deck penetration set to 0.50 (takes effect next shuffle)", "...and says nothing when the setting is already shallower")
check("capped at 0.80" in commands.handle_command("deckpen 0.9", new(2)), "'deckpen 0.9' on two decks explains the 0.80 cap")
check("fewer than 52 cards" in commands.handle_command("deckpen 0.95", new(3, 3)), "'deckpen 0.95' on 3 decks / 3 hands explains the 52-card floor")
check(commands.handle_command("deckpen 0.75", new(6)) == "Deck penetration set to 0.75 (takes effect next shuffle)", "6 decks at 0.75: no note needed")

check.finish("check_failsafe")
