"""One split per hand on a single deck -- deterministic stacked-shoe tests."""
from _support import *  # noqa: F401,F403
import _support as S

check = S.Checker()


def with_filler(decks, lead, **rule_kw):
    """A session whose shoe deals `lead` first, then plenty of harmless filler cards."""
    rules = rules_m.Rules(num_decks=decks, num_hands=1, das=True, surrender="off", **rule_kw)
    s = engine.GameSession(1e9, rules, [10, 0, 0], None)
    tokens = [card(t) for t in lead]
    filler = [cards.Card(rk, st) for rk in ("2", "3", "4", "9") for st in cards.SUITS] * decks
    s.shoe._cards = list(reversed(tokens + filler))
    return s


EIGHTS = ["8♠", "5♦", "8♥", "6♣", "8♦", "8♣"]     # player 8,8 vs dealer 5; the split draws 8,8 again
ACES = ["A♠", "5♦", "A♥", "6♣", "A♦", "A♣"]       # player A,A vs dealer 5; the split draws A,A again

# ---- non-ace pairs
for decks, expect_resplit in ((1, False), (2, True), (6, True)):
    s = with_filler(decks, EIGHTS)
    r, err = engine.try_start_round(s)
    spot, hand = r.current_player_hand()
    check("split" in r.legal_actions(spot, hand), f"{decks} deck: the first split is always offered")
    assert r.perform_action("split") is None
    check(len(spot.hands) == 2 and all(h.can_split for h in spot.hands), f"{decks} deck: split into 2 hands, each now a pair of eights")
    spot, hand = r.current_player_hand()
    legal = r.legal_actions(spot, hand)
    check(("split" in legal) == expect_resplit, f"{decks} deck: a second split is {'offered' if expect_resplit else 'NOT offered'} (splitmax {s.rules.split_max_hands})")
    if not expect_resplit:
        err = r.perform_action("split")
        check(err == "Single-deck games allow one split per hand." and len(spot.hands) == 2, f"1 deck: forcing it is refused with an explanation: {err}")
    check(s.rules.split_max_hands == 4, f"{decks} deck: the splitmax RULE itself is untouched (4)")

s = with_filler(1, EIGHTS, split_max_hands=1)
r, _ = engine.try_start_round(s)
spot, hand = r.current_player_hand()
check("split" not in r.legal_actions(spot, hand), "1 deck with splitmax 1: no splitting at all")
check(r.perform_action("split") == "Max split hands reached (splitmax 1).", "...and the message is the ordinary splitmax one")

# ---- aces (their resplit has its own limit)
for decks, rsa_max, expect_resplit in ((1, 4, False), (2, 4, True), (1, 2, False)):
    s = with_filler(decks, ACES, rsa=True, rsa_max_hands=rsa_max)
    r, _ = engine.try_start_round(s)
    spot, hand = r.current_player_hand()
    assert "split" in r.legal_actions(spot, hand)
    assert r.perform_action("split") is None
    cur = r.current_player_hand()
    offered = cur is not None and "split" in r.legal_actions(*cur)
    check(offered == expect_resplit, f"{decks} deck, RSA on (max {rsa_max}): resplitting aces {'offered' if expect_resplit else 'not offered'}")
    check(all(h.is_split_aces for h in spot.hands) and len(spot.hands) == 2, "   (aces were split once, as normal)")

# ---- the cap follows the LIVE shoe, not the queued-up 'decks' rule
s = with_filler(6, EIGHTS)
check(s.split_hand_limit() == 4 and s.rsa_hand_limit() == 4, "6-deck shoe: limits are the rules' own (4 / 4)")
commands.handle_command("decks 1", s)
check(s.split_hand_limit() == 4, "'decks 1' queued for the next shuffle: the live 6-deck shoe still splits up to 4")
s.reset_shoe()
check(s.shoe.num_decks == 1 and s.split_hand_limit() == 2 and s.rsa_hand_limit() == 2, "after the shuffle: single deck -> 2 / 2")
check(s.rules.split_max_hands == 4 and s.rules.rsa_max_hands == 4, "...with the saved rules untouched")
commands.handle_command("decks 6", s)
s.reset_shoe()
check(s.split_hand_limit() == 4 and s.rsa_hand_limit() == 4, "back on 6 decks the player's own splitmax applies again")

# ---- command messages
s = with_filler(1, EIGHTS)
msg = commands.handle_command("splitmax 8", s)
check("one split per hand" in msg and "2 applies" in msg, f"'splitmax 8' on a single deck says what actually applies: {msg}")
check(commands.handle_command("splitmax 2", s) == "Max split hands (non-ace pairs): 2", "'splitmax 2' needs no caveat")
check("aces can't be resplit" in commands.handle_command("rsa on maxsplit 4", s), "'rsa on maxsplit 4' on a single deck says aces won't resplit")
check(commands.handle_command("splitmax 8", with_filler(6, EIGHTS)) == "Max split hands (non-ace pairs): 8", "multi-deck 'splitmax' message unchanged")
check("one split per hand" in commands.handle_command("decks 1", with_filler(6, EIGHTS)), "'decks 1' announces the split limit too")

check.finish("check_split_cap")
