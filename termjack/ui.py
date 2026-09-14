from __future__ import annotations

import curses
from typing import List, Optional, Tuple

from . import commands, persist
from .cards import Card
from .engine import GameSession, Phase, Round, try_start_round
from .hand import Hand

CARD_H = 7
FAN_OFFSET = 5
SPOT_WIDTH = 34
MIN_COLS = 110
MIN_LINES = 40

RETURN_KEYS = {10, 13, curses.KEY_ENTER}
ACTION_HINTS = [
    ("hit", "SPACE Hit"),
    ("stand", "RETURN Stand"),
    ("double", "D Double"),
    ("split", "P Split"),
    ("surrender", "S Surrender"),
]

CARD_BACK = [
    "┌─────────┐",
    "│▒▒▒▒▒▒▒▒▒│",
    "│▒▒▒▒▒▒▒▒▒│",
    "│▒▒▒▒▒▒▒▒▒│",
    "│▒▒▒▒▒▒▒▒▒│",
    "│▒▒▒▒▒▒▒▒▒│",
    "└─────────┘",
]


def _safe_addstr(win, y: int, x: int, text: str, attr: int = 0) -> None:
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    available = max_x - x - 1  # curses can't write into the very last cell
    if available <= 0:
        return
    try:
        win.addstr(y, x, text[:available], attr)
    except curses.error:
        pass


def _card_color(card: Card) -> int:
    return curses.color_pair(1) if card.is_red else curses.color_pair(2)


def draw_card(win, y: int, x: int, card: Optional[Card], face_down: bool = False) -> None:
    if face_down or card is None:
        for i, line in enumerate(CARD_BACK):
            _safe_addstr(win, y + i, x, line, curses.color_pair(3))
        return

    rank = card.short_rank
    glyph = card.glyph
    tag = f"{rank}{glyph}"
    color = _card_color(card)

    lines = [
        "┌─────────┐",
        f"│{tag:<9}│",
        "│         │",
        f"│{glyph:^9}│",
        "│         │",
        f"│{tag:>9}│",
        "└─────────┘",
    ]
    for i, line in enumerate(lines):
        _safe_addstr(win, y + i, x, line, color)


def draw_hand(win, y: int, x: int, hand: Hand, hide_hole: bool = False) -> None:
    for i, card in enumerate(hand.cards):
        face_down = hide_hole and i == 1
        draw_card(win, y, x + i * FAN_OFFSET, card, face_down=face_down)


def hand_value_label(hand: Hand, hide_hole: bool = False) -> str:
    if hide_hole and len(hand.cards) >= 1:
        return str(hand.cards[0].value)
    if hand.is_bust:
        return f"{hand.best_value} BUST"
    if hand.is_blackjack:
        return "BLACKJACK"
    return str(hand.best_value)


def money(x: float) -> str:
    return f"${x:,.2f}"


def rules_summary(session: GameSession) -> str:
    r = session.rules
    das = "DAS:on" if r.das else "DAS:off"
    rsa = "RSA:on" if r.rsa else "RSA:off"
    s17 = "H17" if r.hit_soft_17 else "S17"
    surr = f"Surr:{r.surrender}"
    return (
        f"termjack  |  {r.num_decks} deck(s) @ {r.penetration:.0%} pen  |  {s17}  |  "
        f"{das}  {rsa}  |  BJ {r.blackjack_payout_label()}  |  {surr}  |  splitmax {r.split_max_hands}"
    )


def side_bet_summary(session: GameSession) -> str:
    r = session.rules
    parts = []
    for key, label in (("power_poker", "PowerPoker"), ("star21", "Star21"), ("dealer_buster", "Buster")):
        rule = getattr(r, key)
        if rule.enabled:
            wager = session.side_bet_wagers.get(key, 0.0)
            parts.append(f"{label}:${wager:,.0f}/max${rule.max_bet:,.0f}")
    return "  ".join(parts) if parts else "no side bets active"


def stats_rows(session: GameSession) -> List[Tuple[str, str]]:
    s = session.stats
    br = session.bankroll
    pl_d = s.pl_dollars(br)
    pl_p = s.pl_percent(br)
    shoe = session.shoe
    sign = "+" if pl_d >= 0 else ""
    return [
        ("Bankroll", money(br)),
        ("P/L", f"{sign}{money(pl_d)} ({pl_p:+.1f}%)"),
        ("Hands (this session)", str(s.hands_this_session)),
        ("Hands (last session)", str(s.hands_last_session)),
        ("Player wins", str(s.player_wins)),
        ("Dealer wins", str(s.dealer_wins)),
        ("Pushes", str(s.pushes)),
        ("Surrenders", str(s.surrenders)),
        ("Doubles", str(s.doubles)),
        ("Splits", str(s.splits)),
        ("Player blackjacks", str(s.player_blackjacks)),
        ("Dealer blackjacks", str(s.dealer_blackjacks)),
        ("Running count", f"{shoe.running_count:+d}"),
        ("True count", f"{shoe.true_count:+.1f}"),
    ]


def render(stdscr, session: GameSession, round_: Optional[Round], buffer: str, message: str) -> None:
    stdscr.erase()
    win = stdscr

    _safe_addstr(win, 0, 2, rules_summary(session), curses.A_BOLD)
    _safe_addstr(win, 1, 2, side_bet_summary(session), curses.A_DIM)

    # ---- Dealer ----
    hide_hole = round_ is not None and not round_.dealer_revealed
    dealer_hand = round_.dealer_hand if round_ else Hand()
    dealer_label = "Dealer"
    if round_:
        dealer_label = f"{'Dealer':<12}{hand_value_label(dealer_hand, hide_hole=hide_hole)}"
    _safe_addstr(win, 3, 2, dealer_label, curses.A_BOLD)
    if round_:
        draw_hand(win, 5, 2, dealer_hand, hide_hole=hide_hole)

    # ---- Insurance / even money / early surrender prompt ----
    prompt_y = 13
    if round_ and round_.phase == Phase.INSURANCE:
        spot = round_.current_prelim_spot()
        if spot is not None:
            kind = round_.insurance_prompt_kind(spot)
            text = "Even Money?" if kind == "even_money" else "Insurance?"
            _safe_addstr(win, prompt_y, 2, f"{text}   [RETURN] Yes    [SPACE] No", curses.A_REVERSE)
    elif round_ and round_.phase == Phase.EARLY_SURRENDER:
        _safe_addstr(
            win, prompt_y, 2,
            "Dealer shows Ace -- Early Surrender?   [S] Surrender    [RETURN] Continue",
            curses.A_REVERSE,
        )

    # ---- Player spots ----
    header_y = 15
    cards_y = 17
    wager_y = header_y + CARD_H + 3
    num_hands = session.rules.num_hands
    active = round_.current_player_hand() if round_ else None
    active_spot_index = active[0].index if active else -1

    for i in range(num_hands):
        x = 2 + i * SPOT_WIDTH
        if round_ is None or i >= len(round_.spots):
            _safe_addstr(win, header_y, x, f"Hand {i + 1}")
            continue
        spot = round_.spots[i]
        is_active_spot = spot.index == active_spot_index
        for j, hand in enumerate(spot.hands):
            # Split hands stack within (and, for 3+ splits, slightly past) the
            # spot's own column budget -- simultaneous multi-hand splitting
            # can get visually tight, which is an accepted tradeoff for a
            # simple layout.
            sub_x = x + j * 16
            label = f"Hand {i + 1}" + (f".{j + 1}" if len(spot.hands) > 1 else "")
            label = f"{label:<10}{hand_value_label(hand)}"
            attr = curses.A_REVERSE if (is_active_spot and active and active[1] is hand) else curses.A_BOLD
            _safe_addstr(win, header_y, sub_x, label, attr)
            draw_hand(win, cards_y, sub_x, hand)
            _safe_addstr(win, wager_y, sub_x, f"Wager: {money(hand.bet)}")

    # ---- Action hint line ----
    hint_y = wager_y + 2
    hint = ""
    if round_ is None:
        hint = "[RETURN] Deal"
    elif round_.phase == Phase.PLAYER_TURN and active:
        legal = round_.legal_actions(*active)
        hint = "   ".join(label for key, label in ACTION_HINTS if key in legal)
    elif round_.phase == Phase.DEALER_TURN:
        hint = "Dealer is drawing..."
    elif round_.phase == Phase.SETTLED:
        hint = "[RETURN] Continue"
    _safe_addstr(win, hint_y, 2, hint, curses.A_DIM)

    # ---- Message area (up to 3 lines) ----
    msg_y = hint_y + 2
    for i, line in enumerate(message.split("\n")[:3]):
        _safe_addstr(win, msg_y + i, 2, line)

    # ---- Command input ----
    input_y = msg_y + 4
    _safe_addstr(win, input_y, 2, f"> {buffer}")

    divider_y = input_y + 2
    _, max_x = win.getmaxyx()
    _safe_addstr(win, divider_y, 0, "-" * max(max_x - 1, 0))

    # ---- Stats panel ----
    stats_y = divider_y + 1
    _safe_addstr(win, stats_y, 2, "STATS", curses.A_BOLD)
    rows = stats_rows(session)
    col_a, col_b = rows[:7], rows[7:]
    for i, (label, value) in enumerate(col_a):
        _safe_addstr(win, stats_y + 2 + i, 2, f"{label:<24}{value}")
    for i, (label, value) in enumerate(col_b):
        _safe_addstr(win, stats_y + 2 + i, 56, f"{label:<24}{value}")

    footer_y = stats_y + 10
    _safe_addstr(win, footer_y, 2, "Type 'help' for the full command list, or 'quit' to exit.", curses.A_DIM)

    win.refresh()


def render_too_small(stdscr) -> None:
    stdscr.erase()
    lines, cols = stdscr.getmaxyx()
    msg = f"Please resize your terminal to at least {MIN_COLS}x{MIN_LINES} (currently {cols}x{lines})."
    _safe_addstr(stdscr, min(1, lines - 1), 0, msg)
    stdscr.refresh()


def init_colors() -> None:
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    curses.init_pair(1, curses.COLOR_RED, bg)
    curses.init_pair(2, curses.COLOR_WHITE, bg)
    curses.init_pair(3, curses.COLOR_BLUE, bg)


def _after_engine_change(round_: Optional[Round], session: GameSession, stdscr) -> Optional[str]:
    while round_ is not None and round_.phase == Phase.DEALER_TURN:
        render(stdscr, session, round_, "", "Dealer is drawing...")
        curses.napms(450)
        round_.step_dealer()
    if round_ is not None and round_.phase == Phase.SETTLED:
        persist.save_state(session.bankroll, session.rules, session.stats)
        lines = round_.summary_lines()
        return "\n".join(lines) if lines else "Round complete."
    return None


def _main(stdscr) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    init_colors()

    bankroll, rules, stats = persist.load_state()
    session = GameSession(bankroll, rules, stats)
    stats.hands_this_session = 0  # this run's count starts fresh; last session already captured

    round_: Optional[Round] = None
    buffer = ""
    message = "Welcome to termjack. Type 'help' for the command list."

    try:
        while not session.quit_requested:
            lines, cols = stdscr.getmaxyx()
            if lines < MIN_LINES or cols < MIN_COLS:
                render_too_small(stdscr)
                ch = stdscr.getch()
                if ch in (ord("q"), ord("Q")):
                    break
                continue

            render(stdscr, session, round_, buffer, message)
            ch = stdscr.getch()

            if ch == curses.KEY_RESIZE:
                continue

            handled = False

            if round_ is not None and round_.phase == Phase.EARLY_SURRENDER and buffer == "":
                if ch in RETURN_KEYS:
                    round_.respond_early_surrender(False)
                    handled = True
                elif ch in (ord("s"), ord("S")):
                    round_.respond_early_surrender(True)
                    handled = True
                if handled:
                    msg = _after_engine_change(round_, session, stdscr)
                    if msg is not None:
                        message = msg
                    continue

            elif round_ is not None and round_.phase == Phase.INSURANCE and buffer == "":
                if ch in RETURN_KEYS:
                    round_.respond_insurance(True)
                    handled = True
                elif ch == ord(" "):
                    round_.respond_insurance(False)
                    handled = True
                if handled:
                    msg = _after_engine_change(round_, session, stdscr)
                    if msg is not None:
                        message = msg
                    continue

            elif round_ is not None and round_.phase == Phase.PLAYER_TURN and buffer == "":
                action = None
                if ch == ord(" "):
                    action = "hit"
                elif ch in RETURN_KEYS:
                    action = "stand"
                elif ch in (ord("d"), ord("D")):
                    action = "double"
                elif ch in (ord("p"), ord("P")):
                    action = "split"
                elif ch in (ord("s"), ord("S")):
                    action = "surrender"
                if action is not None:
                    round_.perform_action(action)
                    msg = _after_engine_change(round_, session, stdscr)
                    if msg is not None:
                        message = msg
                    continue

            elif round_ is None and buffer == "" and ch in RETURN_KEYS:
                new_round, err = try_start_round(session)
                if err:
                    message = err
                else:
                    round_ = new_round
                    message = ""
                    msg = _after_engine_change(round_, session, stdscr)
                    if msg is not None:
                        message = msg
                continue

            elif round_ is not None and round_.phase == Phase.SETTLED and buffer == "" and ch in RETURN_KEYS:
                round_ = None
                message = "Ready for the next round."
                continue

            # Fall through: command-line editing
            if ch in RETURN_KEYS:
                if buffer.strip():
                    message = commands.handle_command(buffer, session)
                    buffer = ""
                    if session.quit_requested:
                        break
                continue
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                buffer = buffer[:-1]
                continue
            if ch == 27:  # ESC
                buffer = ""
                continue
            if 32 <= ch < 127 and not (ch == 32 and buffer == ""):
                buffer += chr(ch)
                continue
    finally:
        persist.save_state(session.bankroll, session.rules, session.stats)


def run() -> None:
    curses.wrapper(_main)
