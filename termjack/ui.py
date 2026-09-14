from __future__ import annotations

import curses
from typing import List, Optional, Tuple

from . import commands, persist
from .cards import Card
from .engine import OUTCOME_LABELS, GameSession, Phase, Round, Spot, try_start_round
from .hand import Hand

CARD_H = 5
CARD_W = 7
FAN_OFFSET = 3
GUTTER = 10
SUB_HAND_SLOT = CARD_W + FAN_OFFSET  # min width for one split hand's card fan
MAX_HANDS_PER_SPOT = 4  # reserve room for 3 splits (4 hands) per spot, 12 total
SPOT_WIDTH = SUB_HAND_SLOT * MAX_HANDS_PER_SPOT
PRIMARY_WIDTH = SPOT_WIDTH // 2  # width the WAGER/BUSTER/STAR21/PP value is centered within
TABLE_WIDTH = GUTTER + 3 * SPOT_WIDTH
NUM_SPOT_COLUMNS = 3  # all three player spots are always visible/navigable, regardless of `hands`
MIN_COLS = TABLE_WIDTH + 8
MIN_LINES = 46

RETURN_KEYS = {10, 13, curses.KEY_ENTER}
ACTION_HINTS = [
    ("hit", "SPACE Hit"),
    ("stand", "RETURN Stand"),
    ("double", "D Double"),
    ("split", "P Split"),
    ("surrender", "S Surrender"),
]

# Betting-grid rows: index 0 is the main wager, 1-3 are the side bets. Wager
# and Buster share one screen row, Star21 and PP share another -- there's
# ample horizontal room, and it's a cheap way to buy back vertical space.
BET_LABELS = ["Wager", "Buster", "Star21", "PP"]
ROW_KEYS = [None, "dealer_buster", "star21", "power_poker"]

CARD_BACK = [
    "┌─────┐",
    "│▒▒▒▒▒│",
    "│▒▒▒▒▒│",
    "│▒▒▒▒▒│",
    "└─────┘",
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


def _emph_compact(text: str) -> str:
    """Tighter emphasis for split sub-hands, where slots are only
    SUB_HAND_SLOT wide -- the full '*** N ***' treatment has zero gap left
    over at that width and runs straight into the next hand's value."""
    return f"*{text}*"


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
        "┌─────┐",
        f"│{tag:<5}│",
        f"│{glyph:^5}│",
        f"│{tag:>5}│",
        "└─────┘",
    ]
    for i, line in enumerate(lines):
        _safe_addstr(win, y + i, x, line, color)


def _hand_width(hand: Hand) -> int:
    if not hand.cards:
        return CARD_W
    return CARD_W + (len(hand.cards) - 1) * FAN_OFFSET


def draw_hand(win, y: int, x: int, hand: Hand, hide_hole: bool = False, hide_last: bool = False) -> None:
    last_index = len(hand.cards) - 1
    for i, card in enumerate(hand.cards):
        face_down = (hide_hole and i == 1) or (hide_last and i == last_index)
        draw_card(win, y, x + i * FAN_OFFSET, card, face_down=face_down)


def hand_value_label(hand: Hand, hide_hole: bool = False) -> str:
    if hide_hole and len(hand.cards) >= 1:
        return str(hand.cards[0].value)

    if hand.double_hidden and hand.cards:
        # The double-down card is face down -- show the total for just the
        # original two cards, with a placeholder for the hidden one.
        visible = Hand(cards=hand.cards[:-1])
        if visible.is_blackjack:
            return "BLACKJACK"
        if visible.is_soft:
            return f"{visible.best_value - 10}/{visible.best_value} + ??"
        return f"{visible.best_value} + ??"

    if hand.is_bust:
        return f"{hand.best_value} BUST"
    if hand.is_blackjack:
        return "BLACKJACK"
    if hand.is_soft:
        # e.g. "6/16" -- shows both totals for as long as the Ace could
        # still count as either 1 or 11. Once a later card forces it down
        # to a hard total, is_soft goes False and only the single value shows.
        return f"{hand.best_value - 10}/{hand.best_value}"
    return str(hand.best_value)


def hand_status_text(hand: Hand, spot: Spot, round_: Round) -> str:
    if round_ is None:
        return ""
    if round_.phase == Phase.EARLY_SURRENDER and round_.current_prelim_spot() is spot:
        return "Early Surrender?"
    if round_.phase == Phase.INSURANCE and round_.current_prelim_spot() is spot:
        kind = round_.insurance_prompt_kind(spot)
        return "Even Money?" if kind == "even_money" else "Insurance?"
    if hand.surrendered:
        return "Surrendered"
    if hand.is_bust:
        return "BUST"
    if round_.phase == Phase.SETTLED:
        for r in round_.results:
            if r.hand is hand:
                return OUTCOME_LABELS[r.outcome]
    return ""


def money(x: float) -> str:
    return f"${x:,.2f}"


def rules_summary(session: GameSession) -> str:
    r = session.rules
    soft17 = "HITS" if r.hit_soft_17 else "STANDS"
    return (
        f"{r.num_decks} DECK  •  {r.penetration:.0%}  •  "
        f"BJ PAYS {r.blackjack_payout_label()}  •  DEALER {soft17} ON SOFT 17"
    )


def rules_detail(session: GameSession) -> str:
    r = session.rules
    das = "DAS:on" if r.das else "DAS:off"
    rsa = f"RSA:on(max{r.rsa_max_hands})" if r.rsa else "RSA:off"
    surr = f"Surr:{r.surrender}"
    table_range = f"${r.table_min:,.0f}-${r.table_max:,.0f}" if r.table_min > 0 else f"${r.table_max:,.0f} max"
    facedown = "  DblFacedown:on" if r.double_facedown else ""
    return f"{das}  {rsa}  {surr}  splitmax {r.split_max_hands}  table {table_range}{facedown}"


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


def lifetime_stats_rows(session: GameSession) -> List[Tuple[str, str]]:
    s = session.stats
    pl_d = s.lifetime_pl_dollars()
    pl_p = s.lifetime_pl_percent()
    ev = s.ev_percent()
    sign = "+" if pl_d >= 0 else ""
    return [
        ("Bankroll", money(session.bankroll)),
        ("P/L $", f"{sign}{money(pl_d)}"),
        ("P/L %", f"{pl_p:+.1f}%"),
        ("EV %", f"{ev:+.2f}%" if ev is not None else "N/A"),
        ("# Hands Played", str(s.hands_lifetime)),
        ("Player Wins", str(s.player_wins)),
        ("Dealer Wins", str(s.dealer_wins)),
        ("Pushes", str(s.pushes)),
        ("8+ Card Busts", str(s.dealer_busts_8plus)),
        ("Blazing 7's \U0001F48E", str(s.blazing_sevens)),
    ]


def session_stats_rows(session: GameSession) -> List[Tuple[str, str]]:
    s = session.stats
    shoe = session.shoe
    sign = "+" if s.session_pl >= 0 else ""
    return [
        ("Total Wagered", money(s.session_wagered)),
        ("P/L $", f"{sign}{money(s.session_pl)}"),
        ("P/L %", f"{s.session_pl_percent():+.1f}%"),
        ("# Hands Played", str(s.hands_this_session)),
        ("Player Wins", str(s.session_player_wins)),
        ("Dealer Wins", str(s.session_dealer_wins)),
        ("Pushes", str(s.session_pushes)),
        ("Doubles", str(s.doubles)),
        ("Splits", str(s.splits)),
        ("Surrenders", str(s.surrenders)),
        ("Player Blackjacks", str(s.player_blackjacks)),
        ("Dealer Blackjacks", str(s.dealer_blackjacks)),
        ("Running Count", f"{shoe.running_count:+d}"),
        ("True Count", f"{shoe.true_count:+.1f}"),
    ]


def _bet_cell_text(
    session: GameSession, round_: Optional[Round], row: int, col: int, is_focused: bool, edit_buffer: str
) -> str:
    if is_focused and edit_buffer:
        return edit_buffer
    if row == 0:
        if round_ is not None and col < len(round_.spots):
            amt = sum(h.bet for h in round_.spots[col].hands)
        else:
            amt = session.wagers[col]
    else:
        if not getattr(session.rules, ROW_KEYS[row]).enabled:
            return "off"
        if round_ is not None and col < len(round_.spots):
            amt = round_.spots[col].side_bet_wagers.get(ROW_KEYS[row], 0.0)
        else:
            amt = session.side_bet_wagers[col].get(ROW_KEYS[row], 0.0)
    return f"{amt:,.0f}"


def _draw_bet_cell(
    win,
    y: int,
    x: int,
    width: int,
    row: int,
    col: int,
    session: GameSession,
    round_: Optional[Round],
    betting: bool,
    bet_row: int,
    bet_col: int,
    bet_edit_buffer: str,
    extra_attr: int = 0,
) -> None:
    is_focused = betting and bet_row == row and bet_col == col
    text = _bet_cell_text(session, round_, row, col, is_focused, bet_edit_buffer)
    full = f"{BET_LABELS[row]}:{text}"
    attr = curses.A_REVERSE if is_focused else (curses.A_NORMAL | extra_attr)
    _safe_addstr(win, y, _center_x(full, width, x), full, attr)


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

    # ---- Header: short rules summary (top-left) + cards remaining (top-right) ----
    _safe_addstr(win, 0, 2, rules_summary(session), curses.A_BOLD)
    cards_left = f"Cards Left: {session.shoe.cards_remaining}"
    _safe_addstr(win, 0, max(2, TABLE_WIDTH - len(cards_left)), cards_left, curses.A_DIM)

    detail_line = f"{rules_detail(session)}   |   {side_bet_summary(session)}"
    _safe_addstr(win, 1, 2, detail_line, curses.A_DIM)

    # ---- DEALER: value line, then cards (no "DEALER" label to save room) ----
    hide_hole = round_ is not None and not round_.dealer_revealed
    dealer_hand = round_.dealer_hand if round_ else Hand()
    dealer_value_y = 3
    if round_:
        value_text = _emph(hand_value_label(dealer_hand, hide_hole=hide_hole))
        _safe_addstr(win, dealer_value_y, _center_x(value_text, TABLE_WIDTH), value_text, curses.A_BOLD)

    dealer_cards_y = dealer_value_y + 1
    if round_:
        dw = _hand_width(dealer_hand)
        dealer_x = max(0, (TABLE_WIDTH - dw) // 2)
        draw_hand(win, dealer_cards_y, dealer_x, dealer_hand, hide_hole=hide_hole)

    # ---- small buffer region, then PLAYER: cards, value line, status line ----
    cards_y = dealer_cards_y + CARD_H + 1
    value_y = cards_y + CARD_H
    status_y = value_y + 1
    bet_row_a_y = status_y + 1  # Wager + Buster, side by side
    bet_row_b_y = bet_row_a_y + 1  # Star21 + PP, side by side

    num_hands = session.rules.num_hands
    active = round_.current_player_hand() if round_ else None

    for i in range(NUM_SPOT_COLUMNS):
        col_x = GUTTER + i * SPOT_WIDTH
        in_play = round_ is not None and i < len(round_.spots)

        if in_play:
            spot = round_.spots[i]
            # Each hand in the spot gets its own fixed-width slot, left-anchored
            # left to right -- reserves room for the max (4 hands from 3 splits)
            # without needing to reflow as splits happen.
            for j, hand in enumerate(spot.hands):
                sub_x = col_x + j * SUB_HAND_SLOT
                is_active = active is not None and active[1] is hand
                value_attr = curses.A_REVERSE if is_active else curses.A_BOLD

                draw_hand(win, cards_y, sub_x, hand, hide_last=hand.double_hidden)
                emph = _emph if len(spot.hands) == 1 else _emph_compact
                value_text = emph(hand_value_label(hand))
                _safe_addstr(win, value_y, sub_x, value_text, value_attr)

                status = hand_status_text(hand, spot, round_)
                is_prompt = status and round_.phase in (Phase.EARLY_SURRENDER, Phase.INSURANCE)
                _safe_addstr(win, status_y, sub_x, status, curses.A_REVERSE if is_prompt else curses.A_BOLD)

        # Betting grid: always drawn for all three spots (regardless of how
        # many hands are actually in play this round) so wagers stay visible
        # and editable ahead of time; spots not in play this round are dimmed.
        dim = curses.A_DIM if i >= num_hands else 0
        _draw_bet_cell(win, bet_row_a_y, col_x, PRIMARY_WIDTH, 0, i, session, round_, betting, bet_row, bet_col, bet_edit_buffer, dim)
        _draw_bet_cell(win, bet_row_a_y, col_x + PRIMARY_WIDTH, PRIMARY_WIDTH, 1, i, session, round_, betting, bet_row, bet_col, bet_edit_buffer, dim)
        _draw_bet_cell(win, bet_row_b_y, col_x, PRIMARY_WIDTH, 2, i, session, round_, betting, bet_row, bet_col, bet_edit_buffer, dim)
        _draw_bet_cell(win, bet_row_b_y, col_x + PRIMARY_WIDTH, PRIMARY_WIDTH, 3, i, session, round_, betting, bet_row, bet_col, bet_edit_buffer, dim)

    # ---- Action hint line ----
    hint_y = bet_row_b_y + 2
    hint = ""
    if round_ is None:
        hint = "Arrows: move  |  digits: type amount  |  RETURN: confirm / deal"
    elif round_.phase == Phase.EARLY_SURRENDER:
        hint = "S Surrender    RETURN Continue"
    elif round_.phase == Phase.INSURANCE:
        hint = "SPACE Yes    RETURN No"
    elif round_.phase == Phase.PLAYER_TURN and active:
        legal = round_.legal_actions(*active)
        hint = "   ".join(label for key, label in ACTION_HINTS if key in legal)
    elif round_.phase == Phase.DEALER_TURN:
        hint = "Dealer is drawing..."
    elif round_.phase == Phase.REVEAL:
        hint = "Revealing double down card(s)..."
    elif round_.phase == Phase.SETTLED:
        hint = "[RETURN] Continue"
    _safe_addstr(win, hint_y, 2, hint, curses.A_DIM)

    # ---- Message area (up to 2 lines) ----
    msg_y = hint_y + 2
    for i, line in enumerate(message.split("\n")[:2]):
        _safe_addstr(win, msg_y + i, 2, line)

    # ---- Command input ----
    input_y = msg_y + 3
    _safe_addstr(win, input_y, 2, f"> {buffer}")

    divider_y = input_y + 2
    _, max_x = win.getmaxyx()
    _safe_addstr(win, divider_y, 0, "-" * max(max_x - 1, 0))

    # ---- Stats panel: Lifetime vs Session, side by side ----
    stats_y = divider_y + 1
    life_x = 2
    session_x = 40
    _safe_addstr(win, stats_y, life_x, "LIFETIME STATS", curses.A_BOLD | curses.A_UNDERLINE)
    _safe_addstr(win, stats_y, session_x, "SESSION STATS", curses.A_BOLD | curses.A_UNDERLINE)
    life_rows = lifetime_stats_rows(session)
    session_rows = session_stats_rows(session)
    for i, (label, value) in enumerate(life_rows):
        _safe_addstr(win, stats_y + 1 + i, life_x, f"{label:<20}{value}")
    for i, (label, value) in enumerate(session_rows):
        _safe_addstr(win, stats_y + 1 + i, session_x, f"{label:<20}{value}")

    max_rows = max(len(life_rows), len(session_rows))
    footer_y = stats_y + 1 + max_rows + 1
    _safe_addstr(win, footer_y, 2, "Type 'help' for the full command list, or 'quit' to exit.", curses.A_DIM)

    win.refresh()


def render_too_small(stdscr) -> None:
    stdscr.erase()
    lines, cols = stdscr.getmaxyx()
    msg = f"Please resize your terminal to at least {MIN_COLS}x{MIN_LINES} (currently {cols}x{lines})."
    _safe_addstr(stdscr, min(1, lines - 1), 0, msg)
    stdscr.refresh()


def render_help_screen(stdscr) -> None:
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    _safe_addstr(stdscr, 0, 2, "termjack -- Command Reference", curses.A_BOLD)
    for i, line in enumerate(commands.HELP_LINES):
        y = 2 + i
        if y >= max_y - 2:
            break
        is_header = bool(line) and not line.startswith(" ")
        _safe_addstr(stdscr, y, 2, line, curses.A_BOLD if is_header else curses.A_NORMAL)
    _safe_addstr(stdscr, max_y - 1, 2, "Press any key to return...", curses.A_DIM)
    stdscr.refresh()
    stdscr.getch()


def _blink_new_shoe(stdscr, session: GameSession, round_: Optional[Round]) -> None:
    msg = "*** NEW SHOE ***"
    x = max(2, TABLE_WIDTH - len(msg))
    for i in range(6):
        render(stdscr, session, round_, "", "")
        if i % 2 == 0:
            _safe_addstr(stdscr, 0, x, msg, curses.A_REVERSE | curses.A_BOLD)
            stdscr.refresh()
        curses.napms(220)


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
    if round_ is not None and round_.phase == Phase.REVEAL:
        render(stdscr, session, round_, "", "Revealing double down card(s)...")
        curses.napms(700)
        round_.reveal_doubles()
    if round_ is not None and round_.phase == Phase.SETTLED:
        persist.save_state(session.bankroll, session.rules, session.stats, session.wagers, session.side_bet_wagers)
        lines = round_.summary_lines()
        return "\n".join(lines) if lines else "Round complete."
    return None


def _dispatch_command(raw: str, session: GameSession, stdscr) -> str:
    if raw.strip().lower() in ("help", "?"):
        render_help_screen(stdscr)
        return ""
    return commands.handle_command(raw, session)


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

            bet_col = min(max(bet_col, 0), NUM_SPOT_COLUMNS - 1)
            if bet_row not in enabled_rows():
                bet_row = 0

            render(stdscr, session, round_, buffer, message, bet_row, bet_col, bet_edit_buffer)
            ch = stdscr.getch()

            if ch == curses.KEY_RESIZE:
                continue

            if session.pending_confirmation:
                kind = session.pending_confirmation
                session.pending_confirmation = None
                if ch in RETURN_KEYS:
                    if round_ is not None:
                        message = "Finish the current round before resetting the shoe."
                    elif kind == "newshoe":
                        session.reset_shoe()
                        _blink_new_shoe(stdscr, session, round_)
                        message = "New shoe shuffled in."
                    else:
                        session.reset_session()
                        _blink_new_shoe(stdscr, session, round_)
                        message = "New shoe shuffled in. Session stats reset."
                else:
                    message = "Cancelled."
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
                if ch == ord(" "):
                    round_.respond_insurance(True)
                elif ch in RETURN_KEYS:
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
                    bet_col = min(NUM_SPOT_COLUMNS - 1, bet_col + 1)
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
                        message = _dispatch_command(buffer, session, stdscr)
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
                        if round_.shoe_changed:
                            _blink_new_shoe(stdscr, session, round_)
                        msg = _after_engine_change(round_, session, stdscr)
                        if msg is not None:
                            message = msg
                    continue

            # Fall through: command-line editing
            if ch in RETURN_KEYS:
                if buffer.strip():
                    message = _dispatch_command(buffer, session, stdscr)
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
