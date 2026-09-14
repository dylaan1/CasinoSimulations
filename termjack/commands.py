from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:  # pragma: no cover
    from .engine import GameSession


class CommandError(Exception):
    pass


HELP_TEXT = (
    "Rules: das on/off | rsa on/off | 32 bj / 65 bj | surr late/early/off | "
    "h17 | s17 | decks N | deckpen 0.NN | splitmax N  |  "
    "Bank: bank N | bank add N  |  "
    "Setup: bet N | hands 1-3  |  "
    "Side bets: powerpoker on/off maxbet N | star21 on/off maxbet N | "
    "buster on/off maxbet N | ppbet N | s21bet N | busterbet N  |  "
    "help | quit"
)

_SIDEBET_LABELS = {"power_poker": "Power Poker", "star21": "Star 21", "dealer_buster": "Dealer Buster"}
_SIDEBET_TOGGLE_NAME = {"power_poker": "powerpoker", "star21": "star21", "dealer_buster": "buster"}


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
        rules.rsa = _parse_bool_on_off(_require(rest, 0, "rsa on/off"))
        return f"Resplit aces: {'ON' if rules.rsa else 'OFF'}"

    if head in ("32", "65") and rest and rest[0] == "bj":
        rules.blackjack_payout = 1.5 if head == "32" else 1.2
        return f"Blackjack pays {rules.blackjack_payout_label()}"

    if head in ("32bj", "65bj"):
        rules.blackjack_payout = 1.5 if head == "32bj" else 1.2
        return f"Blackjack pays {rules.blackjack_payout_label()}"

    if head == "surr":
        mode = _require(rest, 0, "surr late/early/off")
        if mode not in ("late", "early", "off"):
            raise CommandError("surr must be 'late', 'early', or 'off'")
        rules.surrender = mode
        return f"Surrender: {mode.upper()}"

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
        return f"Max split hands: {n}"

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

    if head == "bet":
        amt = _parse_float(_require(rest, 0, "bet N"), "bet")
        if amt <= 0:
            raise CommandError("bet must be positive")
        rules.default_bet = amt
        return f"Base bet set to ${amt:,.2f}"

    if head == "hands":
        n = _parse_int(_require(rest, 0, "hands 1-3"), "hands")
        if not (1 <= n <= 3):
            raise CommandError("hands must be 1, 2, or 3")
        rules.num_hands = n
        return f"Playing {n} hand(s) per round"

    if head in ("powerpoker", "star21", "buster"):
        return _sidebet_toggle(head, rest, session)

    if head in ("ppbet", "s21bet", "busterbet"):
        return _sidebet_wager(head, rest, session)

    if head in ("help", "?"):
        return HELP_TEXT

    if head in ("quit", "exit"):
        session.request_quit()
        return "Quitting..."

    raise CommandError(f"Unknown command: '{head}' (try 'help')")


def _sidebet_toggle(head: str, rest: List[str], session: "GameSession") -> str:
    key = {"powerpoker": "power_poker", "star21": "star21", "buster": "dealer_buster"}[head]
    target = getattr(session.rules, key)
    label = _SIDEBET_LABELS[key]

    i = 0
    if i < len(rest) and rest[i] in ("on", "off"):
        target.enabled = rest[i] == "on"
        i += 1
    if i < len(rest) and rest[i] == "maxbet":
        amt = _parse_float(_require(rest, i + 1, f"{head} on/off maxbet N"), "maxbet")
        if amt <= 0:
            raise CommandError("maxbet must be positive")
        target.max_bet = amt
        i += 2
    if i == 0:
        raise CommandError(f"Usage: {head} on/off [maxbet N]")
    return f"{label}: {'ON' if target.enabled else 'OFF'} (max bet ${target.max_bet:,.2f})"


def _sidebet_wager(head: str, rest: List[str], session: "GameSession") -> str:
    key = {"ppbet": "power_poker", "s21bet": "star21", "busterbet": "dealer_buster"}[head]
    label = _SIDEBET_LABELS[key]
    target = getattr(session.rules, key)
    if not target.enabled:
        raise CommandError(f"{label} is not enabled (try '{_SIDEBET_TOGGLE_NAME[key]} on')")
    amt = _parse_float(_require(rest, 0, f"{head} N"), head)
    if amt < 0:
        raise CommandError("wager cannot be negative")
    if amt > target.max_bet:
        raise CommandError(f"{label} max bet is ${target.max_bet:,.2f}")
    session.side_bet_wagers[key] = amt
    return f"{label} wager set to ${amt:,.2f}"
