from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Iterator, List, Optional, Tuple

from .cards import Card, Shoe
from .dealer import play_dealer_hand
from .hand import Hand
from .rules import Rules
from .sidebets import evaluate_dealer_buster, evaluate_power_poker, evaluate_star21
from .stats import Stats

OUTCOME_LABELS = {
    "player_win": "Win",
    "dealer_win": "Lose",
    "push": "Push",
    "surrender": "Surrendered",
}

SIDE_BET_KEYS = ("power_poker", "star21", "dealer_buster")
SIDE_BET_LABELS = {"power_poker": "PowerPoker", "star21": "Star21", "dealer_buster": "Dealer Buster"}

# American-style peek: the dealer checks their hole card for blackjack whenever
# the up card is an Ace or any ten-value card. Insurance/even money are only
# ever offered on an Ace up card -- a ten-value peek is silent (no side bet),
# it just protects the player from playing (and doubling/splitting) into a
# dealer blackjack that's already a done deal.
PEEK_RANKS = {"A", "10", "J", "Q", "K"}


class Phase(Enum):
    EARLY_SURRENDER = auto()
    INSURANCE = auto()
    PLAYER_TURN = auto()
    DEALER_TURN = auto()
    REVEAL = auto()  # flipping any face-down double-down cards, just before settlement
    SETTLED = auto()


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
        stats: Stats,
        wagers: Optional[List[float]] = None,
        side_bet_wagers: Optional[List[Dict[str, float]]] = None,
    ):
        self.rules = rules
        self.bankroll = bankroll
        self.stats = stats
        self.shoe = Shoe(rules.num_decks, rules.penetration)
        self.wagers: List[float] = list(wagers) if wagers else [rules.default_bet, 0.0, 0.0]
        self.side_bet_wagers: List[Dict[str, float]] = (
            [dict(d) for d in side_bet_wagers]
            if side_bet_wagers
            else [{key: 0.0 for key in SIDE_BET_KEYS} for _ in range(3)]
        )
        self._quit = False
        self.pending_confirmation: Optional[str] = None  # "newshoe" | "newsession", awaiting a RETURN to confirm
        self.pending_hard_reset = False  # awaiting the literal word "confirm" typed as a command

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

    def ensure_shoe_ready(self) -> bool:
        """Cut a fresh shoe if penetration was reached (or too few cards remain).

        Called right after a round settles (and once at session start) --
        deliberately NOT at deal time. A round that crosses the cut card
        still finishes with the shoe it started with; the player is meant to
        see the resulting (possibly reset) true count on the betting screen
        *before* sizing their next wager, not have it swapped out from under
        an already-placed bet.
        """
        if self.shoe.penetration_reached or self.shoe.cards_remaining < 15:
            self.shoe = Shoe(self.rules.num_decks, self.rules.penetration)
            return True
        return False

    def reset_shoe(self) -> None:
        """Forcibly cut a brand-new shoe, e.g. from the 'newshoe' command."""
        self.shoe = Shoe(self.rules.num_decks, self.rules.penetration)

    def reset_session(self) -> None:
        """Forcibly cut a brand-new shoe, clear session-scoped stats, and
        reset the bankroll to its configured default (see 'bank default')."""
        self.reset_shoe()
        self.stats.reset_session()
        self.bankroll = self.rules.default_bankroll

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
    try:
        return Round(session), None
    except (InsufficientFundsError, NoWagerError, BelowMinimumWagerError) as exc:
        return None, str(exc)


class Round:
    """A full deal-to-settlement cycle for one or more simultaneous hands."""

    def __init__(self, session: GameSession):
        self.session = session
        self.rules = session.rules

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
                amt = session.side_bet_wagers[i].get(key, 0.0) if side_rule.enabled else 0.0
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

        # Standard deal order: each spot gets a card, then the dealer, twice.
        for _ in range(2):
            for spot in self.spots:
                spot.hands[0].add_card(session.shoe.draw())
            self.dealer_hand.add_card(session.shoe.draw())

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

        self._current_spot_index = 0
        self._current_hand_index = 0
        self._prelim_index = 0
        self._dealer_draw_iter: Optional[Iterator[Hand]] = None

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
            self.phase = Phase.PLAYER_TURN
            self._advance_player_cursor()

    # ------------------------------------------------------------------
    # Early surrender / insurance / even money / dealer peek
    # ------------------------------------------------------------------

    def current_prelim_spot(self) -> Optional[Spot]:
        if self.phase in (Phase.EARLY_SURRENDER, Phase.INSURANCE) and self._prelim_index < len(self.spots):
            return self.spots[self._prelim_index]
        return None

    def insurance_prompt_kind(self, spot: Spot) -> str:
        """'even_money' or 'insurance', for the UI to pick prompt wording."""
        return "even_money" if spot.hands[0].is_blackjack else "insurance"

    def side_bet_preview_label(self, spot: Spot, key: str) -> Optional[str]:
        """Best-effort outcome label, usable as soon as the spot's first two
        cards are dealt -- Power Poker and Star21 only key off those two
        cards plus the dealer's up card, so (unlike Dealer Buster) their
        outcome is knowable well before settlement."""
        if key == "power_poker":
            outcome = evaluate_power_poker(spot.side_bet_snapshot, self.dealer_up)
        elif key == "star21":
            outcome = evaluate_star21(spot.side_bet_snapshot, self.dealer_up)
        else:
            return None
        return outcome[0] if outcome else None

    def _advance_early_surrender_cursor(self) -> None:
        while self._prelim_index < len(self.spots):
            hand = self.spots[self._prelim_index].hands[0]
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
        while self._prelim_index < len(self.spots):
            if self.spots[self._prelim_index].hands[0].surrendered:
                self._prelim_index += 1
                continue
            return
        self._resolve_peek()

    def respond_early_surrender(self, accept: bool) -> None:
        if self.phase != Phase.EARLY_SURRENDER:
            return
        spot = self.spots[self._prelim_index]
        if accept:
            spot.hands[0].surrendered = True
        self._prelim_index += 1
        self._advance_early_surrender_cursor()

    def respond_insurance(self, accept: bool) -> None:
        if self.phase != Phase.INSURANCE:
            return
        spot = self.spots[self._prelim_index]
        hand = spot.hands[0]
        if accept:
            if hand.is_blackjack:
                hand.even_money_taken = True
            else:
                wager = hand.bet / 2
                if self.session.can_afford(wager):
                    spot.insurance_wager = wager
                    self.session.adjust_bankroll(-wager)
        self._prelim_index += 1
        self._advance_insurance_cursor()

    def _resolve_peek(self) -> None:
        self.peeked = True
        if self.dealer_hand.is_blackjack:
            self.dealer_has_blackjack = True
            self.dealer_revealed = True
            self._settle_round()
            self.phase = Phase.SETTLED
        else:
            self.phase = Phase.PLAYER_TURN
            self._current_spot_index = 0
            self._current_hand_index = 0
            self._advance_player_cursor()

    # ------------------------------------------------------------------
    # Player turn
    # ------------------------------------------------------------------

    def current_player_hand(self) -> Optional[Tuple[Spot, Hand]]:
        if self.phase != Phase.PLAYER_TURN or self._current_spot_index >= len(self.spots):
            return None
        spot = self.spots[self._current_spot_index]
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
                and len(spot.hands) < self.rules.rsa_max_hands
            )
        return True

    def legal_actions(self, spot: Spot, hand: Hand) -> set:
        if not self._hand_needs_play(spot, hand):
            return set()
        if hand.is_split_aces and len(hand.cards) >= 2:
            return {"split"}
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
        if len(spot.hands) >= self.rules.split_max_hands:
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
            if len(spot.hands) >= self.rules.split_max_hands:
                return f"Max split hands reached (splitmax {self.rules.split_max_hands})."
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
            hand.add_card(self.session.shoe.draw())
            if hand.best_value == 21:
                hand.stood = True
        elif action == "stand":
            hand.stood = True
        elif action == "double":
            self.session.adjust_bankroll(-hand.bet)
            hand.bet *= 2
            hand.doubled = True
            hand.add_card(self.session.shoe.draw())
            if self.rules.double_facedown:
                hand.double_hidden = True
            self.session.stats.record_double()
        elif action == "split":
            self._do_split(spot, hand)
        elif action == "surrender":
            hand.surrendered = True

        self._advance_player_cursor()
        return None

    def _do_split(self, spot: Spot, hand: Hand) -> None:
        self.session.adjust_bankroll(-hand.bet)
        kept, moved = hand.cards[0], hand.cards[1]
        is_aces = kept.rank == "A"

        hand.cards = [kept]
        hand.is_split = True
        hand.is_split_aces = is_aces

        new_hand = Hand(cards=[moved], bet=hand.bet, is_split=True, is_split_aces=is_aces)

        hand.add_card(self.session.shoe.draw())
        new_hand.add_card(self.session.shoe.draw())
        spot.hands.insert(self._current_hand_index + 1, new_hand)
        self.session.stats.record_split()

    def _advance_player_cursor(self) -> None:
        while self._current_spot_index < len(self.spots):
            spot = self.spots[self._current_spot_index]
            while self._current_hand_index < len(spot.hands):
                hand = spot.hands[self._current_hand_index]
                if self._hand_needs_play(spot, hand):
                    return
                self._current_hand_index += 1
            self._current_spot_index += 1
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
            self.dealer_hand, self.session.shoe, self.rules.hit_soft_17
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
            return hand.bet * (1 + self.rules.blackjack_payout), "player_win"
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

    def _settle_side_bets(self) -> List[SideBetResult]:
        results: List[SideBetResult] = []
        evaluators = {
            "power_poker": ("Power Poker", evaluate_power_poker),
            "star21": ("Star 21", evaluate_star21),
        }
        for spot in self.spots:
            player_cards = spot.side_bet_snapshot
            for key, (name, fn) in evaluators.items():
                # Evaluated regardless of whether it was actually wagered --
                # some outcomes (like the Star21 7-7-7 diamonds hit) are
                # tracked in lifetime stats purely as an event, independent
                # of the side bet's own win/loss bookkeeping below.
                outcome = fn(player_cards, self.dealer_up)
                label, multiplier = outcome if outcome else (None, 0.0)
                if key == "star21" and label == "Suited 7-7-7 Diamonds":
                    self.session.stats.record_blazing_seven()

                wager = spot.side_bet_wagers.get(key, 0.0)
                if wager <= 0:
                    continue
                win = wager * (1 + multiplier) if outcome else 0.0
                if win:
                    self.session.adjust_bankroll(win)
                self.session.stats.record_side_bet(wager, win)
                results.append(SideBetResult(spot.index, name, wager, label, multiplier, win))

            buster_wager = spot.side_bet_wagers.get("dealer_buster", 0.0)
            if buster_wager > 0:
                outcome = evaluate_dealer_buster(self.dealer_hand)
                label, multiplier = outcome if outcome else (None, 0.0)
                win = buster_wager * (1 + multiplier) if outcome else 0.0
                if win:
                    self.session.adjust_bankroll(win)
                self.session.stats.record_side_bet(buster_wager, win)
                results.append(SideBetResult(spot.index, "Dealer Buster", buster_wager, label, multiplier, win))
        return results

    def _settle_round(self) -> None:
        dealer_bust = self.dealer_hand.is_bust
        dealer_value = self.dealer_hand.best_value
        dealer_bj = self.dealer_hand.is_blackjack

        if dealer_bj:
            self.session.stats.record_dealer_blackjack()
        if dealer_bust and len(self.dealer_hand.cards) >= 8:
            self.session.stats.record_dealer_bust_8plus()

        results: List[HandResult] = []
        for spot in self.spots:
            for hand in spot.hands:
                payout, outcome = self._settle_hand(hand, dealer_bust, dealer_value, dealer_bj)
                self.session.adjust_bankroll(payout)
                self.session.stats.record_hand_outcome(outcome, hand.bet, payout)
                if hand.is_blackjack:
                    self.session.stats.record_player_blackjack()
                results.append(HandResult(spot.index, hand, outcome, payout))

            if spot.insurance_wager > 0:
                insurance_win = spot.insurance_wager * 3 if dealer_bj else 0.0
                if insurance_win:
                    self.session.adjust_bankroll(insurance_win)
                self.session.stats.record_side_bet(spot.insurance_wager, insurance_win)

        self.results = results
        self.side_bet_results = self._settle_side_bets()

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
