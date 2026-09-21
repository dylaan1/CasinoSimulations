from __future__ import annotations

import curses
import sys
import time
from typing import Dict, List, Optional, Tuple, Union

from . import commands, persist
from .cards import Card
from .engine import (
    OUTCOME_LABELS,
    SIDE_BET_LABELS,
    SPOT_SCREEN_ORDER,
    GameSession,
    Phase,
    Round,
    Spot,
    initial_deal_sequence,
    try_start_round,
)
from .hand import Hand
from .sidebets import side_bet_allowed

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
MARGIN_COLS = 6  # ~0.5in left/right margin, assuming a typical ~8px/char terminal font at 96dpi
NUM_SPOT_COLUMNS = 3  # all three player spots are always visible/navigable, regardless of `hands`
DIVIDER_COLS = NUM_SPOT_COLUMNS - 1  # one reserved column per gap, for the ♦ divider between spots

# SPOT_SCREEN_ORDER (spot index -> its on-screen column slot) now lives in
# engine.py, imported above -- it's also the basis of the dealing/play/
# prelim-prompt order there, not just this module's own screen layout.

# ---- Wager cell boxes ----
MAIN_WAGER_BOX_W = 12
SIDEBET_BOX_W = 13  # fits "Power Poker" (11 chars), the longest side-bet title, exactly
SIDEBET_BOX_GAP = 2
SIDEBET_GROUP_W = SIDEBET_BOX_W * 3 + SIDEBET_BOX_GAP * 2

MIN_COL_WIDTH = max(CARD_ROW_WIDTH, SIDEBET_GROUP_W, MAIN_WAGER_BOX_W)

# ---- Stats panel ----
STATS_SESSION_ROWS = 6  # per sub-column (2 sub-columns)
STATS_LIFETIME_ROWS = 6  # per sub-column (2 sub-columns)
STATS_MAX_ROWS = max(STATS_SESSION_ROWS, STATS_LIFETIME_ROWS)

# Side-bet paytables, mirroring the odds in sidebets.py's evaluators --
# shown inline in the stats bar (see PAYOUT_COL_W etc. below). Titled with
# the compact (no-space) form of each bet's name -- these run narrower
# than the wager-cell boxes, which use SIDEBET_LABELS below instead.
#
# Star21 and Buster each have a deck-count-dependent variant (see
# payout_tables_for() below): Star21 swaps to its own double-deck-only
# table at exactly 2 decks in the live shoe, and Buster's 8+ card row pays
# 500:1 instead of 250:1 at exactly 1 deck.
POWER_POKER_PAYOUTS: List[Tuple[str, str]] = [
    ("Royal Flush", "50:1"),
    ("Straight Flush", "40:1"),
    ("Trips", "25:1"),
    ("Straight", "10:1"),
    ("Flush", "3:1"),
]
STAR21_STANDARD_PAYOUTS: List[Tuple[str, str]] = [
    ("Suited 7-7-7♦", "5000:1"),
    ("Suited 7-7-7", "500:1"),
    ("Suited 6-7-8", "100:1"),
    ("Unsuited 7-7-7", "50:1"),
    ("Suited 21", "30:1"),
    ("Unsuited 6-7-8", "20:1"),
    ("Unsuited 21", "8:1"),
    ("Any 20", "4:1"),
    ("Any 19", "3:1"),
]
STAR21_DOUBLE_DECK_PAYOUTS: List[Tuple[str, str]] = [
    ("Suited 6-7-8", "500:1"),
    ("Suited 21", "50:1"),
    ("Unsuited 6-7-8", "40:1"),
    ("Unsuited 21", "10:1"),
    ("Any 20", "4:1"),
    ("Any 19", "3:1"),
]
BUSTER_PAYOUTS: List[Tuple[str, str]] = [
    ("8+ card bust", "250:1"),
    ("7 card bust", "100:1"),
    ("6 card bust", "50:1"),
    ("5 card bust", "12:1"),
    ("4 card bust", "3:1"),
    ("3 card bust", "2:1"),
]
BUSTER_PAYOUTS_SINGLE_DECK: List[Tuple[str, str]] = [
    ("8+ card bust", "500:1"),
    ("7 card bust", "100:1"),
    ("6 card bust", "50:1"),
    ("5 card bust", "12:1"),
    ("4 card bust", "3:1"),
    ("3 card bust", "2:1"),
]


def payout_tables_for(num_decks: int) -> List[Tuple[str, List[Tuple[str, str]]]]:
    star21_title = "Star21 (2-Deck)" if num_decks == 2 else "Star21"
    star21_rows = STAR21_DOUBLE_DECK_PAYOUTS if num_decks == 2 else STAR21_STANDARD_PAYOUTS
    buster_rows = BUSTER_PAYOUTS_SINGLE_DECK if num_decks == 1 else BUSTER_PAYOUTS
    return [
        ("PowerPoker", POWER_POKER_PAYOUTS),
        (star21_title, star21_rows),
        ("Buster", buster_rows),
    ]


PAYOUT_COL_W = 23  # label + right-aligned odds, per mini table
PAYOUT_GAP = 2
# The worst case across every deck-count variant -- fixed at import time so
# the layout's vertical budget (CONTENT_HEIGHT/MIN_LINES below) never shifts
# at runtime just because the player changed the deck count.
PAYOUT_MAX_ROWS = max(
    len(POWER_POKER_PAYOUTS),
    len(STAR21_STANDARD_PAYOUTS),
    len(STAR21_DOUBLE_DECK_PAYOUTS),
    len(BUSTER_PAYOUTS),
    len(BUSTER_PAYOUTS_SINGLE_DECK),
)
STATS_BLOCK_ROWS = max(STATS_MAX_ROWS, PAYOUT_MAX_ROWS)  # shared row budget for the two side-by-side blocks

# The payout tables + session/lifetime stats row needs its own width floor,
# independent of the per-spot-column floor above -- it's what actually goes
# illegible first on a narrow terminal (labels/values get hard-clipped, not
# overlapped, but truncate into gibberish well before the card/wager rows
# would ever collide).
STATS_MIN_COL_W = 25  # per stats sub-column (4 sub-columns: session x2, lifetime x2)
STATS_INNER_GAP = 4  # buffer between Session's own 2 sub-columns, and between Lifetime's own 2
STATS_TABLE_GAP = 1  # extra buffer between Session's table and Lifetime's, beyond their own headers
STATS_ROW_MIN_WIDTH = (
    (PAYOUT_COL_W * 3 + PAYOUT_GAP * 2) + 4 + STATS_MIN_COL_W * 4 + STATS_INNER_GAP * 2 + STATS_TABLE_GAP
)
MIN_COLS = max(
    2 * MARGIN_COLS + MIN_COL_WIDTH * NUM_SPOT_COLUMNS + DIVIDER_COLS,
    2 * MARGIN_COLS + STATS_ROW_MIN_WIDTH,
)

# ---- Vertical content budget ----
# Rows, top to bottom: title(1) + rules-summary/card-count/bankroll
# banner(1) + table-status/running-true banner(1) + divider(1) + dealer
# status(1) + dealer value(1) + dealer cards(CARD_BLOCK_HEIGHT) + chips
# row(1) + player status(1) + player cards(CARD_BLOCK_HEIGHT) + player
# overflow-ticker row(1) + active value(1) + buffer(1) + main wager
# box(3) + main-bet settlement banner row(1) + side-bet boxes(3) (each
# bet's own name doubles as its header, so no separate title row) +
# side-bet banner: winning label(s)(1) + combined total(1) +
# hint/message(1) + blank(1) + input(1) + blank(1) + divider(1) +
# stats/payout header(1) + stats/payout rows(STATS_BLOCK_ROWS).
CONTENT_HEIGHT = (
    1 + 1 + 1 + 1 + 1 + 1 + CARD_BLOCK_HEIGHT + 1 + 1 + CARD_BLOCK_HEIGHT + 1 + 1 + 1 + 3 + 1 + 3 + 1 + 1
    + 1 + 1 + 1 + 1 + 1 + 1 + STATS_BLOCK_ROWS
)
# +2 reserves the top/bottom rows of the border frame around the whole
# window (see _draw_window_border) -- content is inset 1 row inside it.
MIN_LINES = CONTENT_HEIGHT + 2

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
SIDEBET_LABELS = ["Power Poker", "Star 21", "Buster"]
BUSTER_CELL_PAIR = 19  # Buster's wager-cell theme: a neutral mid-orange, black text
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
    ("$10 Table", [
        ("< +1", "$10", "$10", "$10"),
        ("+1", "$20", "$20", "$20"),
        ("+2", "$40", "$40", "$40"),
        ("+3", "$60", "$60", "$80"),
        ("+4", "$80", "$90", "$120"),
        ("> +5", "$100", "$120", "$150"),
    ]),
    ("$25 Table", [
        ("< +1", "$25", "$25", "$25"),
        ("+1", "$50", "$50", "$50"),
        ("+2", "$100", "$100", "$100"),
        ("+3", "$150", "$150", "$200"),
        ("+4", "$200", "$225", "$300"),
        ("> +5", "$250", "$300", "$375"),
    ]),
    ("$100 Table", [
        ("< +1", "$100", "$100", "$100"),
        ("+1", "$200", "$200", "$200"),
        ("+2", "$400", "$400", "$400"),
        ("+3", "$600", "$600", "$800"),
        ("+4", "$800", "$900", "$1200"),
        ("> +5", "$1000", "$1200", "$1500"),
    ]),
]

# (row, col) -> (y, x, height, width) for the currently-drawn wager cells,
# used to hit-test mouse clicks. Populated by the most recent render() call.
CellRects = Dict[Union[str, Tuple[int, int]], Tuple[int, int, int, int]]


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


def _center_x_right_bias(text: str, width: int, origin: int = 0) -> int:
    """Like _center_x, but when the text can't sit perfectly centered (an
    odd leftover gap), the extra column goes on the left, staggering the
    text one column right instead of left. Used for wager cell values."""
    pad = max(0, width - len(text))
    return origin + (pad + 1) // 2


def _draw_window_border(win, max_y: int, max_x: int) -> None:
    """A single-line box frame around the whole window. The bottom-right
    corner cell is the one spot curses refuses a normal addstr() into (it
    can't advance the cursor past it), so that one character goes in with
    insstr() instead, which writes without moving the cursor."""
    if max_y < 2 or max_x < 2:
        return
    try:
        win.addstr(0, 0, "┌" + "─" * (max_x - 2) + "┐")
    except curses.error:
        pass
    for row in range(1, max_y - 1):
        try:
            win.addstr(row, 0, "│")
        except curses.error:
            pass
        try:
            win.insstr(row, max_x - 1, "│")
        except curses.error:
            pass
    try:
        win.addstr(max_y - 1, 0, "└" + "─" * (max_x - 2))
    except curses.error:
        pass
    try:
        win.insstr(max_y - 1, max_x - 1, "┘")
    except curses.error:
        pass


def _draw_filled_banner(win, y: int, x: int, width: int, text: str, attr: int) -> None:
    """A full-width color-filled bar (not just colored text on an
    otherwise blank row) with the given text centered on top of it."""
    _safe_addstr(win, y, x, " " * width, attr)
    _safe_addstr(win, y, _center_x(text, width, x), text, attr)


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


def _card_block_width(hand: Hand, max_cards: Optional[int] = MAX_CARDS_IN_GRID) -> int:
    """Actual on-screen width of a hand's fanned card row as currently
    drawn -- i.e. draw_hand()'s footprint for however many cards it has
    right now (capped at max_cards, same as draw_hand itself), not a
    worst-case width. Used to keep a hand's cards centered on their
    actual width as it grows, rather than left-biased inside a slot
    sized for the maximum possible hand. max_cards=None means uncapped
    (the dealer's row -- it has no overflow ticker to fall back on, so
    its whole hand is always shown, however long it gets)."""
    n = len(hand.cards) if max_cards is None else min(len(hand.cards), max_cards)
    if n <= 0:
        return 0
    return CARD_W + FAN_OFFSET * (n - 1)


def draw_hand(
    win, base_y: int, x: int, hand: Hand, hide_hole: bool = False, hide_last: bool = False,
    max_cards: Optional[int] = MAX_CARDS_IN_GRID,
) -> None:
    last_index = len(hand.cards) - 1
    for i, card in enumerate(hand.cards):
        if max_cards is not None and i >= max_cards:
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
    """Text for the line above a hand's cards -- interactive prompts only.
    The hand's actual result (Win/Lose/Push/Surrendered/BLACKJACK/BUST) is
    NOT shown here; that lives only in the spot's settlement banner below
    the wager box, so a hand's outcome is never announced twice in two
    different spots on screen."""
    if round_ is None:
        return ""
    if round_.phase == Phase.EARLY_SURRENDER and round_.current_prelim_spot() is spot:
        return "Early Surrender?"
    if round_.phase == Phase.INSURANCE and round_.current_prelim_spot() is spot:
        kind = round_.insurance_prompt_kind(spot)
        return "Even Money?" if kind == "even_money" else "Insurance?"
    if round_.phase == Phase.DOUBLE_BLACKJACK and round_.current_prelim_spot() is spot:
        return "Double?"
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


def table_status_summary(session: GameSession) -> str:
    r = session.rules
    range_text = (
        f"MIN: ${r.table_min:,.0f}  –  MAX: ${r.table_max:,.0f}"
        if r.table_min > 0
        else f"MAX: ${r.table_max:,.0f}"
    )
    surr = {"off": "NO SURRENDER", "early": "EARLY SURRENDER", "late": "LATE SURRENDER"}[r.surrender]
    das = "DAS" if r.das else "NO DAS"
    rsa = "RSA" if r.rsa else "NO RSA"
    return f"{range_text}  •  {surr}  •  {das}  •  {rsa}"


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
        ("Royal Flushes", str(s.royal_flushes)),
    ]


def session_stats_rows(session: GameSession) -> List[Tuple[str, str]]:
    s = session.stats
    sign_main = "+" if s.session_main_pl >= 0 else ""
    sign_side = "+" if s.session_sidebet_pl >= 0 else ""
    return [
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
    input_focus: str,
    dim: bool = False,
) -> None:
    is_focused = betting and input_focus == "wager" and bet_row == 0 and bet_col == col
    if is_focused and bet_edit_buffer:
        text = bet_edit_buffer
    elif round_ is not None and col < len(round_.spots):
        text = f"{sum(h.bet for h in round_.spots[col].hands):,.0f}"
    else:
        text = f"{session.wagers[col]:,.0f}"
    _draw_box(win, box_y, box_x, MAIN_WAGER_BOX_W, dim=dim)
    attr = curses.A_REVERSE if is_focused else (curses.A_DIM if dim else 0)
    _safe_addstr(win, box_y + 1, _center_x_right_bias(text, MAIN_WAGER_BOX_W - 2, box_x + 1), text, attr)


def _draw_colored_box(win, y: int, x: int, width: int, attr: int) -> None:
    """Like _draw_box, but the cell's INTERIOR -- never its border -- is
    filled with a color pair, for a side bet's themed wager cell. The
    frame itself is drawn in the default terminal color so the color
    block reads as strictly contained inside the box, with no bleed onto
    its own border."""
    _safe_addstr(win, y, x, "┌" + "─" * (width - 2) + "┐")
    _safe_addstr(win, y + 1, x, "│")
    _safe_addstr(win, y + 1, x + 1, " " * (width - 2), attr)
    _safe_addstr(win, y + 1, x + width - 1, "│")
    _safe_addstr(win, y + 2, x, "└" + "─" * (width - 2) + "┘")


# Each side bet's wager cell is permanently tinted in its own color, the
# same pairs used for that bet's plain (non-jackpot) win banner -- already
# white/black text, never the gold accent reserved for a bet's rarest hit.
SIDEBET_CELL_PAIR = {"power_poker": 8, "star21": 10, "dealer_buster": BUSTER_CELL_PAIR}


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
    input_focus: str,
    dim: bool = False,
) -> CellRects:
    rects: CellRects = {}
    for slot, row in enumerate((1, 2, 3)):
        key = ROW_KEYS[row]
        rule = getattr(session.rules, key)
        sub_x = x + slot * (SIDEBET_BOX_W + SIDEBET_BOX_GAP)
        is_focused = betting and input_focus == "wager" and bet_row == row and bet_col == col
        if not rule.enabled:
            # Greyed out and, per enabled_rows() in _main, simply never
            # reachable by the row scroller (or a mouse click) --
            # unselectable, not just styled.
            _draw_box(win, box_y, sub_x, SIDEBET_BOX_W, dim=True)
            _safe_addstr(win, box_y + 1, _center_x_right_bias("Off", SIDEBET_BOX_W - 2, sub_x + 1), "Off", curses.A_DIM)
            continue
        if round_ is not None and col < len(round_.spots):
            wager = round_.spots[col].side_bet_wagers.get(key, 0.0)
        else:
            wager = session.side_bet_wagers[col].get(key, 0.0)
        if is_focused and bet_edit_buffer:
            text = bet_edit_buffer
        elif wager > 0:
            text = f"{wager:,.0f}"
        else:
            # No wager on this bet yet -- the bet's own name fills the
            # cell in place of a bare "0", doubling as the zero value.
            text = SIDEBET_LABELS[slot]
        cell_attr = curses.color_pair(SIDEBET_CELL_PAIR[key])
        if dim:
            cell_attr |= curses.A_DIM
        _draw_colored_box(win, box_y, sub_x, SIDEBET_BOX_W, cell_attr)
        text_attr = (cell_attr | curses.A_REVERSE) if is_focused else cell_attr
        _safe_addstr(win, box_y + 1, _center_x_right_bias(text, SIDEBET_BOX_W - 2, sub_x + 1), text, text_attr)
        rects[(row, col)] = (box_y, sub_x, 3, SIDEBET_BOX_W)
    return rects


# (singular, plural) word forms for the split-hand tally, keyed by outcome.
_OUTCOME_WORDS = {
    "player_win": ("Win", "Wins"),
    "dealer_win": ("Loss", "Losses"),
    "push": ("Push", "Pushes"),
    "surrender": ("Surrender", "Surrenders"),
}


def _spot_settlement_banner(round_: Optional[Round], spot_index: int) -> Tuple[str, int]:
    """Main-bet settlement banner: (text, curses attr). Shown as soon as
    this spot has at least one settled hand -- which can be well before
    the whole round reaches Phase.SETTLED, since a lone player blackjack
    or an accepted even money offer settles immediately (see engine.py's
    _settle_immediate_blackjacks/_record_settlement), independent of
    whatever the rest of the round is still doing.

    Most outcomes get the standard "Win/Lose/Push/Surrendered -
    $X returned" treatment (dark grass green). A handful of specific
    outcomes read as a different *kind* of event and get their own color:
    an immediate player blackjack (yellow on dark purple), any hand beaten
    by a confirmed dealer blackjack (white on maroon), a player bust
    (white on deep red), and an accepted even money offer -- which is
    still the standard green, per spec, just its own distinct label. A
    doubled hand's win/loss also keeps the standard green, just labeled
    "Double Down Win"/"Double Down Loss" instead of the plain Win/Lose.

    A single hand shows its full result word; a split spot's multiple
    hands instead tally spelled-out counts, e.g. "2 Wins/1 Loss" (Win/
    Loss/Push/Surrender, in that fixed order). A doubled hand that wins
    counts double in its tally -- twice the money was on it -- so, e.g.,
    splitting a pair and doubling down on one hand that then wins, with
    the other hand also winning normally, reads "3 Wins", not "2 Wins".
    A split hand can never itself be a blackjack or have taken even money
    (see Hand.is_blackjack), so the tally case only ever needs to pick
    between the standard color and the dealer-blackjack one -- that's the
    one event that's always true of every hand in the spot at once, so a
    single color for the whole tally still reads unambiguously."""
    if round_ is None:
        return "", 0
    results = [r for r in round_.results if r.spot_index == spot_index]
    if not results:
        return "", 0
    total = sum(r.payout for r in results)
    standard_attr = curses.color_pair(STANDARD_SETTLEMENT_PAIR) | curses.A_BOLD
    dealer_bj_attr = curses.color_pair(DEALER_BJ_PAIR) | curses.A_BOLD

    if len(results) == 1:
        r = results[0]
        hand = r.hand
        if hand.even_money_taken:
            text, attr = "EVEN MONEY", standard_attr
        elif hand.is_blackjack and r.outcome == "player_win":
            text, attr = "BLACKJACK", curses.color_pair(PLAYER_BJ_PAIR) | curses.A_BOLD
        elif hand.is_bust:
            text, attr = "BUST", curses.color_pair(BUST_PAIR) | curses.A_BOLD
        elif round_.dealer_has_blackjack and r.outcome == "dealer_win":
            text, attr = "DEALER BLACKJACK", dealer_bj_attr
        elif hand.doubled and r.outcome == "player_win":
            text, attr = "Double Down Win", standard_attr
        elif hand.doubled and r.outcome == "dealer_win":
            text, attr = "Double Down Loss", standard_attr
        else:
            text, attr = OUTCOME_LABELS[r.outcome], standard_attr
    else:
        counts: Dict[str, int] = {}
        for r in results:
            # A doubled win counts double -- twice the money was riding
            # on that one hand, so it should weigh twice as much here too.
            weight = 2 if (r.outcome == "player_win" and r.hand.doubled) else 1
            counts[r.outcome] = counts.get(r.outcome, 0) + weight
        parts = []
        for outcome in ("player_win", "dealer_win", "push", "surrender"):
            if outcome not in counts:
                continue
            n = counts[outcome]
            singular, plural = _OUTCOME_WORDS[outcome]
            parts.append(f"{n} {singular if n == 1 else plural}")
        text = "/".join(parts)
        attr = dealer_bj_attr if round_.dealer_has_blackjack else standard_attr

    return f"{text} – ${total:,.2f} returned", attr


_SIDEBET_KEYS_ORDERED = ("power_poker", "star21", "dealer_buster")
_BANNER_FRAME_MS = 1500
_DEFAULT_BANNER_ATTR = curses.A_BOLD


def _buster_stage(label: str) -> int:
    """3-card bust -> 0, 4 -> 1, ... 7 -> 4, 8+ -> 5."""
    if label.startswith("8+"):
        return 5
    try:
        n = int(label.split()[0])
    except (ValueError, IndexError):
        return 0
    return max(0, min(5, n - 3))


def _sidebet_banner_attr(key: str, label: str) -> int:
    """Color for one side bet's win banner frame, by which side bet and
    which specific outcome it is (some outcomes get their own accent
    color within the side bet's base color)."""
    if key == "power_poker":
        if label == "Royal Flush":
            return curses.color_pair(9) | curses.A_BOLD
        return curses.color_pair(8) | curses.A_BOLD
    if key == "star21":
        if label == "Suited 7-7-7 Diamonds":
            return curses.color_pair(11) | curses.A_BOLD
        return curses.color_pair(10) | curses.A_BOLD
    if key == "dealer_buster":
        return curses.color_pair(BUSTER_PAIR_BASE + _buster_stage(label)) | curses.A_BOLD
    return _DEFAULT_BANNER_ATTR


def _spot_sidebet_wins(round_: Round, spot: Spot) -> List[Tuple[str, str, float]]:
    """[(key, label, win_amount), ...] for this spot's Power Poker/Star21/
    Buster wins settled so far this round, in PP/S21/BUST order. Each
    settles at a different point (Power Poker and Star21 immediately
    after the deal, Buster only once the dealer's hand is fully played
    out), so this list can grow over the course of the round rather than
    only appearing once everything is done."""
    wins: List[Tuple[str, str, float]] = []
    for key in _SIDEBET_KEYS_ORDERED:
        display_name = SIDE_BET_LABELS[key]
        for sb in round_.side_bet_results:
            if sb.spot_index == spot.index and sb.name == display_name and sb.win_amount > 0:
                wins.append((key, sb.label or display_name, sb.win_amount))
    return wins


def _spot_insurance_result(round_: Round, spot: Spot):
    """This spot's settled Insurance SideBetResult, if it placed one --
    None before the dealer's hole card is peeked, since Insurance can't
    resolve (win OR lose) any earlier than that."""
    for sb in round_.side_bet_results:
        if sb.spot_index == spot.index and sb.name == "Insurance":
            return sb
    return None


def _sidebet_banner_lines(round_: Optional[Round], spot: Spot) -> Tuple[Tuple[str, int], Tuple[str, int]]:
    """The side-bet banner's two rows, built as a list of paired frames
    that cycle together on a wall clock, one frame at a time, repeating --
    driven by _main's idle-timeout redraws, not a counter, so it keeps
    animating even with no keypress. Every frame pairs its own row-1 label
    with the SAME row 2: the combined "Side Bets Total" (dark gray),
    everything settled so far, Insurance's contribution included.
    Insurance gets its own row-1 frame -- "INSURANCE" in beige -- shown
    whether it won or lost, since taking insurance is worth confirming
    either way, not just when it pays off; unlike Power Poker/Star21/
    Buster, it never gets its own row-2 total, just the shared one.

    Power Poker, Star21, and Insurance each settle immediately (right
    after the deal, and right after the dealer's peek, respectively), so
    their frames can appear well before the round is fully settled;
    Dealer Buster can't resolve until the dealer's hand is fully played
    out, so its frame only ever shows up once everything else is done."""
    empty = ("", _DEFAULT_BANNER_ATTR)
    if round_ is None:
        return empty, empty

    wins = _spot_sidebet_wins(round_, spot)
    insurance = _spot_insurance_result(round_, spot)
    total = sum(amount for _, _, amount in wins) + (insurance.win_amount if insurance else 0.0)
    gray_line = (f"Side Bets Total: ${total:,.2f} returned", curses.color_pair(SIDEBET_TOTAL_PAIR) | curses.A_BOLD)

    frames: List[Tuple[Tuple[str, int], Tuple[str, int]]] = [
        ((_display_label(label), _sidebet_banner_attr(key, label)), gray_line) for key, label, _ in wins
    ]
    if insurance is not None:
        frames.append((("INSURANCE", curses.color_pair(INSURANCE_PAIR) | curses.A_BOLD), gray_line))

    if not frames:
        return empty, empty
    frame = int(time.monotonic() * 1000 // _BANNER_FRAME_MS) % len(frames)
    return frames[frame]


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


def _center_on(text: str, center_x: int) -> int:
    return max(0, center_x - len(text) // 2)


def _draw_player_spot(
    win,
    chips_y: int,
    status_y: int,
    cards_y: int,
    overflow_y: int,
    value_y: int,
    cx: int,
    col_width: int,
    spot: Spot,
    round_: Round,
    active: Optional[Tuple[Spot, Hand]],
    deal_reveal: Optional[int] = None,
) -> None:
    """Draws a non-split-aces spot: any earlier completed split hands'
    values collapse to a compact chips row above the cards (unchanged
    from before), kept visually apart from the current hand's own value,
    which sits between its cards and the wager box below -- cards, the
    live value, and the status line all share the column's own center,
    since the (separate, above) chips row no longer competes for that
    same horizontal space the way a single combined row once did.

    deal_reveal, when set (only during the initial deal animation -- no
    split can have happened yet), draws just the spot's cards, capped to
    however many of its first two have been "dealt" so far on screen;
    status/value/chips text -- which would spoil or misdescribe a
    still-incomplete hand -- is skipped entirely."""
    if deal_reveal is not None:
        hand = spot.hands[0]
        hand_x = cx + max(0, (col_width - _card_block_width(hand)) // 2)
        draw_hand(win, cards_y, hand_x, hand, max_cards=deal_reveal)
        return

    active_index = _active_hand_index(spot, round_)
    if active_index > 0:
        chips_text = "   ".join(
            _emph_compact(hand_value_label(spot.hands[j], resolved=True)) for j in range(active_index)
        )
        _safe_addstr(win, chips_y, _center_x(chips_text, col_width, cx), chips_text, curses.A_BOLD)

    hand = spot.hands[active_index]
    is_active = active is not None and active[1] is hand

    status = hand_status_text(hand, spot, round_)
    is_prompt = status and round_.phase in (Phase.EARLY_SURRENDER, Phase.INSURANCE, Phase.DOUBLE_BLACKJACK)
    _safe_addstr(win, status_y, _center_x(status, col_width, cx), status, curses.A_REVERSE if is_prompt else curses.A_BOLD)

    hand_x = cx + max(0, (col_width - _card_block_width(hand)) // 2)
    draw_hand(win, cards_y, hand_x, hand, hide_last=hand.double_hidden)
    _draw_overflow_chips(win, overflow_y, hand_x, CARD_ROW_WIDTH, hand, hide_last=hand.double_hidden)

    emph = _emph if len(spot.hands) == 1 else _emph_compact
    value_text = emph(hand_value_label(hand, resolved=hand.is_resolved))
    _safe_addstr(win, value_y, _center_x(value_text, col_width, cx), value_text, curses.A_REVERSE if is_active else curses.A_BOLD)


SPLIT_ACE_GAP = 2  # columns of breathing room between adjacent split-ace hands


def _draw_split_ace_hands(
    win,
    value_y: int,
    status_y: int,
    cards_y: int,
    overflow_y: int,
    cx: int,
    col_width: int,
    spot: Spot,
    round_: Round,
    active: Optional[Tuple[Spot, Hand]],
) -> None:
    """Split aces get exactly one card each and are never collapsed to a
    chip -- every hand in an ace-split spot (up to 4, with RSA) is shown
    at once, each in its own equal, gap-separated slice of the spot's
    column, with its cards centered directly under its own value."""
    n = max(1, len(spot.hands))
    sub_w = max(1, (col_width - (n - 1) * SPLIT_ACE_GAP) // n)
    for idx, hand in enumerate(spot.hands):
        sub_x = cx + idx * (sub_w + SPLIT_ACE_GAP)
        is_active = active is not None and active[1] is hand
        value_text = _emph_compact(hand_value_label(hand, resolved=hand.is_resolved))
        vx = _center_x(value_text, sub_w, sub_x)
        _safe_addstr(win, value_y, vx, value_text, curses.A_REVERSE if is_active else curses.A_BOLD)
        center_x = vx + len(value_text) // 2

        status = hand_status_text(hand, spot, round_)
        _safe_addstr(win, status_y, _center_on(status, center_x), status, curses.A_BOLD)

        hand_x = center_x - _card_block_width(hand) // 2
        draw_hand(win, cards_y, hand_x, hand, hide_last=hand.double_hidden)
        _draw_overflow_chips(win, overflow_y, hand_x, CARD_ROW_WIDTH, hand, hide_last=hand.double_hidden)


def _deal_reveal_counts(round_: Round, progress: int) -> Tuple[Dict[int, int], int]:
    """From how many steps of the round's initial deal sequence (see
    engine.initial_deal_sequence) have played so far, how many of each
    spot's -- and the dealer's -- first two cards should already be
    visible on screen."""
    seq = initial_deal_sequence(round_.play_order)
    spot_counts = {spot.index: 0 for spot in round_.spots}
    dealer_count = 0
    for target in seq[:progress]:
        if target is None:
            dealer_count += 1
        else:
            spot_counts[target] += 1
    return spot_counts, dealer_count


def render(
    stdscr,
    session: GameSession,
    round_: Optional[Round],
    buffer: str,
    message: str,
    bet_row: int = 0,
    bet_col: int = 0,
    bet_edit_buffer: str = "",
    input_focus: str = "wager",
    deal_progress: Optional[int] = None,
) -> CellRects:
    stdscr.erase()
    win = stdscr
    betting = round_ is None
    max_y, max_x = win.getmaxyx()

    # deal_progress, when set, is a step count into engine.initial_deal_
    # sequence(round_.play_order) -- how many of the round's already-dealt
    # initial cards should be visible on screen so far. Everything that
    # would spoil the round's outcome (dealer status/value, settlement
    # banners, the phase hint) stays blank while animating; only the cards
    # themselves reveal progressively -- see _animate_deal.
    animating = round_ is not None and deal_progress is not None
    spot_reveal: Optional[Dict[int, int]] = None
    dealer_reveal: Optional[int] = None
    if animating:
        spot_reveal, dealer_reveal = _deal_reveal_counts(round_, deal_progress)

    # Center the whole layout vertically in whatever room the (ideally
    # full-screen) terminal offers; horizontally, a fixed margin is used
    # instead (see MARGIN_COLS) so the table stretches to fill the space
    # between the margins rather than being pinned to a fixed width.
    _draw_window_border(win, max_y, max_x)
    left_margin = MARGIN_COLS
    usable_width = max(0, max_x - 2 * MARGIN_COLS)
    # Content is inset 1 row inside the window border drawn above (top and
    # bottom), so it never centers over top of it.
    y_origin = max(1, (max_y - CONTENT_HEIGHT) // 2)
    right_edge = left_margin + usable_width
    # One column is reserved between each pair of adjacent spots for a
    # decorative ♦ divider (see divider_x below); any leftover width from
    # the integer division falls unused at the far right of the screen,
    # past the last spot column, rather than skewing any one column wider.
    col_width = max(1, (usable_width - DIVIDER_COLS) // NUM_SPOT_COLUMNS)
    col_x = [left_margin + i * (col_width + 1) for i in range(NUM_SPOT_COLUMNS)]
    divider_x = [col_x[i] + col_width for i in range(NUM_SPOT_COLUMNS - 1)]

    cell_rects: CellRects = {}

    # ---- Header: title, rules-summary banner (+ card count, bankroll),
    # table-status banner (+ running/true count), min/max, surrender, DAS,
    # RSA), then a divider before the dealer's area ----
    shoe = session.shoe
    y = y_origin
    title = "CasinoSimulations™ Blackjack"
    _safe_addstr(win, y, _center_x(title, usable_width, left_margin), title, curses.A_BOLD)
    y += 1

    top_line = rules_summary(session)
    _draw_filled_banner(win, y, left_margin, usable_width, top_line, curses.color_pair(4) | curses.A_BOLD)
    cards_dealt_text = f"Cards Left: {shoe.cards_remaining}({shoe.cards_dealt})"
    _safe_addstr(win, y, left_margin, cards_dealt_text, curses.color_pair(4) | curses.A_BOLD)
    cell_rects["cards_dealt"] = (y, left_margin, 1, len(cards_dealt_text))
    bankroll_text = f"Bankroll: {money(session.bankroll)}"
    bankroll_x = max(left_margin, right_edge - len(bankroll_text))
    _safe_addstr(win, y, bankroll_x, bankroll_text, curses.color_pair(4) | curses.A_BOLD)
    _safe_addstr(win, y, bankroll_x, "Bankroll:", curses.color_pair(6) | curses.A_BOLD)
    y += 1

    status_line = table_status_summary(session)
    _draw_filled_banner(win, y, left_margin, usable_width, status_line, curses.color_pair(5) | curses.A_BOLD)
    counts_text = f"Running: {shoe.running_count:+d}   True: {shoe.true_count:+.1f}"
    _safe_addstr(win, y, left_margin, counts_text, curses.color_pair(5) | curses.A_BOLD)
    y += 1

    _safe_addstr(win, y, left_margin, "-" * max(usable_width, 0))
    y += 1  # divider row

    # ---- DEALER: status line (blank unless BUST/BLACKJACK), value line,
    # then cards directly beneath with no gap (no "DEALER" label) ----
    hide_hole = round_ is not None and not round_.dealer_revealed
    dealer_hand = round_.dealer_hand if round_ else Hand()
    dealer_resolved = round_ is not None and round_.dealer_revealed and round_.phase != Phase.DEALER_TURN
    if round_ and not animating:
        d_status = dealer_status_text(round_)
        _safe_addstr(win, y, _center_x(d_status, usable_width, left_margin), d_status, curses.A_BOLD)
    y += 1
    if round_ and not animating:
        value_text = _emph(hand_value_label(dealer_hand, hide_hole=hide_hole, resolved=dealer_resolved))
        _safe_addstr(win, y, _center_x(value_text, usable_width, left_margin), value_text, curses.A_BOLD)
    y += 1

    dealer_cards_base_y = y
    # Center on the dealer's actual card count as it grows (not a slot
    # sized for the worst-case 12-card hand), so the row stays centered
    # under the dealer's value line -- and the screen -- as they draw,
    # instead of sitting left-biased inside a too-wide fixed slot. The
    # dealer's hand is never capped/overflowed -- it has its own row with
    # room to spare, unlike a player spot, so the whole hand always shows.
    dealer_x = left_margin + max(0, (usable_width - _card_block_width(dealer_hand, max_cards=None)) // 2)
    if round_:
        if animating:
            # Always hidden during the deal animation, even if the round
            # already resolved (e.g. an instant dealer blackjack) before
            # the animation even started -- the hole card only appears at
            # its own step in the sequence, never sooner.
            draw_hand(win, dealer_cards_base_y, dealer_x, dealer_hand, hide_hole=True, max_cards=dealer_reveal)
        else:
            draw_hand(win, dealer_cards_base_y, dealer_x, dealer_hand, hide_hole=hide_hole, max_cards=None)
    y += CARD_BLOCK_HEIGHT

    # ---- PLAYER: collapsed chips for any already-completed split hands
    # (above the cards, where they've always been) -> status -> cards ->
    # overflow -> the CURRENT hand's own value, between the cards and the
    # wager box with a small buffer -- keeps the collapsed (done) and
    # live (in-progress) values visually apart instead of side by side. ----
    chips_y = y
    y += 1
    status_y = y
    y += 1
    player_cards_base_y = y
    y += CARD_BLOCK_HEIGHT
    player_overflow_y = y
    y += 1
    active_value_y = y
    y += 1
    y += 1  # buffer before the wager box's top border

    # ---- Per-spot wager block: main wager, its settlement banner,
    # side-bet boxes (each bet's own name doubles as its zero-wager
    # placeholder, so no separate header row is needed above them), then
    # the 2-row side-bet banner: winning label(s) cycling, then the
    # static combined total ----
    wager_box_y = y
    y += 3
    settlement_row_y = y
    y += 1
    sidebet_box_y = y
    y += 3
    banner_row1_y = y
    y += 1
    banner_row2_y = y

    num_hands = session.rules.num_hands
    active = round_.current_player_hand() if round_ else None

    for i in range(NUM_SPOT_COLUMNS):
        cx = col_x[SPOT_SCREEN_ORDER[i]]
        in_play = round_ is not None and i < len(round_.spots)

        if in_play:
            spot = round_.spots[i]
            if animating:
                # No split can have happened yet this early -- every spot
                # is still its single, freshly-dealt hand -- so the deal
                # animation only ever needs the plain (non-split-aces) path.
                _draw_player_spot(
                    win, chips_y, status_y, player_cards_base_y, player_overflow_y, active_value_y,
                    cx, col_width, spot, round_, active, deal_reveal=spot_reveal.get(spot.index, 0),
                )
            elif spot.hands and spot.hands[0].is_split_aces:
                _draw_split_ace_hands(
                    win, chips_y, status_y, player_cards_base_y, player_overflow_y,
                    cx, col_width, spot, round_, active,
                )
            else:
                _draw_player_spot(
                    win, chips_y, status_y, player_cards_base_y, player_overflow_y, active_value_y,
                    cx, col_width, spot, round_, active,
                )

        # Wager grid: always drawn for all three spots (regardless of how many
        # hands are actually in play this round) so wagers stay visible,
        # editable, and clickable ahead of time; spots not in play this round
        # are dimmed.
        dim = i >= num_hands
        wager_box_x = cx + max(0, (col_width - MAIN_WAGER_BOX_W) // 2)
        _draw_wager_cell(win, wager_box_y, wager_box_x, i, session, round_, betting, bet_row, bet_col, bet_edit_buffer, input_focus, dim)
        cell_rects[(0, i)] = (wager_box_y, wager_box_x, 3, MAIN_WAGER_BOX_W)

        sidebet_group_x = cx + max(0, (col_width - SIDEBET_GROUP_W) // 2)
        sb_rects = _draw_sidebet_amounts(win, sidebet_box_y, sidebet_group_x, i, session, round_, betting, bet_row, bet_col, bet_edit_buffer, input_focus, dim)
        cell_rects.update(sb_rects)

        if in_play and not animating:
            spot = round_.spots[i]
            settlement_text, settlement_attr = _spot_settlement_banner(round_, i)
            if settlement_text:
                _draw_filled_banner(win, settlement_row_y, cx, col_width, settlement_text, settlement_attr)
            line1, line2 = _sidebet_banner_lines(round_, spot)
            banner1_text, banner1_attr = line1
            banner2_text, banner2_attr = line2
            if banner1_text:
                _draw_filled_banner(win, banner_row1_y, cx, col_width, banner1_text, banner1_attr)
            if banner2_text:
                _draw_filled_banner(win, banner_row2_y, cx, col_width, banner2_text, banner2_attr)

    # ---- Decorative ♦ dividers between the 3 spot columns, one column
    # wide apiece (see divider_x above), spanning just the player/wager
    # block -- not the dealer's own row, which is centered across the
    # whole width rather than per column, so a full-height divider would
    # cut through it. ----
    for dx in divider_x:
        for dy in range(chips_y, banner_row2_y + 1):
            _safe_addstr(win, dy, dx, "♦", curses.color_pair(1))

    # ---- Hint / message line (shows the active message in place of the
    # contextual hint when there is one) ----
    hint_y = banner_row2_y + 1
    hint = ""
    if animating:
        hint = "Dealing..."
    elif round_ is None:
        hint = "Arrows/mouse: move  |  digits: type amount  |  RETURN: confirm / deal"
    elif round_.phase == Phase.EARLY_SURRENDER:
        hint = "S Surrender    RETURN Continue"
    elif round_.phase == Phase.INSURANCE:
        hint = "SPACE Yes    RETURN No"
    elif round_.phase == Phase.DOUBLE_BLACKJACK:
        hint = "D Double    RETURN No"
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

    # ---- Command input -- clickable; typing a command requires clicking
    # here first, the same way typing a wager requires clicking that cell
    # (or navigating to it with arrows) -- see input_focus in _main. ----
    input_y = hint_y + 2
    cli_focused = betting and input_focus == "cli"
    if cli_focused:
        _safe_addstr(win, input_y, left_margin, " " * usable_width, curses.A_REVERSE)
    _safe_addstr(win, input_y, left_margin, f"> {buffer}", curses.A_REVERSE if cli_focused else 0)
    cell_rects["cli"] = (input_y, left_margin, 1, max(1, usable_width))

    # ---- Stats panel: the 3 side-bet payout tables side by side on the
    # left, Session (2x6) and Lifetime (2x6) sharing the rest -- also
    # available full-screen any time via the 'stats' command. Every
    # column here follows the same convention: name left-aligned, value
    # right-aligned, so long $ P/L figures never crowd the label. ----
    divider_y = input_y + 2
    _safe_addstr(win, divider_y, left_margin, "-" * max(usable_width, 0))
    stats_y = divider_y + 1

    payout_x0 = left_margin
    payout_region_w = PAYOUT_COL_W * 3 + PAYOUT_GAP * 2
    divider_x = payout_x0 + payout_region_w + 1
    stats_x0 = divider_x + 3

    payout_value_w = 7  # fits "5000:1", the widest odds figure, plus a pad column
    payout_label_w = PAYOUT_COL_W - payout_value_w
    for slot, (title, rows) in enumerate(payout_tables_for(session.shoe.num_decks)):
        tx = payout_x0 + slot * (PAYOUT_COL_W + PAYOUT_GAP)
        _safe_addstr(win, stats_y, tx, title, curses.A_BOLD | curses.A_UNDERLINE)
        for i, (label, odds) in enumerate(rows):
            line = f"{label[:payout_label_w]:<{payout_label_w}}{odds:>{payout_value_w}}"
            _safe_addstr(win, stats_y + 1 + i, tx, line)

    for dy in range(STATS_BLOCK_ROWS + 1):
        _safe_addstr(win, stats_y + dy, divider_x, "│", curses.A_DIM)

    session_rows = session_stats_rows(session)
    life_rows = lifetime_stats_rows(session)
    sess_a, sess_b = session_rows[:STATS_SESSION_ROWS], session_rows[STATS_SESSION_ROWS:]
    life_a, life_b = life_rows[:STATS_LIFETIME_ROWS], life_rows[STATS_LIFETIME_ROWS:]

    # A gap sits between each table's own two sub-columns (session's
    # names+values vs. its second names+values, and likewise for
    # lifetime), so the left sub-column's values never run up against the
    # right sub-column's names -- but not between the two tables
    # themselves, which already have SESSION/LIFETIME STATS headers
    # marking that boundary.
    stats_region_w = max(1, usable_width - (stats_x0 - left_margin))
    stats_col_w = max(1, (stats_region_w - 2 * STATS_INNER_GAP - STATS_TABLE_GAP) // 4)
    sess_a_x = stats_x0
    sess_b_x = sess_a_x + stats_col_w + STATS_INNER_GAP
    life_a_x = sess_b_x + stats_col_w + STATS_TABLE_GAP
    life_b_x = life_a_x + stats_col_w + STATS_INNER_GAP

    _safe_addstr(win, stats_y, sess_a_x, "SESSION STATS", curses.A_BOLD | curses.A_UNDERLINE)
    _safe_addstr(win, stats_y, life_a_x, "LIFETIME STATS", curses.A_BOLD | curses.A_UNDERLINE)

    # The row is hard-clipped to the column's width so a long value can
    # never bleed into the next column even in a narrower terminal.
    row_w = max(0, stats_col_w - 1)
    value_w = 10  # keeps money/percent values intact; the label truncates first if space is tight
    label_value_gap = 2  # breathing room so the longest labels (e.g. "Dealer Blackjacks") never butt up against the value
    label_w = max(4, row_w - value_w - label_value_gap)
    for col_x_, rows in ((sess_a_x, sess_a), (sess_b_x, sess_b), (life_a_x, life_a), (life_b_x, life_b)):
        for i, (label, value) in enumerate(rows):
            line = f"{label[:label_w]:<{label_w}}{'':<{label_value_gap}}{value:>{value_w}}"
            _safe_addstr(win, stats_y + 1 + i, col_x_, line[:row_w])

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
    ch = stdscr.getch()
    while ch == -1:  # stdscr is in timeout() mode for the main loop's idle
        ch = stdscr.getch()  # redraws; a real "any key" wait needs to skip those


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
        f"  RSA Facedown:        {'ON' if r.rsa_facedown else 'OFF'}",
        f"  Surrender:           {r.surrender.title()}",
        f"  Split Max Hands:     {r.split_max_hands}",
        f"  Table Limits:        {table_range}",
        f"  Double Facedown:     {'ON' if r.double_facedown else 'OFF'}",
        f"  Double Blackjack:    {'ON' if r.double_blackjack else 'OFF'}",
        "",
        "SIDE BETS",
    ]
    num_decks = session.shoe.num_decks
    for key, label, req in (
        ("power_poker", "Power Poker", "3+"),
        ("star21", "Star 21", "2+"),
        ("dealer_buster", "Dealer Buster", None),
    ):
        rule = getattr(r, key)
        if rule.enabled:
            state = f"ON  (min ${rule.min_bet:,.0f}, max ${rule.max_bet:,.0f})"
            if key == "star21" and num_decks == 2:
                state += "  [2-Deck paytable]"
        elif req is not None and not side_bet_allowed(key, num_decks):
            state = f"off (locked -- requires {req} decks, shoe has {num_decks})"
        else:
            state = "off"
        lines.append(f"  {label:<16} {state}")
    if num_decks == 1:
        lines.append("  (single-deck Buster: 8+ card bust pays 500:1)")
    _render_overlay_lines(stdscr, "cs-blackjack -- Game Rules", lines)


def render_stats_screen(stdscr, session: GameSession) -> None:
    lines: List[str] = ["LIFETIME STATS"]
    for label, value in lifetime_stats_rows(session):
        lines.append(f"  {label:<18}{value:>12}")
    lines.append("")
    lines.append("SESSION STATS")
    for label, value in session_stats_rows(session):
        lines.append(f"  {label:<18}{value:>12}")
    _render_overlay_lines(stdscr, "cs-blackjack -- Stats", lines)


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
    """Flashes over the CLI input line -- white background, black text --
    so a fresh shoe is unmistakable even if the player's eyes are on
    their cards or wager, not the header's small "Cards Left" cell (easy
    to miss entirely when focused on play)."""
    msg = "** NEW SHOE **"
    attr = curses.color_pair(7) | curses.A_BOLD
    for i in range(6):
        cell_rects = render(stdscr, session, round_, "", "")
        if i % 2 == 0:
            y, x, _h, w = cell_rects.get("cli", (0, 0, 1, 0))
            width = max(w, len(msg))
            _safe_addstr(stdscr, y, x, " " * width, attr)
            _safe_addstr(stdscr, y, x, msg, attr)
            stdscr.refresh()
        curses.napms(220)


BUSTER_PAIR_BASE = 12  # 6 pairs, one per bust-length stage (3,4,5,6,7,8+ cards)
SIDEBET_TOTAL_PAIR = 18  # "Side Bets Total" summary frame: dark gray

# Main-bet settlement banner colors. STANDARD covers the ordinary outcomes
# (Win/Lose/Push/Surrendered, and multi-hand tallies) plus Even Money, which
# is explicitly the same color by spec -- it's just another "money settled,
# nothing unusual" result. The other three each mark a specific kind of
# event the player should notice at a glance, so they get their own colors
# entirely distinct from STANDARD and from each other.
STANDARD_SETTLEMENT_PAIR = 20  # standard win/lose/push/surrender/even-money: dark grass green
PLAYER_BJ_PAIR = 21  # an immediate, unbeaten player blackjack: yellow on dark purple
DEALER_BJ_PAIR = 22  # any hand beaten by a confirmed dealer blackjack: white on maroon
BUST_PAIR = 23  # a player bust: white on deep red
INSURANCE_PAIR = 24  # a settled Insurance side bet, win or lose: black on beige


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
    curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_RED)  # table-status banner: white on red
    curses.init_pair(6, curses.COLOR_YELLOW, curses.COLOR_BLUE)  # header "Bankroll:" text
    curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)  # new-shoe flash: black on white
    curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_MAGENTA)  # Power Poker win
    curses.init_pair(9, curses.COLOR_YELLOW, curses.COLOR_MAGENTA)  # Power Poker: Royal Flush
    curses.init_pair(10, curses.COLOR_BLACK, curses.COLOR_GREEN)  # Star21 win -- black text reads easiest on green
    curses.init_pair(11, curses.COLOR_BLACK, curses.COLOR_GREEN)  # Star21: Suited 7-7-7 Diamonds -- same treatment

    # Dealer Buster: a light-to-deep orange ramp, one pair per bust length
    # (3 cards through 8+), with text color flipping from black to white
    # to gold as the background darkens. True orange needs the extended
    # palette; on a basic 8-color terminal, approximate the ramp with
    # yellow (light stages) shading into red (deep stages) instead.
    if curses.COLORS >= 256:
        oranges = [230, 223, 216, 209, 208, 202]  # xterm-256: light -> deep orange
        texts = [
            curses.COLOR_BLACK, curses.COLOR_BLACK, curses.COLOR_BLACK,
            curses.COLOR_WHITE, curses.COLOR_WHITE, curses.COLOR_YELLOW,
        ]
    else:
        oranges = [
            curses.COLOR_YELLOW, curses.COLOR_YELLOW, curses.COLOR_YELLOW,
            curses.COLOR_RED, curses.COLOR_RED, curses.COLOR_RED,
        ]
        texts = [
            curses.COLOR_BLACK, curses.COLOR_BLACK, curses.COLOR_BLACK,
            curses.COLOR_WHITE, curses.COLOR_WHITE, curses.COLOR_YELLOW,
        ]
    for stage, (bg_color, fg_color) in enumerate(zip(oranges, texts)):
        curses.init_pair(BUSTER_PAIR_BASE + stage, fg_color, bg_color)

    # "Side Bets Total" frame: a neutral dark gray, distinct from any
    # individual side bet's own color, since it's a summary line rather
    # than a specific bet's result. True gray needs the extended palette;
    # on a basic 8-color terminal, black is the closest approximation.
    gray_bg = 238 if curses.COLORS >= 256 else curses.COLOR_BLACK
    curses.init_pair(SIDEBET_TOTAL_PAIR, curses.COLOR_WHITE, gray_bg)

    # Buster's wager-cell theme -- a mid-tone orange (matching the lighter
    # half of the bust-length ramp above) with black text, so its idle
    # wager cell reads as "orange" without borrowing a specific bust-length
    # stage's exact shade.
    buster_cell_bg = 216 if curses.COLORS >= 256 else curses.COLOR_YELLOW
    curses.init_pair(BUSTER_CELL_PAIR, curses.COLOR_BLACK, buster_cell_bg)

    # Standard main-bet settlement: a "grass" green distinctly darker than
    # Star21's own green (pair 10) so the two never read as the same color
    # side by side. True dark green needs the extended palette; on a basic
    # 8-color terminal there's no darker shade available, so it falls back
    # to plain green (still correct, just less differentiated from Star21).
    dark_green = 22 if curses.COLORS >= 256 else curses.COLOR_GREEN
    curses.init_pair(STANDARD_SETTLEMENT_PAIR, curses.COLOR_WHITE, dark_green)

    # An immediate player blackjack: dark purple background (distinct from
    # every other banner on screen) with yellow text. True dark purple
    # needs the extended palette; on a basic 8-color terminal, magenta is
    # the closest available approximation.
    dark_purple = 54 if curses.COLORS >= 256 else curses.COLOR_MAGENTA
    curses.init_pair(PLAYER_BJ_PAIR, curses.COLOR_YELLOW, dark_purple)

    # Player bust: a deep red, distinctly darker than the table-status
    # banner's own red (pair 5) so the two "red" banners don't blur
    # together. Falls back to plain red on a basic 8-color terminal.
    deep_red = 88 if curses.COLORS >= 256 else curses.COLOR_RED
    curses.init_pair(BUST_PAIR, curses.COLOR_WHITE, deep_red)

    # A hand beaten by a confirmed dealer blackjack: maroon, darker still
    # than both the top status bar's red (pair 5) and the bust deep-red
    # above, with white text -- red-on-purple read poorly, white is a
    # clean, unambiguous swap. Falls back to plain red on a basic
    # 8-color terminal (no darker red is available there).
    maroon = 52 if curses.COLORS >= 256 else curses.COLOR_RED
    curses.init_pair(DEALER_BJ_PAIR, curses.COLOR_WHITE, maroon)

    # Insurance: a beige background with black text, distinct from every
    # other side-bet color -- shown whether it wins or loses, so it reads
    # as its own neutral "this is what insurance did" notice rather than
    # borrowing a win/loss color. True beige needs the extended palette;
    # on a basic 8-color terminal, white is the closest approximation.
    beige = 230 if curses.COLORS >= 256 else curses.COLOR_WHITE
    curses.init_pair(INSURANCE_PAIR, curses.COLOR_BLACK, beige)


DEAL_FRAME_MS = 250  # pause between each card of the initial deal animation


def _animate_deal(stdscr, session: GameSession, round_: Round) -> None:
    """Reveals the round's already-dealt initial cards one at a time, in
    the same traditional table order they were actually drawn from the
    shoe in (rightmost active spot first, working left, dealer last each
    pass -- see engine.table_order/initial_deal_sequence), instead of the
    whole table appearing at once. The round's outcome (peek results,
    even any instant blackjack settlement) is already fully decided by
    this point -- this is purely a progressive reveal of it on screen."""
    total_steps = len(initial_deal_sequence(round_.play_order))
    for step in range(1, total_steps + 1):
        render(stdscr, session, round_, "", "", deal_progress=step)
        curses.napms(DEAL_FRAME_MS)


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
        # No summary text needed here -- the per-spot settlement/side-bet
        # banner rows already show every hand's outcome, and _main's own
        # idle-timeout redraws keep the side-bet label(s) cycling from
        # here on (see _sidebet_banner_lines) without any forced pause.
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
    if stripped == "stats":
        render_stats_screen(stdscr, session)
        return ""
    return commands.handle_command(raw, session)


def _hit_test_cell(cell_rects: CellRects, my: int, mx: int) -> Optional[Union[str, Tuple[int, int]]]:
    for key, (y, x, h, w) in cell_rects.items():
        if y <= my < y + h and x <= mx < x + w:
            return key
    return None


def _main(stdscr) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    # Non-blocking-with-timeout getch() so the loop wakes up on its own to
    # redraw during genuine idle time (e.g. the side-bet win banner's flash
    # animation), not only when the player presses a key. getch() returns
    # -1 on timeout; every branch below that only acts on specific keys
    # already ignores -1, and it's bailed out of immediately besides.
    stdscr.timeout(200)
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
    # Typing a command requires clicking the CLI input line first, the same
    # way typing a wager requires clicking (or arrow-navigating to) a wager
    # cell -- disambiguates which one digits/letters and RETURN apply to.
    # "wager" is the default so keyboard-only play works exactly as before.
    input_focus = "wager"

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

            cell_rects = render(stdscr, session, round_, buffer, message, bet_row, bet_col, bet_edit_buffer, input_focus)
            ch = stdscr.getch()

            if ch == -1:  # idle timeout tick, no real key -- just loop back and redraw
                continue

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
                    if hit == "cli":
                        commit_bet_cell()
                        input_focus = "cli"
                    elif hit is not None:
                        commit_bet_cell()
                        bet_row, bet_col = hit
                        input_focus = "wager"
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
                    curses.flushinp()  # discard any keys queued up during the response/animation above
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
                    curses.flushinp()  # discard any keys queued up during the response/animation above
                    continue

            elif round_ is not None and round_.phase == Phase.DOUBLE_BLACKJACK and buffer == "":
                handled = True
                if ch in (ord("d"), ord("D")):
                    message = ""
                    round_.respond_double_blackjack(True)
                elif ch in RETURN_KEYS:
                    message = ""
                    round_.respond_double_blackjack(False)
                else:
                    handled = False
                if handled:
                    msg = _after_engine_change(round_, session, stdscr)
                    if msg is not None:
                        message = msg
                    curses.flushinp()  # discard any keys queued up during the response/animation above
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
                        curses.flushinp()  # discard any keys queued up during the action/animation above
                    continue

            elif round_ is not None and round_.phase == Phase.SETTLED and buffer == "" and ch in RETURN_KEYS:
                round_ = None
                if session.ensure_shoe_ready():
                    _blink_new_shoe(stdscr, session, None)
                    message = "New shoe shuffled in. Ready for the next round."
                else:
                    message = ""
                # Discard any further RETURNs/clicks queued up while the
                # settlement banners were cycling -- otherwise a player who
                # multi-pressed RETURN to be sure can end up instantly
                # re-dealing (or even acting on) the *next* round from
                # keys that were only ever meant for this one.
                curses.flushinp()
                continue

            elif round_ is None:
                if ch == ord("/") and input_focus != "cli":
                    # Same effect as clicking the CLI line: commit whatever
                    # wager edit was in progress, then hand focus to the
                    # command input -- a keyboard-only equivalent of the click.
                    commit_bet_cell()
                    input_focus = "cli"
                    continue
                if ch == curses.KEY_LEFT:
                    commit_bet_cell()
                    # Step by actual screen position, not raw spot index --
                    # spot 0 ("Hand #1") sits in the middle column, so a
                    # plain bet_col-1 would jump the wrong way visually.
                    screen_slot = max(0, SPOT_SCREEN_ORDER[bet_col] - 1)
                    bet_col = SPOT_SCREEN_ORDER[screen_slot]
                    input_focus = "wager"
                    continue
                if ch == curses.KEY_RIGHT:
                    commit_bet_cell()
                    screen_slot = min(NUM_SPOT_COLUMNS - 1, SPOT_SCREEN_ORDER[bet_col] + 1)
                    bet_col = SPOT_SCREEN_ORDER[screen_slot]
                    input_focus = "wager"
                    continue
                if ch == curses.KEY_UP:
                    commit_bet_cell()
                    rows = enabled_rows()
                    idx = rows.index(bet_row) if bet_row in rows else 0
                    bet_row = rows[max(0, idx - 1)]
                    input_focus = "wager"
                    continue
                if ch == curses.KEY_DOWN:
                    commit_bet_cell()
                    rows = enabled_rows()
                    idx = rows.index(bet_row) if bet_row in rows else 0
                    bet_row = rows[min(len(rows) - 1, idx + 1)]
                    input_focus = "wager"
                    continue
                max_len = WAGER_MAX_LEN if bet_row == 0 else SIDEBET_MAX_LEN
                if input_focus == "wager" and ord("0") <= ch <= ord("9") and len(bet_edit_buffer) < max_len:
                    bet_edit_buffer += chr(ch)
                    continue
                if input_focus == "wager" and ch in (curses.KEY_BACKSPACE, 127, 8) and bet_edit_buffer:
                    bet_edit_buffer = bet_edit_buffer[:-1]
                    continue
                if ch in RETURN_KEYS:
                    if input_focus == "wager" and bet_edit_buffer:
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
                        curses.flushinp()  # a queued key shouldn't fire mid-animation as an early action
                        _animate_deal(stdscr, session, round_)
                        msg = _after_engine_change(round_, session, stdscr)
                        if msg is not None:
                            message = msg
                        curses.flushinp()  # ...or land as a snap decision the instant the deal finishes
                    continue
                if input_focus != "cli" and 32 <= ch < 127:
                    # Not focused on the CLI -- typing a command needs a
                    # click there first (see input_focus above), so a
                    # stray letter/digit here (nothing else claimed it,
                    # e.g. the wager cell is already full) is just dropped
                    # rather than leaking into the command buffer.
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
                input_focus = "wager"
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
