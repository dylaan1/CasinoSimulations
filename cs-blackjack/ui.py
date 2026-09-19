from __future__ import annotations

import curses
import sys
from typing import Dict, List, Optional, Tuple

from . import commands, persist
from .cards import Card
from .engine import OUTCOME_LABELS, SIDE_BET_LABELS, GameSession, Phase, Round, Spot, try_start_round
from .hand import Hand

# ---- Card art / hand-stacking geometry ----
# Only one hand per spot is ever shown at full size (see the "active hand"
# logic below), so a hand can afford real 7x5 cards fanned with a
# horizontal overlap in a single row, up to a 12-card visual limit. A 13th+
# card (all but statistically impossible without busting first) falls back
# to a rolling ticker of compact colored rank+suit chips on the line right
# below -- a backup path, not something expected to ever actually show up
# in practice.
CARD_H = 5
CARD_W = 7
FAN_OFFSET = 3  # horizontal step between cards within the row
MAX_CARDS_IN_GRID = 12  # visual limit; cards beyond this go to the overflow ticker
CARD_ROW_WIDTH = CARD_W + FAN_OFFSET * (MAX_CARDS_IN_GRID - 1)
CARD_BLOCK_HEIGHT = CARD_H

# ---- Table geometry ----
MARGIN_COLS = 12  # ~1.0in left/right margin, assuming a typical ~8px/char terminal font at 96dpi
NUM_SPOT_COLUMNS = 3  # all three player spots are always visible/navigable, regardless of `hands`

# ---- Wager cell boxes ----
MAIN_WAGER_BOX_W = 12
SIDEBET_BOX_W = 9
SIDEBET_BOX_GAP = 2
SIDEBET_GROUP_W = SIDEBET_BOX_W * 3 + SIDEBET_BOX_GAP * 2

MIN_COL_WIDTH = max(CARD_ROW_WIDTH, SIDEBET_GROUP_W, MAIN_WAGER_BOX_W)
MIN_COLS = 2 * MARGIN_COLS + MIN_COL_WIDTH * NUM_SPOT_COLUMNS

# ---- Vertical content budget ----
# Rows, top to bottom: header(2) + blank(1) + dealer value/status(2) +
# dealer cards(CARD_BLOCK_HEIGHT) + dealer overflow-ticker row(1) +
# buffer(2) + player value row(1) + player status(1) + player cards
# (CARD_BLOCK_HEIGHT) + player overflow-ticker row(1) + main wager box(3) +
# main wager payout row(1) + side-bet titles(1) + side-bet boxes(3) +
# side-bet win/payout banner row(1) + hint/message(1) + blank(1) + input(1).
CONTENT_HEIGHT = (
    2 + 1 + 2 + CARD_BLOCK_HEIGHT + 1 + 2 + 1 + 1 + CARD_BLOCK_HEIGHT + 1 + 3 + 1 + 1 + 3 + 1
    + 1 + 1 + 1
)
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

# (true count, 1:10 spread, 1:12 spread, 1:15 spread) reference tables.
BET_SPREAD_TABLES: List[Tuple[str, List[Tuple[str, str, str, str]]]] = [
    ("$10 Minimum Table", [
        ("< +1", "$10", "$10", "$10"),
        ("+1", "$20", "$20", "$20"),
        ("+2", "$40", "$40", "$40"),
        ("+3", "$60", "$60", "$80"),
        ("+4", "$80", "$90", "$120"),
        ("+5 or higher", "$100", "$120", "$150"),
    ]),
    ("$25 Minimum Table", [
        ("< +1", "$25", "$25", "$25"),
        ("+1", "$50", "$50", "$50"),
        ("+2", "$100", "$100", "$100"),
        ("+3", "$150", "$150", "$200"),
        ("+4", "$200", "$225", "$300"),
        ("+5 or higher", "$250", "$300", "$375"),
    ]),
    ("$100 Minimum Table", [
        ("< +1", "$100", "$100", "$100"),
        ("+1", "$200", "$200", "$200"),
        ("+2", "$400", "$400", "$400"),
        ("+3", "$600", "$600", "$800"),
        ("+4", "$800", "$900", "$1200"),
        ("+5 or higher", "$1000", "$1200", "$1500"),
    ]),
]

# Side-bet paytables, mirroring the odds in sidebets.py's evaluators.
PAYOUT_TABLES: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("Power Poker", [
        ("Royal Flush", "50:1"),
        ("Straight Flush", "30:1"),
        ("Flush", "15:1"),
        ("Straight", "9:1"),
        ("Trips", "3:1"),
    ]),
    ("Star 21", [
        ("Suited 7-7-7♦", "5000:1"),
        ("Suited 7-7-7", "500:1"),
        ("Suited 6-7-8", "100:1"),
        ("Suited 21", "40:1"),
        ("Unsuited 7-7-7", "20:1"),
        ("Unsuited 6-7-8", "15:1"),
        ("Unsuited 21", "5:1"),
        ("Any 20", "3:1"),
        ("Any 19", "2:1"),
    ]),
    ("Dealer Buster", [
        ("Dealer busts on 3 cards", "2:1"),
        ("Dealer busts on 4 cards", "3:1"),
        ("Dealer busts on 5 cards", "12:1"),
        ("Dealer busts on 6 cards", "50:1"),
        ("Dealer busts on 7 cards", "100:1"),
        ("Dealer busts on 8+ cards", "250:1"),
    ]),
]

# (row, col) -> (y, x, height, width) for the currently-drawn wager cells,
# used to hit-test mouse clicks. Populated by the most recent render() call.
CellRects = Dict[Tuple[int, int], Tuple[int, int, int, int]]


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
    """Single-asterisk emphasis for a collapsed (already-completed) split
    hand's value, and for the live value of a spot that has any splits --
    distinguishes them from the '*** N ***' treatment an unsplit hand gets."""
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


def draw_hand(win, base_y: int, x: int, hand: Hand, hide_hole: bool = False, hide_last: bool = False) -> None:
    last_index = len(hand.cards) - 1
    for i, card in enumerate(hand.cards):
        if i >= MAX_CARDS_IN_GRID:
            break  # rendered separately as an overflow-ticker chip -- see _draw_overflow_chips
        face_down = (hide_hole and i == 1) or (hide_last and i == last_index)
        draw_card(win, base_y, x + i * FAN_OFFSET, card, face_down=face_down)


def _draw_overflow_chips(win, y: int, x: int, width: int, hand: Hand, hide_last: bool = False) -> None:
    """Cards past the 12-card visual limit (all but statistically
    impossible in real play without busting first -- a backup path, not
    something expected to actually appear) as a rolling ticker of compact
    colored rank+suit chips: as more cards are pulled, older ones scroll
    out of view to the left to make room, with a '+N' counter for however
    many are currently off-screen."""
    if len(hand.cards) <= MAX_CARDS_IN_GRID:
        return
    overflow = list(enumerate(hand.cards[MAX_CARDS_IN_GRID:], start=MAX_CARDS_IN_GRID))
    last_index = len(hand.cards) - 1
    chip_w = 3  # 2-char rank+suit tag, plus a 1-col gap
    max_fit = max(1, width // chip_w)
    visible = overflow[-max_fit:]
    hidden = len(overflow) - len(visible)

    cx = x
    if hidden > 0:
        marker = f"+{hidden} "
        if cx + len(marker) <= x + width:
            _safe_addstr(win, y, cx, marker, curses.A_DIM)
            cx += len(marker)
    for i, card in visible:
        tag = "??" if (hide_last and i == last_index) else f"{card.short_rank}{card.glyph}"
        if cx + len(tag) > x + width:
            break
        _safe_addstr(win, y, cx, tag, _card_color(card))
        cx += len(tag) + 1


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
    ev = s.ev_percent()
    sign_main = "+" if s.lifetime_main_pl >= 0 else ""
    sign_side = "+" if s.lifetime_sidebet_pl >= 0 else ""
    return [
        ("Main Bet P/L $", f"{sign_main}{money(s.lifetime_main_pl)}"),
        ("Side Bet P/L $", f"{sign_side}{money(s.lifetime_sidebet_pl)}"),
        ("EV %", f"{ev:+.2f}%" if ev is not None else "N/A"),
        ("# Hands Played", str(s.hands_lifetime)),
        ("Player Wins", str(s.player_wins)),
        ("Dealer Wins", str(s.dealer_wins)),
        ("Pushes", str(s.pushes)),
        ("Surrenders", str(s.surrenders_lifetime)),
        ("8+ Card Busts", str(s.dealer_busts_8plus)),
        ("Star21 7-7-7♦", str(s.blazing_sevens)),
    ]


def session_stats_rows(session: GameSession) -> List[Tuple[str, str]]:
    s = session.stats
    sign_main = "+" if s.session_main_pl >= 0 else ""
    sign_side = "+" if s.session_sidebet_pl >= 0 else ""
    return [
        ("Bankroll", money(session.bankroll)),
        ("Main Bet P/L $", f"{sign_main}{money(s.session_main_pl)}"),
        ("Side Bet P/L $", f"{sign_side}{money(s.session_sidebet_pl)}"),
        ("# Hands Played", str(s.hands_this_session)),
        ("Player Wins", str(s.session_player_wins)),
        ("Dealer Wins", str(s.session_dealer_wins)),
        ("Pushes", str(s.session_pushes)),
        ("Surrenders", str(s.surrenders)),
        ("Doubles", str(s.doubles)),
        ("Splits", str(s.splits)),
        ("Player Blackjacks", str(s.player_blackjacks)),
        ("Dealer Blackjacks", str(s.dealer_blackjacks)),
    ]


def _draw_box(win, y: int, x: int, width: int, dim: bool = False) -> None:
    attr = curses.A_DIM if dim else 0
    _safe_addstr(win, y, x, "┌" + "─" * (width - 2) + "┐", attr)
    _safe_addstr(win, y + 1, x, "│" + " " * (width - 2) + "│", attr)
    _safe_addstr(win, y + 2, x, "└" + "─" * (width - 2) + "┘", attr)


def _draw_wager_cell(
    win,
    box_y: int,
    box_x: int,
    col: int,
    session: GameSession,
    round_: Optional[Round],
    betting: bool,
    bet_row: int,
    bet_col: int,
    bet_edit_buffer: str,
    dim: bool = False,
) -> None:
    is_focused = betting and bet_row == 0 and bet_col == col
    if is_focused and bet_edit_buffer:
        text = bet_edit_buffer
    elif round_ is not None and col < len(round_.spots):
        text = f"{sum(h.bet for h in round_.spots[col].hands):,.0f}"
    else:
        text = f"{session.wagers[col]:,.0f}"
    _draw_box(win, box_y, box_x, MAIN_WAGER_BOX_W, dim=dim)
    attr = curses.A_REVERSE if is_focused else (curses.A_DIM if dim else 0)
    _safe_addstr(win, box_y + 1, _center_x(text, MAIN_WAGER_BOX_W - 2, box_x + 1), text, attr)


def _draw_sidebet_headers(win, y: int, x: int) -> None:
    for slot, label in enumerate(SIDEBET_LABELS):
        sub_x = x + slot * (SIDEBET_BOX_W + SIDEBET_BOX_GAP)
        _safe_addstr(win, y, _center_x(label, SIDEBET_BOX_W, sub_x), label, curses.A_DIM | curses.A_UNDERLINE)


def _draw_sidebet_amounts(
    win,
    box_y: int,
    x: int,
    col: int,
    session: GameSession,
    round_: Optional[Round],
    betting: bool,
    bet_row: int,
    bet_col: int,
    bet_edit_buffer: str,
    dim: bool = False,
) -> CellRects:
    rects: CellRects = {}
    for slot, row in enumerate((1, 2, 3)):
        key = ROW_KEYS[row]
        rule = getattr(session.rules, key)
        sub_x = x + slot * (SIDEBET_BOX_W + SIDEBET_BOX_GAP)
        is_focused = betting and bet_row == row and bet_col == col
        if not rule.enabled:
            # Greyed out and, per enabled_rows() in _main, simply never
            # reachable by the row scroller (or a mouse click) --
            # unselectable, not just styled.
            _draw_box(win, box_y, sub_x, SIDEBET_BOX_W, dim=True)
            _safe_addstr(win, box_y + 1, _center_x("Off", SIDEBET_BOX_W - 2, sub_x + 1), "Off", curses.A_DIM)
            continue
        if is_focused and bet_edit_buffer:
            text = bet_edit_buffer
        elif round_ is not None and col < len(round_.spots):
            text = f"{round_.spots[col].side_bet_wagers.get(key, 0.0):,.0f}"
        else:
            text = f"{session.side_bet_wagers[col].get(key, 0.0):,.0f}"
        _draw_box(win, box_y, sub_x, SIDEBET_BOX_W, dim=dim)
        attr = curses.A_REVERSE if is_focused else (curses.A_DIM if dim else 0)
        _safe_addstr(win, box_y + 1, _center_x(text, SIDEBET_BOX_W - 2, sub_x + 1), text, attr)
        rects[(row, col)] = (box_y, sub_x, 3, SIDEBET_BOX_W)
    return rects


def _spot_payout_text(round_: Optional[Round], spot_index: int) -> str:
    if round_ is None or round_.phase != Phase.SETTLED:
        return ""
    total = sum(r.payout for r in round_.results if r.spot_index == spot_index)
    return f"(${total:,.2f} returned)"


_SIDEBET_KEYS_ORDERED = ("power_poker", "star21", "dealer_buster")
_SIDEBET_SHORT_LABELS = {"power_poker": "PP", "star21": "S21"}


def _spot_sidebet_wins(round_: Round, spot: Spot) -> List[Tuple[str, float]]:
    """[(label, win_amount), ...] for this spot's side bets that actually
    won this round, in PP/S21/BUST order."""
    if round_.phase != Phase.SETTLED:
        return []
    wins: List[Tuple[str, float]] = []
    for key in _SIDEBET_KEYS_ORDERED:
        display_name = SIDE_BET_LABELS[key]
        for sb in round_.side_bet_results:
            if sb.spot_index == spot.index and sb.name == display_name and sb.win_amount > 0:
                wins.append((sb.label or display_name, sb.win_amount))
    return wins


def _sidebet_banner_flash_sequence(round_: Round, spot: Spot) -> List[str]:
    """Frames for the settlement flash animation: each winning side bet's
    label, then its payout, in turn; if more than one side bet won, a
    final frame with the combined total."""
    wins = _spot_sidebet_wins(round_, spot)
    if not wins:
        return []
    frames: List[str] = []
    for label, amount in wins:
        frames.append(_display_label(label))
        frames.append(f"${amount:,.2f} returned")
    if len(wins) > 1:
        total = sum(amount for _, amount in wins)
        frames.append(f"Side Bets Total: ${total:,.2f} returned")
    return frames


def _sidebet_preview_text(round_: Round, spot: Spot) -> str:
    """Pre-settlement preview of Power Poker / Star21 outcomes for whichever
    of those are actually wagered (Dealer Buster has no preview -- it
    depends on the dealer's full hand)."""
    parts = []
    for key, short in _SIDEBET_SHORT_LABELS.items():
        wager = spot.side_bet_wagers.get(key, 0.0)
        if wager <= 0:
            continue
        label = round_.side_bet_preview_label(spot, key)
        if label:
            parts.append(f"{short}: {_display_label(label)}")
    return "   ".join(parts)


def _sidebet_banner_default_text(round_: Optional[Round], spot: Spot) -> str:
    """What the side-bet banner shows outside of the settlement flash
    animation: the final flash frame once settled (so the result stays
    legible after the animation ends), or a live preview beforehand."""
    if round_ is None:
        return ""
    if round_.phase == Phase.SETTLED:
        seq = _sidebet_banner_flash_sequence(round_, spot)
        return seq[-1] if seq else ""
    return _sidebet_preview_text(round_, spot)


def _draw_result_row(win, y: int, x: int, width: int, text: str) -> None:
    if not text:
        return
    _safe_addstr(win, y, _center_x(text, width, x), text, curses.A_BOLD)


def _active_hand_index(spot: Spot, round_: Round) -> int:
    """Index of the one hand in this spot whose cards should currently be
    on screen: the first not-yet-finished hand (played to completion in
    order, one at a time, same as the engine's own turn order), or the
    last hand once every hand in the spot is done -- its cards then stay
    up through the dealer's turn and settlement."""
    for i, hand in enumerate(spot.hands):
        if round_.legal_actions(spot, hand):
            return i
    return len(spot.hands) - 1


def _draw_spot_value_row(
    win, y: int, col_x: int, col_width: int, spot: Spot, round_: Round, active: Optional[Tuple[Spot, Hand]]
) -> Hand:
    """Draws, left to right: a single-asterisk collapsed-value chip for
    each already-completed hand in this spot, then the '*** N ***' (or, if
    any splits happened, also single-asterisk) live value for the one hand
    whose cards are currently shown. Returns that hand."""
    active_index = _active_hand_index(spot, round_)
    parts: List[Tuple[str, int]] = []
    for i in range(active_index):
        text = _emph_compact(hand_value_label(spot.hands[i], resolved=True))
        parts.append((text, curses.A_BOLD))

    hand = spot.hands[active_index]
    emph = _emph if len(spot.hands) == 1 else _emph_compact
    is_active = active is not None and active[1] is hand
    value_text = emph(hand_value_label(hand, resolved=hand.is_resolved))
    parts.append((value_text, curses.A_REVERSE if is_active else curses.A_BOLD))

    total_width = sum(len(t) for t, _ in parts) + 2 * (len(parts) - 1)
    x = col_x + max(0, (col_width - total_width) // 2)
    for text, attr in parts:
        _safe_addstr(win, y, x, text, attr)
        x += len(text) + 2
    return hand


def render(
    stdscr,
    session: GameSession,
    round_: Optional[Round],
    buffer: str,
    message: str,
    bet_row: int = 0,
    bet_col: int = 0,
    bet_edit_buffer: str = "",
    banner_override: Optional[Dict[int, str]] = None,
) -> CellRects:
    stdscr.erase()
    win = stdscr
    betting = round_ is None
    max_y, max_x = win.getmaxyx()

    # Center the whole layout vertically in whatever room the (ideally
    # full-screen) terminal offers; horizontally, a fixed margin is used
    # instead (see MARGIN_COLS) so the table stretches to fill the space
    # between the margins rather than being pinned to a fixed width.
    left_margin = MARGIN_COLS
    usable_width = max(0, max_x - 2 * MARGIN_COLS)
    y_origin = max(0, (max_y - CONTENT_HEIGHT) // 2)
    right_edge = left_margin + usable_width
    col_width = usable_width // NUM_SPOT_COLUMNS
    col_x = [left_margin + i * col_width for i in range(NUM_SPOT_COLUMNS)]

    cell_rects: CellRects = {}

    # ---- Header: short rules summary, centered, plus corner stats ----
    y = y_origin
    top_line = rules_summary(session)
    _safe_addstr(win, y, _center_x(top_line, usable_width, left_margin), top_line, curses.color_pair(4) | curses.A_BOLD)
    cards_left = f"Cards Left: {session.shoe.cards_remaining}"
    _safe_addstr(win, y, max(left_margin, right_edge - len(cards_left)), cards_left, curses.A_DIM)
    y += 1
    shoe = session.shoe
    counts = f"Running: {shoe.running_count:+d}   True: {shoe.true_count:+.1f}"
    _safe_addstr(win, y, max(left_margin, right_edge - len(counts)), counts, curses.A_DIM)
    y += 2  # blank row

    # ---- DEALER: value line, status line, then cards (no "DEALER" label) ----
    hide_hole = round_ is not None and not round_.dealer_revealed
    dealer_hand = round_.dealer_hand if round_ else Hand()
    dealer_resolved = round_ is not None and round_.dealer_revealed and round_.phase != Phase.DEALER_TURN
    if round_:
        value_text = _emph(hand_value_label(dealer_hand, hide_hole=hide_hole, resolved=dealer_resolved))
        _safe_addstr(win, y, _center_x(value_text, usable_width, left_margin), value_text, curses.A_BOLD)
    y += 1
    if round_:
        d_status = dealer_status_text(round_)
        _safe_addstr(win, y, _center_x(d_status, usable_width, left_margin), d_status, curses.A_BOLD)
    y += 1

    dealer_cards_base_y = y
    dealer_x = left_margin + max(0, (usable_width - CARD_ROW_WIDTH) // 2)
    if round_:
        draw_hand(win, dealer_cards_base_y, dealer_x, dealer_hand, hide_hole=hide_hole)
    y += CARD_BLOCK_HEIGHT
    dealer_overflow_y = y
    if round_ and not hide_hole:
        _draw_overflow_chips(win, dealer_overflow_y, dealer_x, CARD_ROW_WIDTH, dealer_hand)
    y += 1 + 2  # dealer overflow-chip row, plus a two-row buffer before the player's area

    # ---- PLAYER: value line (collapsed split-hand chips + live value),
    # status line, then the currently-shown hand's cards ----
    value_y = y
    y += 1
    status_y = y
    y += 1
    player_cards_base_y = y
    y += CARD_BLOCK_HEIGHT
    player_overflow_y = y
    y += 1

    # ---- Per-spot wager block: main wager, its payout, side-bet
    # header/boxes, then the side-bet win/payout banner ----
    wager_box_y = y
    y += 3
    payout_row_y = y
    y += 1
    sidebet_header_y = y
    y += 1
    sidebet_box_y = y
    y += 3
    banner_row_y = y

    num_hands = session.rules.num_hands
    active = round_.current_player_hand() if round_ else None

    for i in range(NUM_SPOT_COLUMNS):
        cx = col_x[i]
        in_play = round_ is not None and i < len(round_.spots)

        if in_play:
            spot = round_.spots[i]
            shown_hand = _draw_spot_value_row(win, value_y, cx, col_width, spot, round_, active)

            status = hand_status_text(shown_hand, spot, round_)
            is_prompt = status and round_.phase in (Phase.EARLY_SURRENDER, Phase.INSURANCE)
            _safe_addstr(win, status_y, _center_x(status, col_width, cx), status, curses.A_REVERSE if is_prompt else curses.A_BOLD)

            hand_x = cx + max(0, (col_width - CARD_ROW_WIDTH) // 2)
            draw_hand(win, player_cards_base_y, hand_x, shown_hand, hide_last=shown_hand.double_hidden)
            _draw_overflow_chips(win, player_overflow_y, hand_x, CARD_ROW_WIDTH, shown_hand, hide_last=shown_hand.double_hidden)

        # Wager grid: always drawn for all three spots (regardless of how many
        # hands are actually in play this round) so wagers stay visible,
        # editable, and clickable ahead of time; spots not in play this round
        # are dimmed.
        dim = i >= num_hands
        wager_box_x = cx + max(0, (col_width - MAIN_WAGER_BOX_W) // 2)
        _draw_wager_cell(win, wager_box_y, wager_box_x, i, session, round_, betting, bet_row, bet_col, bet_edit_buffer, dim)
        cell_rects[(0, i)] = (wager_box_y, wager_box_x, 3, MAIN_WAGER_BOX_W)

        sidebet_group_x = cx + max(0, (col_width - SIDEBET_GROUP_W) // 2)
        _draw_sidebet_headers(win, sidebet_header_y, sidebet_group_x)
        sb_rects = _draw_sidebet_amounts(win, sidebet_box_y, sidebet_group_x, i, session, round_, betting, bet_row, bet_col, bet_edit_buffer, dim)
        cell_rects.update(sb_rects)

        if in_play:
            spot = round_.spots[i]
            _draw_result_row(win, payout_row_y, cx, col_width, _spot_payout_text(round_, i))
            if banner_override is not None:
                banner_text = banner_override.get(i, "")
            else:
                banner_text = _sidebet_banner_default_text(round_, spot)
            _draw_result_row(win, banner_row_y, cx, col_width, banner_text)

    # ---- Hint / message line (shows the active message in place of the
    # contextual hint when there is one) ----
    hint_y = banner_row_y + 1
    hint = ""
    if round_ is None:
        hint = "Arrows/mouse: move  |  digits: type amount  |  RETURN: confirm / deal"
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
    if message:
        _safe_addstr(win, hint_y, left_margin, message, curses.A_BOLD)
    else:
        _safe_addstr(win, hint_y, left_margin, hint, curses.A_DIM)

    # ---- Command input ----
    input_y = hint_y + 2
    _safe_addstr(win, input_y, left_margin, f"> {buffer}")

    win.refresh()
    return cell_rects


def render_too_small(stdscr) -> None:
    stdscr.erase()
    lines, cols = stdscr.getmaxyx()
    msg = f"cs-blackjack needs a full-screen (or at least {MIN_COLS}x{MIN_LINES}) terminal -- currently {cols}x{lines}."
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
    _render_overlay_lines(stdscr, "cs-blackjack -- Command Reference", commands.HELP_LINES)


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
    _render_overlay_lines(stdscr, "cs-blackjack -- Game Rules", lines)


def render_stats_screen(stdscr, session: GameSession) -> None:
    lines: List[str] = ["LIFETIME STATS"]
    for label, value in lifetime_stats_rows(session):
        lines.append(f"  {label:<18}{value}")
    lines.append("")
    lines.append("SESSION STATS")
    for label, value in session_stats_rows(session):
        lines.append(f"  {label:<18}{value}")
    _render_overlay_lines(stdscr, "cs-blackjack -- Stats", lines)


def render_payouts_screen(stdscr) -> None:
    lines: List[str] = []
    for i, (title, rows) in enumerate(PAYOUT_TABLES):
        if i:
            lines.append("")
        lines.append(title)
        for label, odds in rows:
            lines.append(f"  {label:<28}{odds}")
    _render_overlay_lines(stdscr, "cs-blackjack -- Payout Tables", lines)


def render_betspread_screen(stdscr) -> None:
    col_w = (16, 14, 14, 14)
    header = f"  {'True Count':<{col_w[0]}}{'1:10 Spread':<{col_w[1]}}{'1:12 Spread':<{col_w[2]}}{'1:15 Spread':<{col_w[3]}}"
    lines: List[str] = []
    for i, (title, rows) in enumerate(BET_SPREAD_TABLES):
        if i:
            lines.append("")
        lines.append(title)
        lines.append(header)
        for tc, a, b, c in rows:
            lines.append(f"  {tc:<{col_w[0]}}{a:<{col_w[1]}}{b:<{col_w[2]}}{c:<{col_w[3]}}")
    _render_overlay_lines(stdscr, "cs-blackjack -- Bet Spread", lines)


def _blink_new_shoe(stdscr, session: GameSession, round_: Optional[Round]) -> None:
    msg = "*** NEW SHOE ***"
    max_y, max_x = stdscr.getmaxyx()
    left_margin = MARGIN_COLS
    usable_width = max(0, max_x - 2 * MARGIN_COLS)
    y_origin = max(0, (max_y - CONTENT_HEIGHT) // 2)
    x = max(left_margin, left_margin + usable_width - len(msg))
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
        # Flash each spot's winning side bets (label, then payout, one
        # after another, ending on the combined total if more than one
        # side bet hit), 1.5s per frame; shorter sequences hold their last
        # frame while longer ones keep going. Skipped entirely if nothing
        # anywhere won, so a round with no side bets in play never pauses.
        sequences = {i: _sidebet_banner_flash_sequence(round_, spot) for i, spot in enumerate(round_.spots)}
        max_len = max((len(seq) for seq in sequences.values()), default=0)
        for step in range(max_len):
            frames = {i: (seq[min(step, len(seq) - 1)] if seq else "") for i, seq in sequences.items()}
            render(stdscr, session, round_, "", "", banner_override=frames)
            curses.napms(1500)
        persist.save_state(session.bankroll, session.rules, session.stats, session.wagers, session.side_bet_wagers)
        # No summary text needed here -- the per-spot payout/banner rows
        # already show every hand's outcome.
        return ""
    return None


def _dispatch_command(raw: str, session: GameSession, round_: Optional[Round], stdscr) -> str:
    stripped = raw.strip().lower()
    if session.pending_hard_reset:
        session.pending_hard_reset = False
        if stripped != "confirm":
            return "Hard reset cancelled."
        if round_ is not None:
            return "Finish the current round before hard-resetting."
        session.stats.reset_lifetime()
        session.reset_session()
        _blink_new_shoe(stdscr, session, None)
        return "Lifetime stats reset. New shoe shuffled in; session stats and bankroll reset."
    if stripped in ("help", "?"):
        render_help_screen(stdscr)
        return ""
    if stripped == "gamerules":
        render_gamerules_screen(stdscr, session)
        return ""
    if stripped == "betspread":
        render_betspread_screen(stdscr)
        return ""
    if stripped == "payouts":
        render_payouts_screen(stdscr)
        return ""
    if stripped == "stats":
        render_stats_screen(stdscr, session)
        return ""
    return commands.handle_command(raw, session)


def _hit_test_cell(cell_rects: CellRects, my: int, mx: int) -> Optional[Tuple[int, int]]:
    for (row, col), (y, x, h, w) in cell_rects.items():
        if y <= my < y + h and x <= mx < x + w:
            return (row, col)
    return None


def _main(stdscr) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    init_colors()
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(0)
    except curses.error:
        pass

    bankroll, rules, stats, wagers, side_bet_wagers = persist.load_state()
    session = GameSession(bankroll, rules, stats, wagers, side_bet_wagers)
    session.ensure_shoe_ready()  # validate the session's very first shoe (silently -- nothing to blink about yet)

    round_: Optional[Round] = None
    buffer = ""
    message = ""
    cell_rects: CellRects = {}

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
        message = ""
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

            cell_rects = render(stdscr, session, round_, buffer, message, bet_row, bet_col, bet_edit_buffer)
            ch = stdscr.getch()

            if ch == curses.KEY_RESIZE:
                continue

            if ch == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                clickish = bstate & (
                    curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED
                )
                if round_ is None and clickish:
                    hit = _hit_test_cell(cell_rects, my, mx)
                    if hit is not None:
                        commit_bet_cell()
                        bet_row, bet_col = hit
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
                    message = ""
                    round_.respond_early_surrender(False)
                elif ch in (ord("s"), ord("S")):
                    message = ""
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
                    message = ""
                    round_.respond_insurance(True)
                elif ch in RETURN_KEYS:
                    message = ""
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
                    message = ""
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
                    message = ""
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
                        message = _dispatch_command(buffer, session, round_, stdscr)
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
                    message = _dispatch_command(buffer, session, round_, stdscr)
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
