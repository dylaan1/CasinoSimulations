from __future__ import annotations

import curses
from typing import List, Optional, Tuple

from . import commands, persist
from .cards import Card
from .engine import OUTCOME_LABELS, GameSession, Phase, Round, try_start_round
from .hand import Hand

CARD_H = 7
CARD_W = 11
FAN_OFFSET = 5
GUTTER = 16
SUB_HAND_SLOT = CARD_W + FAN_OFFSET  # min width for one split hand's card fan
MAX_HANDS_PER_SPOT = 4  # reserve room for 3 splits (4 hands) per spot, 12 total
SPOT_WIDTH = SUB_HAND_SLOT * MAX_HANDS_PER_SPOT
PRIMARY_WIDTH = 32  # width the WAGER/BUSTER/STAR21/PP value is centered within
TABLE_WIDTH = GUTTER + 3 * SPOT_WIDTH
MIN_COLS = TABLE_WIDTH + 8
MIN_LINES = 58

RETURN_KEYS = {10, 13, curses.KEY_ENTER}
ACTION_HINTS = [
    ("hit", "SPACE Hit"),
    ("stand", "RETURN Stand"),
    ("double", "D Double"),
    ("split", "P Split"),
    ("surrender", "S Surrender"),
]

# Betting-grid rows: index 0 is the main wager, 1-3 are the side bets.
ROW_LABELS = ["WAGER:", "BUSTER:", "STAR 21:", "PP:"]
ROW_KEYS = [None, "dealer_buster", "star21", "power_poker"]

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


def _center_x(text: str, width: int, origin: int = 0) -> int:
    return origin + max(0, (width - len(text)) // 2)


def _emph(text: str) -> str:
    return f"*** {text} ***"


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


def _hand_width(hand: Hand) -> int:
    if not hand.cards:
        return CARD_W
    return CARD_W + (len(hand.cards) - 1) * FAN_OFFSET


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


def hand_status_text(hand: Hand, round_: Round) -> str:
    if hand.is_bust:
        return "BUST"
    if round_.phase == Phase.SETTLED:
        for r in round_.results:
            if r.hand is hand:
                return OUTCOME_LABELS[r.outcome]
    if hand.surrendered:
        return "SURR"
    return ""


def money(x: float) -> str:
    return f"${x:,.2f}"


def rules_summary(session: GameSession) -> str:
    r = session.rules
    das = "DAS:on" if r.das else "DAS:off"
    rsa = f"RSA:on(max{r.rsa_max_hands})" if r.rsa else "RSA:off"
    s17 = "H17" if r.hit_soft_17 else "S17"
    surr = f"Surr:{r.surrender}"
    table_range = f"${r.table_min:,.0f}-${r.table_max:,.0f}" if r.table_min > 0 else f"${r.table_max:,.0f} max"
    return (
        f"termjack  |  {r.num_decks} deck(s) @ {r.penetration:.0%} pen  |  {s17}  |  "
        f"{das}  {rsa}  |  BJ {r.blackjack_payout_label()}  |  {surr}  |  "
        f"splitmax {r.split_max_hands}  |  table {table_range}"
    )


def side_bet_summary(session: GameSession) -> str:
    r = session.rules
    parts = []
    for key, label in (("power_poker", "PowerPoker"), ("star21", "Star21"), ("dealer_buster", "Buster")):
        rule = getattr(r, key)
        if rule.enabled:
            state = f"ON ${rule.min_bet:,.0f}-${rule.max_bet:,.0f}" if rule.min_bet > 0 else f"ON max${rule.max_bet:,.0f}"
        else:
            state = "off"
        parts.append(f"{label}:{state}")
    return "  ".join(parts)


def stats_columns(session: GameSession) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    s = session.stats
    br = session.bankroll
    pl_d = s.lifetime_pl_dollars()
    pl_p = s.lifetime_pl_percent()
    ev = s.ev_percent()
    shoe = session.shoe
    sign = "+" if pl_d >= 0 else ""

    col_a = [
        ("Bankroll", money(br)),
        ("P/L $ (lifetime)", f"{sign}{money(pl_d)}"),
        ("P/L % (lifetime)", f"{pl_p:+.1f}%"),
        ("EV%", f"{ev:+.2f}%" if ev is not None else "N/A"),
        ("Hands (lifetime)", str(s.hands_lifetime)),
        ("Player wins", str(s.player_wins)),
        ("Dealer wins", str(s.dealer_wins)),
        ("Pushes", str(s.pushes)),
    ]
    col_b = [
        ("Hands (this session)", str(s.hands_this_session)),
        ("Surrenders", str(s.surrenders)),
        ("Doubles", str(s.doubles)),
        ("Splits", str(s.splits)),
        ("Player blackjacks", str(s.player_blackjacks)),
        ("Dealer blackjacks", str(s.dealer_blackjacks)),
        ("Remaining cards", str(shoe.cards_remaining)),
        ("Running count", f"{shoe.running_count:+d}"),
        ("True count", f"{shoe.true_count:+.1f}"),
    ]
    return col_a, col_b


def _bet_cell_text(session: GameSession, row: int, col: int, is_focused: bool, edit_buffer: str) -> str:
    if is_focused and edit_buffer:
        return edit_buffer
    if row == 0:
        amt = session.wagers[col]
    else:
        amt = session.side_bet_wagers[col].get(ROW_KEYS[row], 0.0)
        if not getattr(session.rules, ROW_KEYS[row]).enabled:
            return "off"
    return f"{amt:,.0f}"


def render(
    stdscr,
    session: GameSession,
    round_: Optional[Round],
    buffer: str,
    message: str,
    bet_row: int = 0,
    bet_col: int = 0,
    bet_edit_buffer: str = "",
) -> None:
    stdscr.erase()
    win = stdscr
    betting = round_ is None

    _safe_addstr(win, 0, 2, rules_summary(session), curses.A_BOLD)
    _safe_addstr(win, 1, 2, side_bet_summary(session), curses.A_DIM)

    # ---- DEALER ----
    _safe_addstr(win, 3, _center_x("DEALER", TABLE_WIDTH), "DEALER", curses.A_BOLD)

    hide_hole = round_ is not None and not round_.dealer_revealed
    dealer_hand = round_.dealer_hand if round_ else Hand()
    if round_:
        value_text = _emph(hand_value_label(dealer_hand, hide_hole=hide_hole))
        _safe_addstr(win, 5, _center_x(value_text, TABLE_WIDTH), value_text, curses.A_BOLD)
        dw = _hand_width(dealer_hand)
        dealer_x = max(0, (TABLE_WIDTH - dw) // 2)
        draw_hand(win, 7, dealer_x, dealer_hand, hide_hole=hide_hole)

    # ---- Insurance / even money / early surrender prompt ----
    prompt_y = 14
    if round_ and round_.phase == Phase.INSURANCE:
        spot = round_.current_prelim_spot()
        if spot is not None:
            kind = round_.insurance_prompt_kind(spot)
            text = "Even Money?" if kind == "even_money" else "Insurance?"
            line = f"Hand {spot.index + 1}: {text}   [RETURN] Yes    [SPACE] No"
            _safe_addstr(win, prompt_y, _center_x(line, TABLE_WIDTH), line, curses.A_REVERSE)
    elif round_ and round_.phase == Phase.EARLY_SURRENDER:
        spot = round_.current_prelim_spot()
        idx = spot.index + 1 if spot else "?"
        line = f"Hand {idx}: Early Surrender?   [S] Surrender    [RETURN] Continue"
        _safe_addstr(win, prompt_y, _center_x(line, TABLE_WIDTH), line, curses.A_REVERSE)

    # ---- Per-hand WIN/LOSE/BUST status row ----
    status_y = 16
    cards_y = 18
    value_y = cards_y + CARD_H + 1
    wager_y = value_y + 1
    buster_y = wager_y + 1
    star21_y = buster_y + 1
    pp_y = star21_y + 1

    num_hands = session.rules.num_hands
    active = round_.current_player_hand() if round_ else None

    for i in range(num_hands):
        col_x = GUTTER + i * SPOT_WIDTH

        if round_ is None or i >= len(round_.spots):
            continue

        spot = round_.spots[i]
        # Each hand in the spot gets its own fixed-width slot, left-anchored
        # left to right -- reserves room for the max (4 hands from 3 splits)
        # without needing to reflow as splits happen, and without spreading
        # the common 1-hand case out to fill the whole reserved width.
        for j, hand in enumerate(spot.hands):
            sub_x = col_x + j * SUB_HAND_SLOT
            is_active = active is not None and active[1] is hand
            value_attr = curses.A_REVERSE if is_active else curses.A_BOLD

            status = hand_status_text(hand, round_) if round_ else ""
            _safe_addstr(win, status_y, sub_x, status, curses.A_BOLD)
            draw_hand(win, cards_y, sub_x, hand)
            value_text = _emph(hand_value_label(hand))
            _safe_addstr(win, value_y, sub_x, value_text, value_attr)

        # Betting grid rows (WAGER / BUSTER / STAR 21 / PP) -- one value per
        # spot, centered in a fixed zone regardless of how many hands it's
        # split into.
        for row in range(4):
            y = [wager_y, buster_y, star21_y, pp_y][row]
            is_focused = betting and bet_row == row and bet_col == i
            text = _bet_cell_text(session, row, i, is_focused, bet_edit_buffer)
            attr = curses.A_REVERSE if is_focused else curses.A_NORMAL
            _safe_addstr(win, y, _center_x(text, PRIMARY_WIDTH, col_x), text, attr)

    for row in range(4):
        y = [wager_y, buster_y, star21_y, pp_y][row]
        _safe_addstr(win, y, 0, ROW_LABELS[row], curses.A_DIM)

    player_y = pp_y + 2
    _safe_addstr(win, player_y, _center_x("PLAYER", TABLE_WIDTH), "PLAYER", curses.A_BOLD)

    # ---- Action hint line ----
    hint_y = player_y + 2
    hint = ""
    if round_ is None:
        hint = "Arrows: move  |  digits: type amount  |  RETURN: confirm / deal"
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
    col_a, col_b = stats_columns(session)
    for i, (label, value) in enumerate(col_a):
        _safe_addstr(win, stats_y + 2 + i, 2, f"{label:<24}{value}")
    for i, (label, value) in enumerate(col_b):
        _safe_addstr(win, stats_y + 2 + i, 56, f"{label:<24}{value}")

    footer_y = stats_y + 12
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
        persist.save_state(session.bankroll, session.rules, session.stats, session.wagers, session.side_bet_wagers)
        lines = round_.summary_lines()
        return "\n".join(lines) if lines else "Round complete."
    return None


def _main(stdscr) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    init_colors()

    bankroll, rules, stats, wagers, side_bet_wagers = persist.load_state()
    session = GameSession(bankroll, rules, stats, wagers, side_bet_wagers)

    round_: Optional[Round] = None
    buffer = ""
    message = "Welcome to termjack. Type 'help' for the command list."

    bet_row = 0
    bet_col = 0
    bet_edit_buffer = ""

    def enabled_rows() -> List[int]:
        rows = [0]
        for i in range(1, 4):
            if getattr(session.rules, ROW_KEYS[i]).enabled:
                rows.append(i)
        return rows

    def commit_bet_cell() -> None:
        nonlocal bet_edit_buffer, message
        if not bet_edit_buffer:
            return
        amount = float(bet_edit_buffer)
        if bet_row == 0:
            err = session.try_set_wager(bet_col, amount)
        else:
            err = session.try_set_side_bet_wager(bet_col, ROW_KEYS[bet_row], amount)
        if err:
            message = err
        bet_edit_buffer = ""

    try:
        while not session.quit_requested:
            lines, cols = stdscr.getmaxyx()
            if lines < MIN_LINES or cols < MIN_COLS:
                render_too_small(stdscr)
                ch = stdscr.getch()
                if ch in (ord("q"), ord("Q")):
                    break
                continue

            bet_col = min(bet_col, session.rules.num_hands - 1)
            if bet_row not in enabled_rows():
                bet_row = 0

            render(stdscr, session, round_, buffer, message, bet_row, bet_col, bet_edit_buffer)
            ch = stdscr.getch()

            if ch == curses.KEY_RESIZE:
                continue

            if round_ is not None and round_.phase == Phase.EARLY_SURRENDER and buffer == "":
                handled = True
                if ch in RETURN_KEYS:
                    round_.respond_early_surrender(False)
                elif ch in (ord("s"), ord("S")):
                    round_.respond_early_surrender(True)
                else:
                    handled = False
                if handled:
                    msg = _after_engine_change(round_, session, stdscr)
                    if msg is not None:
                        message = msg
                    continue

            elif round_ is not None and round_.phase == Phase.INSURANCE and buffer == "":
                handled = True
                if ch in RETURN_KEYS:
                    round_.respond_insurance(True)
                elif ch == ord(" "):
                    round_.respond_insurance(False)
                else:
                    handled = False
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
                    err = round_.perform_action(action)
                    if err:
                        message = err
                    else:
                        msg = _after_engine_change(round_, session, stdscr)
                        if msg is not None:
                            message = msg
                    continue

            elif round_ is not None and round_.phase == Phase.SETTLED and buffer == "" and ch in RETURN_KEYS:
                round_ = None
                message = "Ready for the next round."
                continue

            elif round_ is None:
                if ch == curses.KEY_LEFT:
                    commit_bet_cell()
                    bet_col = max(0, bet_col - 1)
                    continue
                if ch == curses.KEY_RIGHT:
                    commit_bet_cell()
                    bet_col = min(session.rules.num_hands - 1, bet_col + 1)
                    continue
                if ch == curses.KEY_UP:
                    commit_bet_cell()
                    rows = enabled_rows()
                    idx = rows.index(bet_row) if bet_row in rows else 0
                    bet_row = rows[max(0, idx - 1)]
                    continue
                if ch == curses.KEY_DOWN:
                    commit_bet_cell()
                    rows = enabled_rows()
                    idx = rows.index(bet_row) if bet_row in rows else 0
                    bet_row = rows[min(len(rows) - 1, idx + 1)]
                    continue
                if ord("0") <= ch <= ord("9") and buffer == "" and len(bet_edit_buffer) < 7:
                    bet_edit_buffer += chr(ch)
                    continue
                if ch in (curses.KEY_BACKSPACE, 127, 8) and bet_edit_buffer:
                    bet_edit_buffer = bet_edit_buffer[:-1]
                    continue
                if ch in RETURN_KEYS:
                    if bet_edit_buffer:
                        commit_bet_cell()
                        continue
                    if buffer.strip():
                        message = commands.handle_command(buffer, session)
                        buffer = ""
                        if session.quit_requested:
                            break
                        continue
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
                bet_edit_buffer = ""
                continue
            if 32 <= ch < 127 and not (ch == 32 and buffer == ""):
                buffer += chr(ch)
                continue
    finally:
        persist.save_state(session.bankroll, session.rules, session.stats, session.wagers, session.side_bet_wagers)


def run() -> None:
    curses.wrapper(_main)
