from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:  # pragma: no cover
    from .engine import GameSession


class CommandError(Exception):
    pass


HELP_LINES = [
    "RULES",
    "  das on/off                    Double after split",
    "  rsa on/off [maxsplit N]       Resplit aces (max resulting hands)",
    "  bj32  /  bj65                  Blackjack pays 3:2 or 6:5",
    "  surr late/early/off            Surrender mode",
    "  h17  /  s17                    Dealer hits / stands on soft 17",
    "  decks N                        Number of decks (1-12)",
    "  deckpen 0.NN                   Deck penetration before reshuffle",
    "  splitmax N                     Max hands from splitting non-ace pairs",
    "  tablemin N  /  tablemax N      Table wager limits",
    "  double facedown on/off         Deal the double-down card face down",
    "",
    "BANKROLL",
    "  bank N                         Set bankroll to N",
    "  bank add N                     Add N to bankroll",
    "",
    "TABLE SETUP",
    "  hands 1-3                      Simultaneous hands to play",
    "",
    "SIDE BETS",
    "  powerpoker on/off [minbet N] [maxbet N]",
    "  star21 on/off [minbet N] [maxbet N]",
    "  buster on/off [minbet N] [maxbet N]",
    "",
    "SHOE / SESSION",
    "  newshoe                        Reshuffle a fresh shoe (RETURN confirms)",
    "  newsession                     Reset shoe + session stats (RETURN confirms)",
    "",
    "WAGERS",
    "  Arrow keys move around the betting grid; type digits to set an",
    "  amount for the highlighted cell; RETURN confirms it (or deals,",
    "  if nothing is pending).",
    "",
    "IN-ROUND KEYS",
    "  SPACE Hit   RETURN Stand   D Double   P Split   S Surrender",
    "  Insurance / Even Money:  SPACE Yes   RETURN No",
    "  Early Surrender:  S Surrender   RETURN Continue",
    "",
    "MISC",
    "  help | ?                       Show this screen",
    "  gamerules                      Show the full table-rules screen",
    "  quit | exit                    Quit termjack",
]

HELP_TEXT = "  |  ".join(line.strip() for line in HELP_LINES if line.strip())

_SIDEBET_LABELS = {"power_poker": "Power Poker", "star21": "Star 21", "dealer_buster": "Dealer Buster"}


def handle_command(raw: str, session: "GameSession") -> str:
    """Parse and apply a settings/betting command, returning a feedback string."""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        tokens = shlex.split(raw.lower())
    except ValueError as exc:
        return f"Could not parse command: {exc}"
    if not tokens:
        return ""

    head, rest = tokens[0], tokens[1:]
    try:
        return _dispatch(head, rest, session)
    except CommandError as exc:
        return str(exc)


def _require(rest: List[str], index: int, usage: str) -> str:
    if index >= len(rest):
        raise CommandError(f"Usage: {usage}")
    return rest[index]


def _parse_bool_on_off(token: str) -> bool:
    if token in ("on", "yes", "true"):
        return True
    if token in ("off", "no", "false"):
        return False
    raise CommandError(f"expected 'on' or 'off', got '{token}'")


def _parse_float(token: str, name: str) -> float:
    try:
        return float(token)
    except ValueError:
        raise CommandError(f"'{token}' is not a valid number for {name}")


def _parse_int(token: str, name: str) -> int:
    try:
        return int(token)
    except ValueError:
        raise CommandError(f"'{token}' is not a valid integer for {name}")


def _dispatch(head: str, rest: List[str], session: "GameSession") -> str:
    rules = session.rules

    if head == "das":
        rules.das = _parse_bool_on_off(_require(rest, 0, "das on/off"))
        return f"Double after split: {'ON' if rules.das else 'OFF'}"

    if head == "rsa":
        return _rsa_command(rest, session)

    if head == "bj" and rest and rest[0] in ("32", "65"):
        rules.blackjack_payout = 1.5 if rest[0] == "32" else 1.2
        return f"Blackjack pays {rules.blackjack_payout_label()}"

    if head in ("bj32", "bj65"):
        rules.blackjack_payout = 1.5 if head == "bj32" else 1.2
        return f"Blackjack pays {rules.blackjack_payout_label()}"

    if head == "surr":
        mode = _require(rest, 0, "surr late/early/off")
        if mode not in ("late", "early", "off"):
            raise CommandError("surr must be 'late', 'early', or 'off'")
        rules.surrender = mode
        return f"Surrender: {mode.upper()}"

    if head == "double" and rest and rest[0] == "facedown":
        rules.double_facedown = _parse_bool_on_off(_require(rest, 1, "double facedown on/off"))
        return f"Double-down card dealt face down: {'ON' if rules.double_facedown else 'OFF'}"

    if head == "h17":
        rules.hit_soft_17 = True
        return "Dealer hits soft 17 (H17)"

    if head == "s17":
        rules.hit_soft_17 = False
        return "Dealer stands on soft 17 (S17)"

    if head == "decks":
        n = _parse_int(_require(rest, 0, "decks N"), "decks")
        if not (1 <= n <= 12):
            raise CommandError("decks must be between 1 and 12")
        rules.num_decks = n
        return f"Shoe will use {n} deck(s) starting next shuffle"

    if head == "deckpen":
        p = _parse_float(_require(rest, 0, "deckpen 0.NN"), "deckpen")
        if not (0.1 <= p <= 1.0):
            raise CommandError("deckpen must be between 0.1 and 1.0")
        rules.penetration = p
        return f"Deck penetration set to {p:.2f} (takes effect next shuffle)"

    if head == "splitmax":
        n = _parse_int(_require(rest, 0, "splitmax N"), "splitmax")
        if not (1 <= n <= 8):
            raise CommandError("splitmax must be between 1 and 8")
        rules.split_max_hands = n
        return f"Max split hands (non-ace pairs): {n}"

    if head == "tablemax":
        amt = _parse_float(_require(rest, 0, "tablemax N"), "tablemax")
        if amt <= 0:
            raise CommandError("tablemax must be positive")
        if amt < rules.table_min:
            raise CommandError("tablemax cannot be below the current tablemin")
        rules.table_max = amt
        return f"Table max wager set to ${amt:,.2f}"

    if head == "tablemin":
        amt = _parse_float(_require(rest, 0, "tablemin N"), "tablemin")
        if amt < 0:
            raise CommandError("tablemin cannot be negative")
        if amt > rules.table_max:
            raise CommandError("tablemin cannot exceed the current tablemax")
        rules.table_min = amt
        return f"Table min wager set to ${amt:,.2f}"

    if head == "bank":
        if rest and rest[0] == "add":
            amt = _parse_float(_require(rest, 1, "bank add N"), "bank add")
            session.adjust_bankroll(amt)
            return f"Bankroll +${amt:,.2f} -> ${session.bankroll:,.2f}"
        amt = _parse_float(_require(rest, 0, "bank N"), "bank")
        if amt < 0:
            raise CommandError("bankroll cannot be negative")
        session.set_bankroll(amt)
        return f"Bankroll set to ${amt:,.2f}"

    if head == "hands":
        n = _parse_int(_require(rest, 0, "hands 1-3"), "hands")
        if not (1 <= n <= 3):
            raise CommandError("hands must be 1, 2, or 3")
        rules.num_hands = n
        return f"Playing {n} hand(s) per round"

    if head in ("powerpoker", "star21", "buster"):
        return _sidebet_toggle(head, rest, session)

    if head == "newshoe":
        session.pending_confirmation = "newshoe"
        return "Press RETURN to shuffle in a brand-new shoe (any other key cancels)."

    if head == "newsession":
        session.pending_confirmation = "newsession"
        return "Press RETURN to reset the shoe AND session stats (any other key cancels)."

    if head in ("help", "?"):
        return HELP_TEXT

    if head in ("quit", "exit"):
        session.request_quit()
        return "Quitting..."

    raise CommandError(f"Unknown command: '{head}' (try 'help')")


def _rsa_command(rest: List[str], session: "GameSession") -> str:
    rules = session.rules
    i = 0
    if i < len(rest) and rest[i] in ("on", "off"):
        rules.rsa = rest[i] == "on"
        i += 1
    if i < len(rest) and rest[i] == "maxsplit":
        n = _parse_int(_require(rest, i + 1, "rsa on/off maxsplit N"), "maxsplit")
        if not (2 <= n <= 8):
            raise CommandError("maxsplit must be between 2 and 8")
        rules.rsa_max_hands = n
        i += 2
    if i == 0:
        raise CommandError("Usage: rsa on/off [maxsplit N]")
    return f"Resplit aces: {'ON' if rules.rsa else 'OFF'} (max {rules.rsa_max_hands} hands)"


def _sidebet_toggle(head: str, rest: List[str], session: "GameSession") -> str:
    key = {"powerpoker": "power_poker", "star21": "star21", "buster": "dealer_buster"}[head]
    target = getattr(session.rules, key)
    label = _SIDEBET_LABELS[key]
    usage = f"Usage: {head} on/off [minbet N] [maxbet N]"

    i = 0
    if i < len(rest) and rest[i] in ("on", "off"):
        target.enabled = rest[i] == "on"
        i += 1
    while i < len(rest):
        if rest[i] == "maxbet":
            amt = _parse_float(_require(rest, i + 1, usage), "maxbet")
            if amt <= 0:
                raise CommandError("maxbet must be positive")
            target.max_bet = amt
            i += 2
        elif rest[i] == "minbet":
            amt = _parse_float(_require(rest, i + 1, usage), "minbet")
            if amt < 0:
                raise CommandError("minbet cannot be negative")
            target.min_bet = amt
            i += 2
        else:
            raise CommandError(usage)
    if i == 0:
        raise CommandError(usage)
    if target.min_bet > target.max_bet:
        raise CommandError("minbet cannot exceed maxbet")
    return (
        f"{label}: {'ON' if target.enabled else 'OFF'} "
        f"(min ${target.min_bet:,.2f}, max ${target.max_bet:,.2f})"
    )
