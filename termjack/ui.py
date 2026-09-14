from __future__ import annotations

import curses
import sys
from typing import List, Optional, Tuple

from . import commands, persist
from .cards import Card
from .engine import OUTCOME_LABELS, SIDE_BET_LABELS, GameSession, Phase, Round, Spot, try_start_round
from .hand import Hand

CARD_H = 5
CARD_W = 7
FAN_OFFSET = 3
GUTTER = 10
SUB_HAND_SLOT = CARD_W + FAN_OFFSET  # min width for one split hand's card fan
MAX_HANDS_PER_SPOT = 4  # reserve room for 3 splits (4 hands) per spot, 12 total
SPOT_WIDTH = SUB_HAND_SLOT * MAX_HANDS_PER_SPOT
TABLE_WIDTH = GUTTER + 3 * SPOT_WIDTH
NUM_SPOT_COLUMNS = 3  # all three player spots are always visible/navigable, regardless of `hands`
MIN_COLS = max(TABLE_WIDTH + 8, 150)
CONTENT_HEIGHT = 45  # rows the full layout actually needs (see render()'s y-chain)
MIN_LINES = CONTENT_HEIGHT + 1

RETURN_KEYS = {10, 13, curses.KEY_ENTER}
ACTION_HINTS = [
    ("hit", "SPACE Hit"),
    ("stand", "RETURN Stand"),
    ("double", "D Double"),
    ("split", "P Split"),
    ("surrender", "S Surrender"),
]

# Betting-grid rows: index 0 is the main wager, 1-3 are the side bets, in the
# same left-to-right order they're drawn on screen (PP, S21, BUST).
ROW_KEYS = [None, "power_poker", "star21", "dealer_buster"]
SIDEBET_LABELS = ["PP", "S21", "BUST"]
WAGER_MAX_LEN = 8
SIDEBET_MAX_LEN = 5

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


def _display_label(label: str) -> str:
    """ALL CAPS, with a spelled-out suit folded into its glyph
    ("...Diamonds" -> "...♦"), e.g. "Suited 7-7-7 Diamonds" -> "SUITED 7-7-7♦"."""
    return label.upper().replace(" DIAMONDS", "♦")


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


def _spot_group_x(col_x: int, num_sub_hands: int) -> int:
    """Left edge for a spot's block of sub-hand slots, centered within
    SPOT_WIDTH so a single (unsplit) hand's cards/value/status line up
    with its wager cell below, rather than sitting flush against the
    spot's left edge."""
    content_width = num_sub_hands * SUB_HAND_SLOT
    return col_x + max(0, (SPOT_WIDTH - content_width) // 2)


def hand_value_label(hand: Hand, hide_hole: bool = False, resolved: bool = False) -> str:
    if hide_hole and len(hand.cards) >= 1:
        return str(hand.cards[0].value)

    if hand.double_hidden and hand.cards:
        # The double-down card is face down -- show the total for just the
        # original two cards, with a placeholder for the hidden one.
        visible = Hand(cards=hand.cards[:-1])
        if visible.is_blackjack:
            return "21"
        if visible.is_soft:
            return f"{visible.best_value - 10}/{visible.best_value} + ??"
        return f"{visible.best_value} + ??"

    if hand.is_bust:
        # No "BUST" suffix here -- the status line right below already says it.
        return str(hand.best_value)
    if hand.is_blackjack:
        return "21"
    if hand.is_soft and not resolved:
        # e.g. "6/16" -- shows both totals for as long as the Ace could
        # still count as either 1 or 11. Once the hand is done being played
        # (stood, doubled, dealer stopped drawing, ...) it collapses to the
        # single value it's actually standing on.
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
    if hand.is_blackjack:
        return "BLACKJACK"
    if round_.phase == Phase.SETTLED:
        for r in round_.results:
            if r.hand is hand:
                return OUTCOME_LABELS[r.outcome]
    return ""


def dealer_status_text(round_: Optional[Round]) -> str:
    if round_ is None or not round_.dealer_revealed:
        return ""
    if round_.dealer_has_blackjack:
        return "BLACKJACK"
    if round_.dealer_hand.is_bust:
        return "BUST"
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
        ("Star21 7-7-7♦", str(s.blazing_sevens)),
    ]


def session_stats_rows(session: GameSession) -> List[Tuple[str, str]]:
    s = session.stats
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
    ]


def _draw_wager_cell(
    win,
    y: int,
    x: int,
    width: int,
    col: int,
    session: GameSession,
    round_: Optional[Round],
    betting: bool,
    bet_row: int,
    bet_col: int,
    bet_edit_buffer: str,
    extra_attr: int = 0,
) -> None:
    is_focused = betting and bet_row == 0 and bet_col == col
    if is_focused and bet_edit_buffer:
        text = bet_edit_buffer
    elif round_ is not None and col < len(round_.spots):
        text = f"{sum(h.bet for h in round_.spots[col].hands):,.0f}"
    else:
        text = f"{session.wagers[col]:,.0f}"
    attr = curses.A_REVERSE if is_focused else extra_attr
    _safe_addstr(win, y, _center_x(text, width, x), text, attr)


def _draw_sidebet_headers(win, y: int, x: int, width: int) -> None:
    sub_w = width // 3
    for i, label in enumerate(SIDEBET_LABELS):
        _safe_addstr(win, y, _center_x(label, sub_w, x + i * sub_w), label, curses.A_DIM | curses.A_UNDERLINE)


def _draw_sidebet_amounts(
    win,
    y: int,
    x: int,
    width: int,
    col: int,
    session: GameSession,
    round_: Optional[Round],
    betting: bool,
    bet_row: int,
    bet_col: int,
    bet_edit_buffer: str,
    extra_attr: int = 0,
) -> None:
    sub_w = width // 3
    for slot, row in enumerate((1, 2, 3)):
        key = ROW_KEYS[row]
        rule = getattr(session.rules, key)
        sub_x = x + slot * sub_w
        is_focused = betting and bet_row == row and bet_col == col
        if not rule.enabled:
            # Greyed out and, per enabled_rows() in _main, simply never
            # reachable by the row scroller -- unselectable, not just styled.
            _safe_addstr(win, y, _center_x("Off", sub_w, sub_x), "Off", curses.A_DIM)
            continue
        if is_focused and bet_edit_buffer:
            text = bet_edit_buffer
        elif round_ is not None and col < len(round_.spots):
            text = f"{round_.spots[col].side_bet_wagers.get(key, 0.0):,.0f}"
        else:
            text = f"{session.side_bet_wagers[col].get(key, 0.0):,.0f}"
        attr = curses.A_REVERSE if is_focused else extra_attr
        _safe_addstr(win, y, _center_x(text, sub_w, sub_x), text, attr)


def _spot_payout_text(round_: Optional[Round], spot_index: int) -> str:
    if round_ is None or round_.phase != Phase.SETTLED:
        return ""
    total = sum(r.payout for r in round_.results if r.spot_index == spot_index)
    return f"(${total:,.2f} returned)"


def _sidebet_result_text(round_: Optional[Round], spot: Spot, key: str) -> str:
    if round_ is None:
        return ""
    wager = spot.side_bet_wagers.get(key, 0.0)
    if wager <= 0:
        return ""
    if round_.phase == Phase.SETTLED:
        display_name = SIDE_BET_LABELS[key]
        for sb in round_.side_bet_results:
            if sb.spot_index == spot.index and sb.name == display_name:
                return f"(${sb.win_amount:,.2f} returned)"
        return ""
    if key == "dealer_buster":
        return ""  # no preview -- depends on the dealer's full hand
    label = round_.side_bet_preview_label(spot, key)
    return _display_label(label) if label else ""


def _draw_result_row(win, y: int, x: int, width: int, text: str) -> None:
    if not text:
        return
    _safe_addstr(win, y, _center_x(text, width, x), text, curses.A_BOLD)


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
    max_y, max_x = win.getmaxyx()

    # Center the whole layout in whatever room the (ideally full-screen)
    # terminal actually offers, instead of pinning everything to the
    # top-left corner. x_origin only shifts the table/header area (the
    # stats panel is wider than the table and stays left-anchored so it
    # can't run off the right edge); y_origin shifts everything, which is
    # also what pushes the stats panel further down on a tall terminal.
    x_origin = max(0, (max_x - TABLE_WIDTH) // 2)
    y_origin = max(0, (max_y - CONTENT_HEIGHT) // 2)

    # ---- Header: short rules summary, centered over the table and highlighted ----
    top_line = rules_summary(session)
    _safe_addstr(win, y_origin, _center_x(top_line, TABLE_WIDTH, x_origin), top_line, curses.color_pair(4) | curses.A_BOLD)
    corner_x = x_origin + TABLE_WIDTH
    cards_left = f"Cards Left: {session.shoe.cards_remaining}"
    _safe_addstr(win, y_origin, max(x_origin + 2, corner_x - len(cards_left)), cards_left, curses.A_DIM)
    shoe = session.shoe
    counts = f"Running: {shoe.running_count:+d}   True: {shoe.true_count:+.1f}"
    _safe_addstr(win, y_origin + 1, max(x_origin + 2, corner_x - len(counts)), counts, curses.A_DIM)

    # ---- DEALER: value line, status line, then cards (no "DEALER" label) ----
    hide_hole = round_ is not None and not round_.dealer_revealed
    dealer_hand = round_.dealer_hand if round_ else Hand()
    dealer_resolved = round_ is not None and round_.dealer_revealed and round_.phase != Phase.DEALER_TURN
    dealer_value_y = y_origin + 3
    dealer_status_y = dealer_value_y + 1
    if round_:
        value_text = _emph(hand_value_label(dealer_hand, hide_hole=hide_hole, resolved=dealer_resolved))
        _safe_addstr(win, dealer_value_y, _center_x(value_text, TABLE_WIDTH, x_origin), value_text, curses.A_BOLD)
        d_status = dealer_status_text(round_)
        _safe_addstr(win, dealer_status_y, _center_x(d_status, TABLE_WIDTH, x_origin), d_status, curses.A_BOLD)

    dealer_cards_y = dealer_status_y + 1
    if round_:
        dw = _hand_width(dealer_hand)
        dealer_x = max(x_origin, x_origin + (TABLE_WIDTH - dw) // 2)
        draw_hand(win, dealer_cards_y, dealer_x, dealer_hand, hide_hole=hide_hole)

    # ---- small buffer region, then PLAYER: cards, value line, status line ----
    cards_y = dealer_cards_y + CARD_H + 1
    value_y = cards_y + CARD_H
    status_y = value_y + 1

    # ---- Per-spot wager block: main wager, side-bet header/amounts, results ----
    wager_row_y = status_y + 1
    sidebet_header_y = wager_row_y + 1
    sidebet_amount_y = sidebet_header_y + 1
    payout_row_y = sidebet_amount_y + 1
    pp_result_y = payout_row_y + 1
    s21_result_y = pp_result_y + 1
    buster_result_y = s21_result_y + 1

    num_hands = session.rules.num_hands
    active = round_.current_player_hand() if round_ else None

    for i in range(NUM_SPOT_COLUMNS):
        col_x = x_origin + GUTTER + i * SPOT_WIDTH
        in_play = round_ is not None and i < len(round_.spots)

        if in_play:
            spot = round_.spots[i]
            group_x = _spot_group_x(col_x, len(spot.hands))
            for j, hand in enumerate(spot.hands):
                sub_x = group_x + j * SUB_HAND_SLOT
                is_active = active is not None and active[1] is hand
                value_attr = curses.A_REVERSE if is_active else curses.A_BOLD

                draw_hand(win, cards_y, sub_x, hand, hide_last=hand.double_hidden)
                emph = _emph if len(spot.hands) == 1 else _emph_compact
                value_text = emph(hand_value_label(hand, resolved=hand.is_resolved))
                _safe_addstr(win, value_y, _center_x(value_text, SUB_HAND_SLOT, sub_x), value_text, value_attr)

                status = hand_status_text(hand, spot, round_)
                is_prompt = status and round_.phase in (Phase.EARLY_SURRENDER, Phase.INSURANCE)
                _safe_addstr(win, status_y, _center_x(status, SUB_HAND_SLOT, sub_x), status, curses.A_REVERSE if is_prompt else curses.A_BOLD)

        # Wager grid: always drawn for all three spots (regardless of how many
        # hands are actually in play this round) so wagers stay visible and
        # editable ahead of time; spots not in play this round are dimmed.
        dim = curses.A_DIM if i >= num_hands else 0
        _draw_wager_cell(win, wager_row_y, col_x, SPOT_WIDTH, i, session, round_, betting, bet_row, bet_col, bet_edit_buffer, dim)
        _draw_sidebet_headers(win, sidebet_header_y, col_x, SPOT_WIDTH)
        _draw_sidebet_amounts(win, sidebet_amount_y, col_x, SPOT_WIDTH, i, session, round_, betting, bet_row, bet_col, bet_edit_buffer, dim)

        if in_play:
            spot = round_.spots[i]
            _draw_result_row(win, payout_row_y, col_x, SPOT_WIDTH, _spot_payout_text(round_, i))
            _draw_result_row(win, pp_result_y, col_x, SPOT_WIDTH, _sidebet_result_text(round_, spot, "power_poker"))
            _draw_result_row(win, s21_result_y, col_x, SPOT_WIDTH, _sidebet_result_text(round_, spot, "star21"))
            _draw_result_row(win, buster_result_y, col_x, SPOT_WIDTH, _sidebet_result_text(round_, spot, "dealer_buster"))

    # ---- Action hint line ----
    hint_y = buster_result_y + 2
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
    _safe_addstr(win, hint_y, x_origin + 2, hint, curses.A_DIM)

    # ---- Message area (up to 2 lines) ----
    msg_y = hint_y + 2
    for i, line in enumerate(message.split("\n")[:2]):
        _safe_addstr(win, msg_y + i, x_origin + 2, line)

    # ---- Command input ----
    input_y = msg_y + 3
    _safe_addstr(win, input_y, x_origin + 2, f"> {buffer}")

    divider_y = input_y + 2
    _safe_addstr(win, divider_y, 0, "-" * max(max_x - 1, 0))

    # ---- Stats panel: Lifetime (2x5) and Session (2x7), side by side ----
    # Left-anchored (not shifted by x_origin) since it's wider than the
    # table itself and would otherwise risk running off the right edge.
    stats_y = divider_y + 1
    life_rows = lifetime_stats_rows(session)
    session_rows = session_stats_rows(session)
    life_a, life_b = life_rows[:5], life_rows[5:]
    sess_a, sess_b = session_rows[:6], session_rows[6:]

    life_a_x, life_b_x = 2, 38
    sess_a_x, sess_b_x = 80, 116

    _safe_addstr(win, stats_y, life_a_x, "LIFETIME STATS", curses.A_BOLD | curses.A_UNDERLINE)
    _safe_addstr(win, stats_y, sess_a_x, "SESSION STATS", curses.A_BOLD | curses.A_UNDERLINE)

    for col_x, rows in ((life_a_x, life_a), (life_b_x, life_b), (sess_a_x, sess_a), (sess_b_x, sess_b)):
        for i, (label, value) in enumerate(rows):
            _safe_addstr(win, stats_y + 1 + i, col_x, f"{label:<18}{value}")

    max_rows = max(len(life_a), len(life_b), len(sess_a), len(sess_b))
    footer_y = stats_y + 1 + max_rows + 1
    _safe_addstr(win, footer_y, 2, "Type 'help' for commands, 'gamerules' for table rules, or 'quit' to exit.", curses.A_DIM)

    win.refresh()


def render_too_small(stdscr) -> None:
    stdscr.erase()
    lines, cols = stdscr.getmaxyx()
    msg = f"termjack needs a full-screen (or at least {MIN_COLS}x{MIN_LINES}) terminal -- currently {cols}x{lines}."
    _safe_addstr(stdscr, min(1, lines - 1), 0, msg)
    stdscr.refresh()


def _render_overlay_lines(stdscr, title: str, lines: List[str]) -> None:
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    _safe_addstr(stdscr, 0, 2, title, curses.A_BOLD)
    for i, line in enumerate(lines):
        y = 2 + i
        if y >= max_y - 2:
            break
        is_header = bool(line) and not line.startswith(" ")
        _safe_addstr(stdscr, y, 2, line, curses.A_BOLD if is_header else curses.A_NORMAL)
    _safe_addstr(stdscr, max_y - 1, 2, "Press any key to return...", curses.A_DIM)
    stdscr.refresh()
    stdscr.getch()


def render_help_screen(stdscr) -> None:
    _render_overlay_lines(stdscr, "termjack -- Command Reference", commands.HELP_LINES)


def render_gamerules_screen(stdscr, session: GameSession) -> None:
    r = session.rules
    table_range = f"${r.table_min:,.0f}-${r.table_max:,.0f}" if r.table_min > 0 else f"${r.table_max:,.0f} max"
    lines = [
        "GAME RULES",
        f"  Decks:               {r.num_decks}",
        f"  Penetration:         {r.penetration:.0%}",
        f"  Blackjack pays:      {r.blackjack_payout_label()}",
        f"  Dealer Soft 17:      {'Hits' if r.hit_soft_17 else 'Stands'}",
        f"  Double After Split:  {'ON' if r.das else 'OFF'}",
        f"  Resplit Aces:        {('ON (max ' + str(r.rsa_max_hands) + ' hands)') if r.rsa else 'OFF'}",
        f"  Surrender:           {r.surrender.title()}",
        f"  Split Max Hands:     {r.split_max_hands}",
        f"  Table Limits:        {table_range}",
        f"  Double Facedown:     {'ON' if r.double_facedown else 'OFF'}",
        "",
        "SIDE BETS",
    ]
    for key, label in (("power_poker", "Power Poker"), ("star21", "Star 21"), ("dealer_buster", "Dealer Buster")):
        rule = getattr(r, key)
        state = f"ON  (min ${rule.min_bet:,.0f}, max ${rule.max_bet:,.0f})" if rule.enabled else "off"
        lines.append(f"  {label:<16} {state}")
    _render_overlay_lines(stdscr, "termjack -- Game Rules", lines)


def render_betspread_screen(stdscr, session: GameSession) -> None:
    rows = session.bet_spread.rows
    lines = [
        "BET SPREAD",
        f"  {'TRUE COUNT':<16}{'# HANDS':<12}{'WAGER / HAND':<14}",
    ]
    if not rows:
        lines.append("  (empty -- try 'betspread update +1.0 1 200')")
    else:
        for i, r in enumerate(rows):
            tc_label = f"Below {rows[1].true_count:+.1f}" if i == 0 and len(rows) > 1 else f"{r.true_count:+.1f}"
            lines.append(f"  {tc_label:<16}{r.hands:<12}{money(r.wager_per_hand):<14}")
    lines.append("")
    lines.append("  betspread update <true_count> <hands> <wager>  to add/change a row")
    _render_overlay_lines(stdscr, "termjack -- Bet Spread", lines)


def _blink_new_shoe(stdscr, session: GameSession, round_: Optional[Round]) -> None:
    msg = "*** NEW SHOE ***"
    max_y, max_x = stdscr.getmaxyx()
    x_origin = max(0, (max_x - TABLE_WIDTH) // 2)
    y_origin = max(0, (max_y - CONTENT_HEIGHT) // 2)
    x = max(x_origin + 2, x_origin + TABLE_WIDTH - len(msg))
    for i in range(6):
        render(stdscr, session, round_, "", "")
        if i % 2 == 0:
            _safe_addstr(stdscr, y_origin, x, msg, curses.A_REVERSE | curses.A_BOLD)
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
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)  # top rules line: white on blue


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
        persist.save_state(session.bankroll, session.rules, session.stats, session.wagers, session.side_bet_wagers, session.bet_spread)
        lines = round_.summary_lines()
        return "\n".join(lines) if lines else "Round complete."
    return None


def _dispatch_command(raw: str, session: GameSession, stdscr) -> str:
    stripped = raw.strip().lower()
    if stripped in ("help", "?"):
        render_help_screen(stdscr)
        return ""
    if stripped == "gamerules":
        render_gamerules_screen(stdscr, session)
        return ""
    if stripped == "betspread":
        render_betspread_screen(stdscr, session)
        return ""
    return commands.handle_command(raw, session)


def _main(stdscr) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    init_colors()

    bankroll, rules, stats, wagers, side_bet_wagers, bet_spread = persist.load_state()
    session = GameSession(bankroll, rules, stats, wagers, side_bet_wagers, bet_spread)
    session.ensure_shoe_ready()  # validate the session's very first shoe (silently -- nothing to blink about yet)

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
            if not err:
                # Funding (or clearing) a spot via the grid is, on its own,
                # enough to include (or exclude) it in the deal -- no separate
                # 'hands N' step required to actually get it dealt.
                if amount > 0:
                    session.rules.num_hands = max(session.rules.num_hands, bet_col + 1)
                elif bet_col + 1 == session.rules.num_hands:
                    shrink_to = 1
                    for j in range(bet_col - 1, -1, -1):
                        if session.wagers[j] > 0:
                            shrink_to = j + 1
                            break
                    session.rules.num_hands = shrink_to
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
                if session.ensure_shoe_ready():
                    _blink_new_shoe(stdscr, session, None)
                    message = "New shoe shuffled in. Ready for the next round."
                else:
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
                max_len = WAGER_MAX_LEN if bet_row == 0 else SIDEBET_MAX_LEN
                if ord("0") <= ch <= ord("9") and buffer == "" and len(bet_edit_buffer) < max_len:
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
        persist.save_state(session.bankroll, session.rules, session.stats, session.wagers, session.side_bet_wagers, session.bet_spread)


def run() -> None:
    try:
        # Best-effort request to maximize/fullscreen the terminal (xterm and
        # many compatible emulators honor this control sequence; unsupported
        # terminals simply ignore it). Sent before curses takes over the
        # screen so an unsupported terminal has nothing visible to leak.
        sys.stdout.write("\x1b[9;1t")
        sys.stdout.flush()
    except Exception:
        pass
    curses.wrapper(_main)
