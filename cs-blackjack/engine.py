from __future__ import annotations

import copy
import random
from types import SimpleNamespace
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Dict, Iterator, List, Optional, Tuple

from .cards import Card, Shoe, hilo_value
from .dealer import play_dealer_hand
from .hand import Hand
from .history import HistoryError
from .rules import (
    DOUBLE_DECK_MAX_PENETRATION,
    RANDOM_PENETRATION_RANGE,
    SINGLE_DECK_MAX_HANDS,
    SINGLE_DECK_MAX_SPLIT_HANDS,
    Rules,
    min_cards_to_deal,
)
from .sidebets import (
    buster_table_key,
    evaluate_dealer_buster,
    evaluate_power_poker,
    evaluate_star21,
    evaluate_star21_double_deck,
    side_bet_allowed,
    star21_table_key,
)
from .stats import Stats

if TYPE_CHECKING:  # pragma: no cover
    from .history import HistoryDB

OUTCOME_LABELS = {
    "player_win": "Win",
    "dealer_win": "Lose",
    "push": "Push",
    "surrender": "Surrendered",
}

SIDE_BET_KEYS = ("power_poker", "star21", "dealer_buster")
SIDE_BET_LABELS = {"power_poker": "Power Poker", "star21": "Star 21", "dealer_buster": "Dealer Buster"}

# Spot index -> its on-screen column slot (0=left, 1=middle, 2=right). Spot 0
# ("Hand #1") sits front-and-center under the dealer since it's the one spot
# that's always in play; spots 1 and 2 ("Hand #2"/"#3") fill outward to the
# left and right as more hands are added. This mapping is its own inverse
# (slot -> spot uses the same array), which is what lets the UI's left/right
# arrow-key wager-grid navigation just run it both ways.
SPOT_SCREEN_ORDER = [1, 0, 2]


def table_order(num_hands: int) -> List[int]:
    """Spot indices in traditional real-table order: rightmost active
    screen position first, working left -- mirrors SPOT_SCREEN_ORDER's
    spot->screen mapping. This is the single order that dealing, the
    early-surrender/insurance prompts, and the player's turn all follow,
    so cards, decisions, and play always proceed the same direction
    around the table."""
    return sorted(range(num_hands), key=lambda i: -SPOT_SCREEN_ORDER[i])


def initial_deal_sequence(order: List[int]) -> List[Optional[int]]:
    """Flat recipient order (spot index, or None for the dealer) matching
    Round's actual two-pass initial deal -- each spot in `order` gets a
    card, then the dealer, twice. Used by the UI to animate the deal
    card-by-card in the same order it actually happened."""
    seq: List[Optional[int]] = []
    for _ in range(2):
        seq.extend(order)
        seq.append(None)
    return seq


# American-style peek: the dealer checks their hole card for blackjack whenever
# the up card is an Ace or any ten-value card. Insurance/even money are only
# ever offered on an Ace up card -- a ten-value peek is silent (no side bet),
# it just protects the player from playing (and doubling/splitting) into a
# dealer blackjack that's already a done deal.
PEEK_RANKS = {"A", "10", "J", "Q", "K"}


class Phase(Enum):
    EARLY_SURRENDER = auto()
    INSURANCE = auto()
    DOUBLE_BLACKJACK = auto()  # only reachable with rules.double_blackjack on
    PLAYER_TURN = auto()
    DEALER_TURN = auto()
    REVEAL = auto()  # flipping any face-down double-down cards, just before settlement
    SETTLED = auto()


@dataclass
class ActiveTableRules:
    """A snapshot of the handful of rules that only take effect at the next
    shuffle (blackjack payout, dealer soft-17 behavior), captured at the
    exact moment a shoe is actually cut. session.rules may already hold a
    newer value the player queued up for the *next* shoe -- this is what
    the *current* shoe (and the round being played against it) actually
    uses, so a round never finishes under different rules than it started
    with, and the UI can show what's really in effect rather than what's
    merely been typed in. Deck count and penetration don't need their own
    copy here -- the live Shoe object already carries its own num_decks/
    penetration, which is exactly this same "as of last cut" snapshot."""
    blackjack_payout: float
    hit_soft_17: bool


class InsufficientFundsError(Exception):
    def __init__(self, needed: float, available: float):
        super().__init__(f"Need ${needed:,.2f} but only ${available:,.2f} available")
        self.needed = needed
        self.available = available


class NoWagerError(Exception):
    def __init__(self, hand_index: int):
        super().__init__(f"Set a wager for Hand {hand_index + 1} before dealing.")
        self.hand_index = hand_index


class BelowMinimumWagerError(Exception):
    def __init__(self, hand_index: int, wager: float, table_min: float):
        super().__init__(
            f"Hand {hand_index + 1}'s wager (${wager:,.2f}) is below the table minimum (${table_min:,.2f})."
        )
        self.hand_index = hand_index


@dataclass
class Spot:
    """One of the 1-3 hands the player chose to play this round (pre-split)."""

    index: int
    hands: List[Hand] = field(default_factory=list)
    insurance_wager: float = 0.0
    side_bet_wagers: Dict[str, float] = field(default_factory=dict)
    side_bet_snapshot: List[Card] = field(default_factory=list)


@dataclass
class SideBetResult:
    spot_index: int
    name: str
    wager: float
    label: Optional[str]
    payout_multiplier: float
    win_amount: float
    bet_key: str = ""  # "power_poker" | "star21" | "dealer_buster" | "insurance"
    category_key: Optional[str] = None  # payout-table key that hit, e.g. "royalflush" (None on a loss)


@dataclass
class HandResult:
    spot_index: int
    hand: Hand
    outcome: str  # player_win | dealer_win | push | surrender
    payout: float  # total credited to bankroll for this hand (0 if lost outright)


class GameSession:
    """Long-lived state that persists across rounds: rules, bankroll, shoe, stats, wagers."""

    def __init__(
        self,
        bankroll: float,
        rules: Rules,
        wagers: Optional[List[float]] = None,
        side_bet_wagers: Optional[List[Dict[str, float]]] = None,
        history: Optional["HistoryDB"] = None,
    ):
        self.history = history
        self.rules = rules
        self.bankroll = bankroll
        # Nothing in the game counts stats: the history database does, and
        # replaces this snapshot (HistoryDB._refresh_stats) whenever a
        # session starts, a shoe is cut, or a round is recorded. Without a
        # database it just stays all zeros.
        self.stats = Stats()
        self.shoe = self._new_shoe()
        self._enforce_sidebet_deck_gate()
        self.active_rules = ActiveTableRules(rules.blackjack_payout, rules.hit_soft_17)
        self.wagers: List[float] = list(wagers) if wagers else [rules.default_bet, 0.0, 0.0]
        self.side_bet_wagers: List[Dict[str, float]] = (
            [dict(d) for d in side_bet_wagers]
            if side_bet_wagers
            else [{key: 0.0 for key in SIDE_BET_KEYS} for _ in range(3)]
        )
        self._quit = False
        self.pending_confirmation: Optional[str] = None  # "newshoe" | "newsession" | "bank_reset", awaiting a RETURN to confirm
        self.pending_restore: Optional[str] = None  # backup name awaiting the literal word "confirm"
        if self.history is not None:
            self.history.start_session(self)
            self.history.shoe_cut(self, "start")

    def _enforce_sidebet_deck_gate(self) -> None:
        """Power Poker (3+ decks) and Star 21 (2+ decks) are firmly disabled
        below their deck-count floor -- called right after (re)cutting the
        shoe so a rule flag left ON from a higher deck count (or loaded from
        a stale persisted session) can't silently stay enabled against a
        shoe that no longer supports it. Dealer Buster has no such floor."""
        for key in ("power_poker", "star21"):
            rule = getattr(self.rules, key)
            if rule.enabled and not side_bet_allowed(key, self.shoe.num_decks):
                rule.enabled = False

    def _commit_active_rules(self) -> None:
        """Snapshot the next-shuffle-only rules as of right now -- called
        whenever a shoe is actually (re)cut, so the newly active shoe is
        paired with whatever those rules currently are."""
        self.active_rules = ActiveTableRules(self.rules.blackjack_payout, self.rules.hit_soft_17)

    @property
    def has_pending_rule_changes(self) -> bool:
        """True if any next-shuffle-only rule (deck count, penetration,
        blackjack payout, dealer soft-17) has been changed since the
        current shoe was cut, and so differs from what's actually active."""
        return (
            self.rules.num_decks != self.shoe.num_decks
            or abs(self._target_penetration(self.shoe.num_decks) - self.shoe.penetration) > 1e-9
            or abs(self.rules.blackjack_payout - self.active_rules.blackjack_payout) > 1e-9
            or self.rules.hit_soft_17 != self.active_rules.hit_soft_17
        )

    def adjust_bankroll(self, amount: float) -> None:
        self.bankroll += amount

    def set_bankroll(self, amount: float) -> None:
        self.bankroll = amount

    def can_afford(self, amount: float) -> bool:
        return self.bankroll >= amount

    def request_quit(self) -> None:
        self._quit = True

    @property
    def quit_requested(self) -> bool:
        return self._quit

    def _roll_penetration(self) -> None:
        """Re-rolls rules.penetration to a fresh random value (see
        "deckpen rand") right before a new shoe is actually cut -- a no-op
        unless that mode is on. Setting it here, immediately before the new
        Shoe is built from the same field, means the shoe's own penetration
        always matches rules.penetration right after the cut, so this never
        trips has_pending_rule_changes the way a mid-shoe rule edit would."""
        if self.rules.random_penetration:
            lo, hi = RANDOM_PENETRATION_RANGE
            self.rules.penetration = round(random.uniform(lo, hi), 2)

    def _target_penetration(self, num_decks: int) -> float:
        """The cut-card depth a `num_decks` shoe is cut with under the current
        rules: rules.penetration, except that a two-deck shoe is never cut
        deeper than DOUBLE_DECK_MAX_PENETRATION."""
        if num_decks == 2:
            return min(self.rules.penetration, DOUBLE_DECK_MAX_PENETRATION)
        return self.rules.penetration

    def _min_cards_left(self, num_decks: int) -> int:
        """Fewest cards a shoe may be left with before it's cut, for the
        number of hands currently being played (see rules.min_cards_to_deal)."""
        return min_cards_to_deal(num_decks, self.rules.num_hands)

    def _new_shoe(self) -> Shoe:
        """A freshly shuffled shoe for the current rules, with the deck-size
        limits applied: on a single deck, hands above the maximum are cut back
        to it (whatever set them -- an older save, or a 3-hand game about to
        switch to one deck)."""
        if self.rules.num_decks == 1:
            self.rules.num_hands = min(self.rules.num_hands, SINGLE_DECK_MAX_HANDS)
        return Shoe(
            self.rules.num_decks,
            self._target_penetration(self.rules.num_decks),
            min_cards_left=self._min_cards_left(self.rules.num_decks),
        )

    def split_hand_limit(self) -> int:
        """Most hands one spot can split into right now: the 'splitmax' rule,
        held to one split per hand (2 hands) while a single-deck shoe is in
        play. The rule itself is left alone, so it applies again on any
        multi-deck shoe."""
        limit = self.rules.split_max_hands
        return min(limit, SINGLE_DECK_MAX_SPLIT_HANDS) if self.shoe.num_decks == 1 else limit

    def rsa_hand_limit(self) -> int:
        """Same, for resplitting aces (the 'rsa ... maxsplit' rule): on a
        single deck that means aces can be split once but never resplit."""
        limit = self.rules.rsa_max_hands
        return min(limit, SINGLE_DECK_MAX_SPLIT_HANDS) if self.shoe.num_decks == 1 else limit

    def try_set_num_hands(self, n: int) -> Optional[str]:
        """Set how many hands are played per round. Returns an error string,
        or None on success. A single-deck shoe allows at most SINGLE_DECK_MAX_
        HANDS; within that it can be changed between any two rounds."""
        if self.shoe.num_decks == 1 and n > SINGLE_DECK_MAX_HANDS:
            return f"Single-deck games are limited to {SINGLE_DECK_MAX_HANDS} hands."
        self.rules.num_hands = n
        self.shoe.min_cards_left = self._min_cards_left(self.shoe.num_decks)  # more hands need more cards
        return None

    def _cut_shoe(self, reason: str) -> None:
        """Retire the current shoe and cut a brand-new one -- the single
        path every reshuffle after the first goes through, so the history
        log sees each one (with `reason`) no matter what triggered it."""
        self._roll_penetration()
        if self.history is not None:
            self.history.shoe_retired(self)
        self.shoe = self._new_shoe()
        self._enforce_sidebet_deck_gate()
        self._commit_active_rules()
        if self.history is not None:
            self.history.shoe_cut(self, reason)

    def ensure_shoe_ready(self) -> bool:
        """Cut a fresh shoe if the cut card was reached, or if fewer cards remain
        than the shoe needs for another round (see rules.min_cards_to_deal:
        it depends on the deck count and, above two decks, the hands in play).

        Called right after a round settles (and once at session start) --
        deliberately NOT at deal time. A round that crosses the cut card
        still finishes with the shoe it started with; the player is meant to
        see the resulting (possibly reset) true count on the betting screen
        *before* sizing their next wager, not have it swapped out from under
        an already-placed bet.
        """
        self.shoe.min_cards_left = self._min_cards_left(self.shoe.num_decks)
        if self.shoe.needs_cut:
            self._cut_shoe("penetration")
            return True
        return False

    def reset_shoe(self, reason: str = "newshoe") -> None:
        """Forcibly cut a brand-new shoe, e.g. from the 'newshoe' command."""
        self._cut_shoe(reason)

    def reshuffle_mid_round(self, round_: "Round") -> None:
        """The failsafe for a shoe that runs out of cards in the middle of a
        round: the discards are shuffled and the round carries on, as at a
        real table. Every card drawn this round stays where it is; everything
        else -- including cards from earlier rounds -- goes back into a fresh
        shuffle of the same shoe (see Shoe.reshuffle_around).

        The history log closes the exhausted shoe (its never-dealt part is
        empty) and opens a new one, and remembers which shoe the round began
        on so the round's rows can say so. Rules pending for the next shuffle
        are NOT applied: a round never finishes under different rules than it
        started with."""
        if self.history is not None:
            if round_.history_shoe_id is None:
                round_.history_shoe_id = self.history.shoe_id
            self.history.shoe_retired(self)
        self.shoe.reshuffle_around(round_.drawn)
        round_.reshuffled_mid_round = True
        # The count shown on screen is in the new shuffle's terms from here on:
        # nothing was dealt from it before this round's own cards.
        round_.count_base = (0, 0)
        if self.history is not None:
            self.history.shoe_cut(self, "mid_round")

    def reset_bankroll(self) -> None:
        """Reset the bankroll to its configured default (see 'bank default'),
        e.g. from the 'bank reset' command. Touches nothing else."""
        self.bankroll = self.rules.default_bankroll

    def reset_session(self, reason: str = "newsession") -> None:
        """Start a new session on a brand-new shoe. The bankroll is left
        untouched -- see reset_bankroll().

        The history log closes out the old session first and opens the new
        one before the new shoe is cut, so that shoe is logged under the
        session it actually belongs to; the session stats the panels show
        start over because the new session has no hands yet."""
        if self.history is not None and self.history.end_session(self, reason):
            self.history.start_session(self)  # (if the old one couldn't be closed -- database busy -- the log just carries on in it)
        self.reset_shoe(reason)

    def restore_backup(self, name: str) -> Optional[str]:
        """Replace ALL current data (history database, bankroll, rules,
        wagers) with a saved backup, then start a fresh session on a new
        shoe. Returns an error string, or None on success.
        The caller must make sure no round is in progress."""
        if self.history is None:
            return "History database is unavailable."
        try:
            bankroll, rules, wagers, side_bet_wagers = self.history.restore(self, name)
        except HistoryError as exc:
            return str(exc)
        self.bankroll = bankroll
        self.rules = rules
        self.wagers = wagers
        self.side_bet_wagers = side_bet_wagers
        self.history.start_session(self)
        self.reset_shoe("restore")
        return None

    def try_set_wager(self, hand_index: int, amount: float) -> Optional[str]:
        """Set the main wager for a hand slot. Returns an error string, or None on success.

        0 is always allowed (it just means "no wager set yet" -- NoWagerError
        catches that at deal time with its own message); any nonzero amount
        must fall within [table_min, table_max].
        """
        if amount < 0:
            return "Wager cannot be negative."
        if amount > self.rules.table_max:
            return f"Max Bet {self.rules.table_max:,.0f}"
        if 0 < amount < self.rules.table_min:
            return f"Min Bet {self.rules.table_min:,.0f}"
        self.wagers[hand_index] = amount
        return None

    def try_set_side_bet_wager(self, hand_index: int, key: str, amount: float) -> Optional[str]:
        rule = getattr(self.rules, key)
        if not rule.enabled:
            return f"{SIDE_BET_LABELS[key]} is not enabled."
        if amount < 0:
            return "Wager cannot be negative."
        if amount > rule.max_bet:
            return f"Max Bet {rule.max_bet:,.0f}"
        if 0 < amount < rule.min_bet:
            return f"Min Bet {rule.min_bet:,.0f}"
        self.side_bet_wagers[hand_index][key] = amount
        return None


def try_start_round(session: GameSession) -> Tuple[Optional["Round"], Optional[str]]:
    if session.shoe.num_decks == 1 and session.rules.num_hands > SINGLE_DECK_MAX_HANDS:
        # Belt and braces: try_set_num_hands and the shoe cut already keep
        # this true, but a round must never be dealt in violation of it.
        return None, f"Single-deck games are limited to {SINGLE_DECK_MAX_HANDS} hands."
    try:
        return Round(session), None
    except (InsufficientFundsError, NoWagerError, BelowMinimumWagerError) as exc:
        return None, str(exc)


class Round:
    """A full deal-to-settlement cycle for one or more simultaneous hands."""

    def __init__(self, session: GameSession):
        self.session = session
        self.rules = session.rules

        # Baselines captured before this round touches anything -- lets the
        # UI reconstruct "stats/count as of just before this round" for as
        # long as it needs to stay hidden (see visible_counts() below and
        # ui.py's _display_stats()), without engine.py needing to know
        # anything about *why* the UI wants that (settlement banners vs.
        # progressive card-reveal animation are entirely presentation
        # concerns -- this just gives it the numbers to work with).
        self.stats_before = copy.deepcopy(session.stats)
        self.running_count_before = session.shoe.running_count
        self.cards_dealt_before = session.shoe.cards_dealt
        # The same three numbers a player sees when sizing this round's
        # wager, plus the bankroll before that wager comes off it -- kept
        # for the history log.
        self.true_count_before = session.shoe.true_count
        self.bankroll_before = session.bankroll

        # Every card this round has taken from the shoe, in the order it was
        # drawn (all of them are on the table until the round ends) -- what
        # a mid-round reshuffle keeps in play (see _draw). It's tracked here
        # rather than worked out from the hands because splitting shuffles
        # cards between hands mid-draw.
        self.drawn: List[Card] = []
        # True if the shoe ran out during this round and the discards were
        # shuffled back in (GameSession.reshuffle_mid_round). When it did,
        # the *_before figures above and history_shoe_id describe the shoe the
        # round STARTED on; the cards after the reshuffle came from a new one.
        self.reshuffled_mid_round = False
        self.reshuffle_announced = False  # the UI has shown the player what happened
        self.history_shoe_id: Optional[int] = None  # set by the history log if the shoe changed under this round
        # (running count, cards dealt) the visible count is measured from --
        # the round-start values, reset to zero if the shoe is reshuffled
        # mid-round (a new shuffle has had nothing dealt from it but this
        # round's own cards).
        self.count_base: Tuple[int, int] = (self.running_count_before, self.cards_dealt_before)

        num_hands = self.rules.num_hands

        per_hand_wager: List[float] = []
        per_hand_sidebets: List[Dict[str, float]] = []
        total_needed = 0.0
        for i in range(num_hands):
            wager = session.wagers[i]
            if wager <= 0:
                raise NoWagerError(i)
            if wager < self.rules.table_min:
                # Can happen if tablemin was raised after wagers were already
                # (stickily) set from a previous round.
                raise BelowMinimumWagerError(i, wager, self.rules.table_min)
            per_hand_wager.append(wager)
            total_needed += wager

            sb: Dict[str, float] = {}
            for key in SIDE_BET_KEYS:
                side_rule = getattr(self.rules, key)
                # side_bet_allowed() is a belt-and-suspenders check against
                # the *live* shoe -- _enforce_sidebet_deck_gate() already
                # keeps side_rule.enabled in sync whenever the shoe is cut,
                # so this should never actually differ in practice.
                available = side_rule.enabled and side_bet_allowed(key, session.shoe.num_decks)
                amt = session.side_bet_wagers[i].get(key, 0.0) if available else 0.0
                if amt > side_rule.max_bet:
                    amt = side_rule.max_bet
                if 0 < amt < side_rule.min_bet:
                    # A stale wager now below a since-raised minimum is just
                    # not placed, rather than blocking the whole round --
                    # side bets are optional, the main wager is not.
                    amt = 0.0
                sb[key] = amt
                total_needed += amt
            per_hand_sidebets.append(sb)

        if not session.can_afford(total_needed):
            raise InsufficientFundsError(total_needed, session.bankroll)
        session.adjust_bankroll(-total_needed)

        self.dealer_hand = Hand()
        self.spots: List[Spot] = [
            Spot(index=i, hands=[Hand(bet=per_hand_wager[i])], side_bet_wagers=per_hand_sidebets[i])
            for i in range(num_hands)
        ]

        # Table order: rightmost active screen spot first, working left --
        # see table_order() -- reused for dealing, early-surrender/insurance
        # prompts, and the player's turn, so the whole round proceeds
        # around the table in one consistent direction.
        self.play_order: List[int] = table_order(num_hands)

        # Standard deal order: each active spot gets a card (in table
        # order), then the dealer, twice.
        for _ in range(2):
            for i in self.play_order:
                self.spots[i].hands[0].add_card(self._draw())
            self.dealer_hand.add_card(self._draw())

        # Side bets key off each spot's original two cards -- snapshot them
        # now since a hand's cards may change if it's hit.
        for spot in self.spots:
            spot.side_bet_snapshot = list(spot.hands[0].cards)
        self.dealer_up: Card = self.dealer_hand.cards[0]

        self.dealer_revealed = False
        self.dealer_has_blackjack = False
        self.peeked = False
        self.results: List[HandResult] = []
        self.side_bet_results: List[SideBetResult] = []
        # (spot index, bet key) -> the payout category that occurred for that
        # spot's side bet, wagered or not (None = no category hit). Feeds the
        # history log's per-hand side-bet columns.
        self.sidebet_categories: Dict[Tuple[int, str], Optional[str]] = {}

        self._play_cursor = 0
        self._current_hand_index = 0
        self._prelim_index = 0
        self._dealer_draw_iter: Optional[Iterator[Hand]] = None

        # Power Poker and Star 21 only key off each spot's first two cards
        # plus the dealer's up card -- already fully known -- so they
        # settle immediately here, before any early-surrender/insurance
        # decision or player action. Dealer Buster can't resolve until the
        # dealer's hand is fully played out, so it waits and settles
        # alongside the final main-wager settlement instead (_settle_buster).
        self._settle_pp_s21()

        if self.dealer_up.rank in PEEK_RANKS:
            if self.rules.surrender_early and self.dealer_up.rank == "A":
                self.phase = Phase.EARLY_SURRENDER
                self._advance_early_surrender_cursor()
            elif self.dealer_up.rank == "A":
                self.phase = Phase.INSURANCE
                self._advance_insurance_cursor()
            else:
                self._resolve_peek()
        else:
            # No peek possible on a 2-9 up card (a natural blackjack always
            # needs an Ace or ten-value up card) -- any player blackjack is
            # therefore already a guaranteed win, so it settles right away
            # (or, with double_blackjack on, is offered a double instead)
            # rather than waiting on the rest of the round.
            self._offer_blackjack_doubles_or_proceed()

    # ------------------------------------------------------------------
    # Early surrender / insurance / even money / dealer peek
    # ------------------------------------------------------------------

    def _draw(self) -> Card:
        """Take the next card for this round -- every draw the round makes,
        the dealer's included, goes through here. If the shoe is empty the
        discards are shuffled back in first (GameSession.reshuffle_mid_round)
        and the round carries on."""
        shoe = self.session.shoe
        if shoe.cards_remaining == 0:
            self.session.reshuffle_mid_round(self)
        card = shoe.draw()
        self.drawn.append(card)
        return card

    def current_prelim_spot(self) -> Optional[Spot]:
        if (
            self.phase in (Phase.EARLY_SURRENDER, Phase.INSURANCE, Phase.DOUBLE_BLACKJACK)
            and self._prelim_index < len(self.play_order)
        ):
            return self.spots[self.play_order[self._prelim_index]]
        return None

    def insurance_prompt_kind(self, spot: Spot) -> str:
        """'even_money' or 'insurance', for the UI to pick prompt wording."""
        return "even_money" if spot.hands[0].is_blackjack else "insurance"

    def _advance_early_surrender_cursor(self) -> None:
        while self._prelim_index < len(self.play_order):
            hand = self.spots[self.play_order[self._prelim_index]].hands[0]
            # A player blackjack is never offered early surrender -- it's
            # only ever eligible for even money, offered next in the
            # INSURANCE phase.
            if hand.surrendered or hand.is_blackjack:
                self._prelim_index += 1
                continue
            return
        self._prelim_index = 0
        if self.dealer_up.rank == "A":
            self.phase = Phase.INSURANCE
            self._advance_insurance_cursor()
        else:
            self._resolve_peek()

    def _advance_insurance_cursor(self) -> None:
        while self._prelim_index < len(self.play_order):
            if self.spots[self.play_order[self._prelim_index]].hands[0].surrendered:
                self._prelim_index += 1
                continue
            return
        self._resolve_peek()

    def respond_early_surrender(self, accept: bool) -> None:
        if self.phase != Phase.EARLY_SURRENDER:
            return
        spot = self.spots[self.play_order[self._prelim_index]]
        if accept:
            # Settles immediately, like a real table and like late surrender
            # (see perform_action's "surrender" branch) -- half the wager
            # comes back right away rather than waiting on the rest of the
            # round, which hasn't even reached the peek yet at this point.
            hand = spot.hands[0]
            hand.surrendered = True
            payout, outcome = self._settle_hand(hand, dealer_bust=False, dealer_value=0, dealer_bj=False)
            self._record_settlement(spot, hand, outcome, payout)
        self._prelim_index += 1
        self._advance_early_surrender_cursor()

    def respond_insurance(self, accept: bool) -> None:
        if self.phase != Phase.INSURANCE:
            return
        spot = self.spots[self.play_order[self._prelim_index]]
        hand = spot.hands[0]
        if accept:
            if hand.is_blackjack:
                # Even money is an immediate, self-contained settlement --
                # it doesn't wait on the dealer's hole card (that's the
                # whole point of taking it) or the rest of the round.
                hand.even_money_taken = True
                payout, outcome = self._settle_hand(hand, dealer_bust=False, dealer_value=0, dealer_bj=False)
                self._record_settlement(spot, hand, outcome, payout)
            else:
                wager = hand.bet / 2
                if self.session.can_afford(wager):
                    spot.insurance_wager = wager
                    self.session.adjust_bankroll(-wager)
        self._prelim_index += 1
        self._advance_insurance_cursor()

    def _resolve_peek(self) -> None:
        self.peeked = True
        # Insurance settles the instant the hole card is peeked -- 2:1 if
        # the dealer has blackjack, forfeited otherwise -- independent of
        # whatever the rest of the round does next.
        self._settle_insurance()
        if self.dealer_hand.is_blackjack:
            self.dealer_has_blackjack = True
            self.dealer_revealed = True
            self._settle_round()
            self.phase = Phase.SETTLED
        else:
            # Dealer confirmed clean -- any player blackjack that didn't
            # take even money is now a guaranteed win, so settle it right
            # away (or, with double_blackjack on, offer a double instead)
            # rather than making it wait on the rest of the round.
            self._offer_blackjack_doubles_or_proceed()

    # ------------------------------------------------------------------
    # Player turn
    # ------------------------------------------------------------------

    def current_player_hand(self) -> Optional[Tuple[Spot, Hand]]:
        if self.phase != Phase.PLAYER_TURN or self._play_cursor >= len(self.play_order):
            return None
        spot = self.spots[self.play_order[self._play_cursor]]
        if self._current_hand_index >= len(spot.hands):
            return None
        return spot, spot.hands[self._current_hand_index]

    def _hand_needs_play(self, spot: Spot, hand: Hand) -> bool:
        if hand.is_resolved:
            return False
        if hand.is_split_aces and len(hand.cards) >= 2:
            return (
                self.rules.rsa
                and hand.cards[-1].rank == "A"
                and len(spot.hands) < self.session.rsa_hand_limit()
            )
        return True

    def legal_actions(self, spot: Spot, hand: Hand) -> set:
        if not self._hand_needs_play(spot, hand):
            return set()
        if hand.is_split_aces and len(hand.cards) >= 2:
            # Only reachable when a resplit is actually available (see
            # _hand_needs_play) -- resplitting is the player's choice, not
            # forced, so standing pat on the one-card hand is equally legal.
            return {"split", "stand"}
        actions = {"hit", "stand"}
        if self._can_double(hand):
            actions.add("double")
        if self._can_split(spot, hand):
            actions.add("split")
        if self._can_surrender(hand):
            actions.add("surrender")
        return actions

    def _can_double(self, hand: Hand) -> bool:
        if not hand.can_double:
            return False
        if hand.is_split and not self.rules.das:
            return False
        return self.session.can_afford(hand.bet)

    def _can_split(self, spot: Spot, hand: Hand) -> bool:
        if not hand.can_split:
            return False
        if len(spot.hands) >= self.session.split_hand_limit():
            return False
        return self.session.can_afford(hand.bet)

    def _can_surrender(self, hand: Hand) -> bool:
        if self.rules.surrender == "off":
            return False
        if hand.is_split or len(hand.cards) != 2:
            return False
        if self.dealer_up.rank in PEEK_RANKS:
            # Early surrender only ever applies pre-peek, and only against an
            # Ace (see Round.__init__) -- by the time we're here that chance
            # has passed (or never existed, for a ten-value up card), so both
            # "late" and "early" fall back to ordinary post-peek surrender.
            return self.rules.surrender in ("late", "early")
        return True

    def _illegal_reason(self, action: str, spot: Spot, hand: Hand) -> str:
        if not self._hand_needs_play(spot, hand):
            return "This hand is already finished."
        if hand.is_split_aces and len(hand.cards) >= 2:
            return "Split aces get one card each -- resplit only if RSA allows it and another Ace is drawn."

        if action == "double":
            if not hand.can_double:
                return "Can't double now (already acted, or more than 2 cards)."
            if hand.is_split and not self.rules.das:
                return "Double after split is off (das off)."
            if not self.session.can_afford(hand.bet):
                return "Not enough bankroll to double."
            return "Doubling isn't allowed on this hand."

        if action == "split":
            if not hand.can_split:
                return "Those two cards can't be split."
            limit = self.session.split_hand_limit()
            if len(spot.hands) >= limit:
                if limit < self.rules.split_max_hands:
                    return "Single-deck games allow one split per hand."
                return f"Max split hands reached (splitmax {limit})."
            if not self.session.can_afford(hand.bet):
                return "Not enough bankroll to split."
            return "Splitting isn't allowed on this hand."

        if action == "surrender":
            if self.rules.surrender == "off":
                return "Surrender is disabled."
            if hand.is_split:
                return "Can't surrender a hand created by a split."
            if len(hand.cards) != 2:
                return "Surrender is only available as your first decision."
            if self.dealer_up.rank in PEEK_RANKS and self.rules.surrender not in ("late", "early"):
                return "Surrender isn't available here."
            return "Surrender isn't allowed on this hand."

        return f"'{action}' isn't allowed right now."

    def perform_action(self, action: str) -> Optional[str]:
        """Apply a hit/stand/double/split/surrender action. Returns an error
        string (and leaves state unchanged) if the action isn't legal."""
        current = self.current_player_hand()
        if current is None:
            return "No hand is awaiting an action."
        spot, hand = current
        legal = self.legal_actions(spot, hand)
        if action not in legal:
            return self._illegal_reason(action, spot, hand)

        if action == "hit":
            hand.add_card(self._draw())
            if hand.is_bust:
                # Settle a bust the instant it happens -- the wager is
                # already lost, no need to wait for the rest of the round.
                payout, outcome = self._settle_hand(hand, dealer_bust=False, dealer_value=0, dealer_bj=False)
                self._record_settlement(spot, hand, outcome, payout)
            elif hand.best_value == 21:
                hand.stood = True
        elif action == "stand":
            hand.stood = True
        elif action == "double":
            self._apply_double(spot, hand)
        elif action == "split":
            self._do_split(spot, hand)
        elif action == "surrender":
            # Surrender settles immediately too, like a real table --
            # half the wager comes back right away, not at round's end.
            hand.surrendered = True
            payout, outcome = self._settle_hand(hand, dealer_bust=False, dealer_value=0, dealer_bj=False)
            self._record_settlement(spot, hand, outcome, payout)

        self._advance_player_cursor()
        return None

    def _apply_double(self, spot: Spot, hand: Hand) -> None:
        """Doubles this hand's bet and draws its one additional card. A
        resulting bust settles immediately, unless the card is dealt face
        down (double_facedown), in which case it -- and any bust -- stays
        hidden until the REVEAL phase. Shared by an ordinary in-turn
        double and an accepted double on a natural blackjack.

        Facedown doubles are only offered on hands with little/no bust
        risk -- soft totals, or a hard total of 11 or fewer -- computed
        from the hand's original two cards before the double card is
        drawn. A hard 12+ always deals its double card face up instead,
        so a bust is immediately visible and settles right away, same as
        any other bust."""
        self.session.adjust_bankroll(-hand.bet)
        hand.bet *= 2
        hand.doubled = True
        facedown_eligible = hand.is_soft or hand.best_value <= 11
        hand.add_card(self._draw())
        if self.rules.double_facedown and facedown_eligible:
            hand.double_hidden = True
        elif hand.is_bust:
            payout, outcome = self._settle_hand(hand, dealer_bust=False, dealer_value=0, dealer_bj=False)
            self._record_settlement(spot, hand, outcome, payout)

    def _do_split(self, spot: Spot, hand: Hand) -> None:
        self.session.adjust_bankroll(-hand.bet)
        kept, moved = hand.cards[0], hand.cards[1]
        is_aces = kept.rank == "A"

        hand.cards = [kept]
        hand.is_split = True
        hand.is_split_aces = is_aces

        new_hand = Hand(cards=[moved], bet=hand.bet, is_split=True, is_split_aces=is_aces)

        hand.add_card(self._draw())
        new_hand.add_card(self._draw())
        if is_aces and self.rules.rsa_facedown:
            # Same face-down-until-reveal mechanic as a double-down card --
            # only reachable with RSA off (see commands.py), so each split
            # gets exactly one hidden card per hand, no resplit to chase.
            hand.double_hidden = True
            new_hand.double_hidden = True
        spot.hands.insert(self._current_hand_index + 1, new_hand)

    def _advance_player_cursor(self) -> None:
        while self._play_cursor < len(self.play_order):
            spot = self.spots[self.play_order[self._play_cursor]]
            while self._current_hand_index < len(spot.hands):
                hand = spot.hands[self._current_hand_index]
                if self._hand_needs_play(spot, hand):
                    return
                if hand.is_split_aces and not hand.is_resolved:
                    # A split-ace hand that was never offered a resplit
                    # decision (RSA off, no Ace drawn, or already at the
                    # resplit cap) never goes through perform_action("stand")
                    # -- mark it stood here so is_resolved/hand_value_label
                    # treat it as done and collapse its display to the
                    # single hard total it's actually standing on, instead
                    # of showing a soft "x/y" split forever.
                    hand.stood = True
                self._current_hand_index += 1
            self._play_cursor += 1
            self._current_hand_index = 0
        self._begin_dealer_turn_or_settle()

    # ------------------------------------------------------------------
    # Dealer turn
    # ------------------------------------------------------------------

    def _has_hidden_doubles(self) -> bool:
        return any(h.double_hidden for spot in self.spots for h in spot.hands)

    def _finish_dealer_turn(self) -> None:
        """Common tail once the dealer has no more cards to draw: reveal any
        face-down double-down cards first (as its own visible step), then settle."""
        if self._has_hidden_doubles():
            self.phase = Phase.REVEAL
        else:
            self._settle_round()
            self.phase = Phase.SETTLED

    def reveal_doubles(self) -> None:
        for spot in self.spots:
            for hand in spot.hands:
                hand.double_hidden = False
        self._settle_round()
        self.phase = Phase.SETTLED

    def _begin_dealer_turn_or_settle(self) -> None:
        any_live = any(
            not (h.is_bust or h.surrendered or h.even_money_taken or h.is_blackjack)
            for spot in self.spots
            for h in spot.hands
        )
        # Dealer Buster needs the dealer to play out their hand to resolve,
        # even if every player hand is already settled.
        buster_wagered = any(spot.side_bet_wagers.get("dealer_buster", 0.0) > 0 for spot in self.spots)
        need_dealer_play = any_live or buster_wagered

        if not need_dealer_play:
            self.dealer_revealed = True
            self._finish_dealer_turn()
            return

        self.dealer_revealed = True
        self.phase = Phase.DEALER_TURN
        self._dealer_draw_iter = play_dealer_hand(
            self.dealer_hand, SimpleNamespace(draw=self._draw), self.session.active_rules.hit_soft_17
        )

    def step_dealer(self) -> bool:
        """Draw one more dealer card. Returns True if the dealer is still drawing."""
        if self.phase != Phase.DEALER_TURN:
            return False
        drawn = next(self._dealer_draw_iter, None)
        if drawn is None:
            self._finish_dealer_turn()
            return False
        return True

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------

    def _settle_hand(self, hand: Hand, dealer_bust: bool, dealer_value: int, dealer_bj: bool) -> Tuple[float, str]:
        if hand.even_money_taken:
            return hand.bet * 2, "player_win"
        if hand.surrendered:
            return hand.bet * 0.5, "surrender"
        if hand.is_bust:
            return 0.0, "dealer_win"
        if hand.is_blackjack:
            if dealer_bj:
                return hand.bet, "push"
            return hand.bet * (1 + self.session.active_rules.blackjack_payout), "player_win"
        if dealer_bj:
            return 0.0, "dealer_win"
        if dealer_bust:
            return hand.bet * 2, "player_win"
        player_value = hand.best_value
        if player_value > dealer_value:
            return hand.bet * 2, "player_win"
        if player_value < dealer_value:
            return 0.0, "dealer_win"
        return hand.bet, "push"

    def _record_settlement(self, spot: Spot, hand: Hand, outcome: str, payout: float) -> None:
        """Credit a single hand's payout and record it as a HandResult right
        now, independent of the rest of the round -- used both by the
        eventual full-round settlement below and by the earlier immediate
        settlements (a lone player blackjack, an accepted even money)."""
        hand.settled = True
        self.session.adjust_bankroll(payout)
        self.results.append(HandResult(spot.index, hand, outcome, payout))

    def _settle_immediate_blackjacks(self) -> None:
        """Settle every spot's still-unsettled natural blackjack the moment
        it's known the dealer doesn't (or can't) have one of their own --
        called right after a clean peek, or immediately at deal time when
        no peek was even possible (a 2-9 up card)."""
        for spot in self.spots:
            hand = spot.hands[0]
            if hand.is_blackjack and not hand.settled:
                payout, outcome = self._settle_hand(hand, dealer_bust=False, dealer_value=0, dealer_bj=False)
                self._record_settlement(spot, hand, outcome, payout)

    def _offer_blackjack_doubles_or_proceed(self) -> None:
        """Called once it's known to be safe to resolve any lone player
        blackjacks (no peek needed, or a clean peek). With double_blackjack
        off, they settle immediately as wins, same as always. With it on,
        each one is offered a chance to double instead of an automatic 3:2
        payout -- in table order, like early surrender/insurance."""
        if not self.rules.double_blackjack:
            self._settle_immediate_blackjacks()
            self.phase = Phase.PLAYER_TURN
            self._play_cursor = 0
            self._current_hand_index = 0
            self._advance_player_cursor()
            return
        self.phase = Phase.DOUBLE_BLACKJACK
        self._prelim_index = 0
        self._advance_double_blackjack_cursor()

    def _advance_double_blackjack_cursor(self) -> None:
        while self._prelim_index < len(self.play_order):
            hand = self.spots[self.play_order[self._prelim_index]].hands[0]
            if hand.is_blackjack and not hand.settled:
                return
            self._prelim_index += 1
        # Every offer has been answered -- any blackjack that declined a
        # double (or was never offered one, e.g. a spot with no blackjack
        # at all) settles the ordinary way now.
        self._settle_immediate_blackjacks()
        self.phase = Phase.PLAYER_TURN
        self._play_cursor = 0
        self._current_hand_index = 0
        self._advance_player_cursor()

    def respond_double_blackjack(self, accept: bool) -> None:
        if self.phase != Phase.DOUBLE_BLACKJACK:
            return
        spot = self.spots[self.play_order[self._prelim_index]]
        hand = spot.hands[0]
        if accept and self.session.can_afford(hand.bet):
            # A natural blackjack (Ace + ten-value) can never bust when
            # doubled -- the extra card just settles onto a normal 12-21
            # total -- so this always turns into an ordinary, still-live
            # doubled hand rather than an immediate settlement.
            self._apply_double(spot, hand)
        self._prelim_index += 1
        self._advance_double_blackjack_cursor()

    def _settle_pp_s21(self) -> None:
        """Power Poker and Star 21 settle immediately after the deal -- both
        only key off the spot's first two cards and the dealer's up card,
        already fully known the moment dealing finishes, well before any
        early-surrender/insurance decision or player action."""
        star21_table = star21_table_key(self.session.shoe.num_decks)
        star21_fn = evaluate_star21_double_deck if star21_table == "star21_double" else evaluate_star21
        evaluators = {
            "power_poker": (SIDE_BET_LABELS["power_poker"], evaluate_power_poker, self.rules.payouts["power_poker"]),
            "star21": (SIDE_BET_LABELS["star21"], star21_fn, self.rules.payouts[star21_table]),
        }
        for spot in self.spots:
            player_cards = spot.side_bet_snapshot
            for key, (name, fn, payouts) in evaluators.items():
                # Evaluated regardless of whether it was actually wagered --
                # every category's occurrence is recorded (in sidebet_categories,
                # and from there in the history log) purely as an event, to
                # inform future payout tuning, independent of the side bet's
                # own win/loss bookkeeping.
                outcome = fn(player_cards, self.dealer_up, payouts)
                category_key = None
                if outcome:
                    category_key, label, multiplier = outcome
                else:
                    label, multiplier = None, 0.0
                self.sidebet_categories[(spot.index, key)] = category_key

                wager = spot.side_bet_wagers.get(key, 0.0)
                if wager <= 0:
                    continue
                win = wager * (1 + multiplier) if outcome else 0.0
                if win:
                    self.session.adjust_bankroll(win)
                self.side_bet_results.append(
                    SideBetResult(spot.index, name, wager, label, multiplier, win, key, category_key)
                )

    def _settle_insurance(self) -> None:
        """Insurance settles the instant the dealer's hole card is peeked
        -- paid 2:1 (a 3x return) if the dealer has blackjack, forfeited
        otherwise -- independent of the main hand(s) and of Dealer Buster."""
        dealer_bj = self.dealer_hand.is_blackjack
        for spot in self.spots:
            wager = spot.insurance_wager
            if wager <= 0:
                continue
            win = wager * 3 if dealer_bj else 0.0
            if win:
                self.session.adjust_bankroll(win)
            self.side_bet_results.append(SideBetResult(spot.index, "Insurance", wager, None, 2.0, win, "insurance"))

    def _settle_buster(self) -> None:
        """Dealer Buster can't resolve until the dealer's hand is fully
        played out, so -- unlike Power Poker and Star 21 -- it settles
        alongside the final main-wager settlement, not right after the deal.
        The outcome itself is the same for every spot (it's purely about
        the dealer's one hand), so it's evaluated -- and its occurrence
        recorded -- exactly once per round, not once per spot."""
        payouts = self.rules.payouts[buster_table_key(self.session.shoe.num_decks)]
        outcome = evaluate_dealer_buster(self.dealer_hand, payouts)
        category_key = None
        if outcome:
            category_key, label, multiplier = outcome
        else:
            label, multiplier = None, 0.0
        for spot in self.spots:
            self.sidebet_categories[(spot.index, "dealer_buster")] = category_key
            buster_wager = spot.side_bet_wagers.get("dealer_buster", 0.0)
            if buster_wager <= 0:
                continue
            win = buster_wager * (1 + multiplier) if outcome else 0.0
            if win:
                self.session.adjust_bankroll(win)
            self.side_bet_results.append(
                SideBetResult(
                    spot.index, SIDE_BET_LABELS["dealer_buster"], buster_wager, label, multiplier, win,
                    "dealer_buster", category_key,
                )
            )

    def _settle_round(self) -> None:
        dealer_bust = self.dealer_hand.is_bust
        dealer_value = self.dealer_hand.best_value
        dealer_bj = self.dealer_hand.is_blackjack

        for spot in self.spots:
            for hand in spot.hands:
                if hand.settled:
                    # Already credited and recorded earlier this round (a
                    # lone player blackjack once the dealer was confirmed
                    # clean, or an accepted even money offer) -- settling
                    # it again here would double-pay it.
                    continue
                payout, outcome = self._settle_hand(hand, dealer_bust, dealer_value, dealer_bj)
                self._record_settlement(spot, hand, outcome, payout)

        self._settle_buster()

    # ------------------------------------------------------------------
    # Display support -- Hi-Lo running/true count reveal timing
    # ------------------------------------------------------------------

    def visible_cards(self, deal_progress: Optional[int] = None) -> List[Card]:
        """Cards from THIS round the player can currently see, for Hi-Lo
        purposes -- excludes the dealer's hole card until dealer_revealed,
        any face-down double/RSA-split card until its hand's double_hidden
        clears, and, while deal_progress is given (mid initial-deal
        animation -- a step count into
        initial_deal_sequence(self.play_order)), any card whose turn in
        that sequence hasn't actually been shown on screen yet."""
        if deal_progress is not None:
            seq = initial_deal_sequence(self.play_order)
            spot_shown: Dict[int, int] = {}
            dealer_shown = 0
            for recipient in seq[:deal_progress]:
                if recipient is None:
                    dealer_shown += 1
                else:
                    spot_shown[recipient] = spot_shown.get(recipient, 0) + 1
            cards: List[Card] = []
            for spot in self.spots:
                n = spot_shown.get(spot.index, 0)
                cards.extend(spot.hands[0].cards[:n])
            if dealer_shown >= 1:
                # Only the up-card -- the deal sequence's second dealer
                # card is the hole card, which the deal animation never
                # reveals on its own (see the dealer_revealed branch below
                # for when that actually happens).
                cards.append(self.dealer_hand.cards[0])
            return cards

        cards: List[Card] = []
        for spot in self.spots:
            for hand in spot.hands:
                cards.extend(hand.cards[:-1] if hand.double_hidden else hand.cards)
        if self.dealer_revealed:
            cards.extend(self.dealer_hand.cards)
        else:
            cards.append(self.dealer_hand.cards[0])
        return cards

    def visible_counts(self, deal_progress: Optional[int] = None) -> Tuple[int, float]:
        """(running_count, true_count) as of only the cards currently
        visible to the player this round -- layered on top of the shoe's
        own count as of just before this round began (running_count_
        before/cards_dealt_before), so a hidden hole card or a still-
        animating deal never lets the count jump to its final value ahead
        of the player actually seeing the cards behind it."""
        visible = self.visible_cards(deal_progress)
        base_running, base_dealt = self.count_base
        running = base_running + sum(hilo_value(c) for c in visible)
        cards_dealt = base_dealt + len(visible)
        if cards_dealt == 0:
            return running, 0.0
        decks_remaining = max(self.session.shoe.total_cards - cards_dealt, 1) / 52
        true_count = round(running / decks_remaining * 2) / 2
        return running, true_count

    def summary_lines(self) -> List[str]:
        lines = []
        for r in self.results:
            label = OUTCOME_LABELS[r.outcome]
            lines.append(f"Hand {r.spot_index + 1}: {label}  (${r.payout:,.2f} returned)")
        for sb in self.side_bet_results:
            if sb.win_amount > 0:
                lines.append(f"Hand {sb.spot_index + 1} {sb.name}: {sb.label}!  +${sb.win_amount:,.2f}")
            else:
                lines.append(f"Hand {sb.spot_index + 1} {sb.name}: no win  (-${sb.wager:,.2f})")
        return lines
