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
    "player_win": "WIN",
    "dealer_win": "LOSE",
    "push": "PUSH",
    "surrender": "SURRENDER",
}


class Phase(Enum):
    EARLY_SURRENDER = auto()
    INSURANCE = auto()
    PLAYER_TURN = auto()
    DEALER_TURN = auto()
    SETTLED = auto()


class InsufficientFundsError(Exception):
    def __init__(self, needed: float, available: float):
        super().__init__(f"Need ${needed:,.2f} but only ${available:,.2f} available")
        self.needed = needed
        self.available = available


@dataclass
class Spot:
    """One of the 1-3 hands the player chose to play this round (pre-split)."""

    index: int
    hands: List[Hand] = field(default_factory=list)
    insurance_wager: float = 0.0


@dataclass
class SideBetResult:
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
    """Long-lived state that persists across rounds: rules, bankroll, shoe, stats."""

    def __init__(self, bankroll: float, rules: Rules, stats: Stats):
        self.rules = rules
        self.bankroll = bankroll
        self.stats = stats
        self.stats.session_start_bankroll = bankroll
        self.shoe = Shoe(rules.num_decks, rules.penetration)
        self.side_bet_wagers: Dict[str, float] = {
            "power_poker": 0.0,
            "star21": 0.0,
            "dealer_buster": 0.0,
        }
        self._quit = False

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

        Only ever called between rounds, never mid-round -- a shoe's
        card order and running count must stay stable while a round is live.
        """
        if self.shoe.penetration_reached or self.shoe.cards_remaining < 15:
            self.shoe = Shoe(self.rules.num_decks, self.rules.penetration)
            return True
        return False


def try_start_round(session: GameSession) -> Tuple[Optional["Round"], Optional[str]]:
    try:
        return Round(session), None
    except InsufficientFundsError as exc:
        return None, str(exc)


class Round:
    """A full deal-to-settlement cycle for one or more simultaneous hands."""

    def __init__(self, session: GameSession):
        self.session = session
        self.rules = session.rules
        session.ensure_shoe_ready()

        num_hands = self.rules.num_hands
        base_bet = self.rules.default_bet

        self.side_bet_wagers: Dict[str, float] = {}
        for key in ("power_poker", "star21", "dealer_buster"):
            side_rule = getattr(self.rules, key)
            amt = session.side_bet_wagers.get(key, 0.0) if side_rule.enabled else 0.0
            self.side_bet_wagers[key] = min(amt, side_rule.max_bet) if amt > 0 else 0.0

        total_needed = num_hands * base_bet + sum(self.side_bet_wagers.values())
        if not session.can_afford(total_needed):
            raise InsufficientFundsError(total_needed, session.bankroll)
        session.adjust_bankroll(-total_needed)

        self.dealer_hand = Hand()
        self.spots: List[Spot] = [
            Spot(index=i, hands=[Hand(bet=base_bet)]) for i in range(num_hands)
        ]

        # Standard deal order: each spot gets a card, then the dealer, twice.
        for _ in range(2):
            for spot in self.spots:
                spot.hands[0].add_card(session.shoe.draw())
            self.dealer_hand.add_card(session.shoe.draw())

        # Side bets key off the very first hand's original two cards --
        # snapshot them now since that hand's cards may change if it's hit.
        self._side_bet_snapshot: List[Card] = list(self.spots[0].hands[0].cards)
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

        if self.dealer_up.rank == "A":
            if self.rules.surrender_early:
                self.phase = Phase.EARLY_SURRENDER
                self._advance_early_surrender_cursor()
            else:
                self.phase = Phase.INSURANCE
                self._advance_insurance_cursor()
        else:
            self.phase = Phase.PLAYER_TURN
            self._advance_player_cursor()

    # ------------------------------------------------------------------
    # Early surrender / insurance / even money (dealer Ace up only)
    # ------------------------------------------------------------------

    def current_prelim_spot(self) -> Optional[Spot]:
        if self.phase in (Phase.EARLY_SURRENDER, Phase.INSURANCE) and self._prelim_index < len(self.spots):
            return self.spots[self._prelim_index]
        return None

    def insurance_prompt_kind(self, spot: Spot) -> str:
        """'even_money' or 'insurance', for the UI to pick prompt wording."""
        return "even_money" if spot.hands[0].is_blackjack else "insurance"

    def _advance_early_surrender_cursor(self) -> None:
        while self._prelim_index < len(self.spots):
            if self.spots[self._prelim_index].hands[0].surrendered:
                self._prelim_index += 1
                continue
            return
        self._prelim_index = 0
        self.phase = Phase.INSURANCE
        self._advance_insurance_cursor()

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
                and len(spot.hands) < self.rules.split_max_hands
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
        if self.dealer_up.rank == "A":
            # Early surrender (if enabled) already had its chance pre-peek;
            # late surrender is offered here, now that there's no dealer blackjack.
            return self.rules.surrender == "late"
        return True

    def perform_action(self, action: str) -> None:
        current = self.current_player_hand()
        if current is None:
            return
        spot, hand = current
        legal = self.legal_actions(spot, hand)
        if action not in legal:
            return

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
            self.session.stats.record_double()
        elif action == "split":
            self._do_split(spot, hand)
        elif action == "surrender":
            hand.surrendered = True

        self._advance_player_cursor()

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

    def _begin_dealer_turn_or_settle(self) -> None:
        any_live = any(
            not (h.is_bust or h.surrendered or h.even_money_taken or h.is_blackjack)
            for spot in self.spots
            for h in spot.hands
        )
        # Dealer Buster needs the dealer to play out their hand to resolve,
        # even if every player hand is already settled.
        buster_wager = self.side_bet_wagers.get("dealer_buster", 0.0)
        need_dealer_play = any_live or buster_wager > 0

        if not need_dealer_play:
            self.dealer_revealed = True
            self._settle_round()
            self.phase = Phase.SETTLED
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
            self._settle_round()
            self.phase = Phase.SETTLED
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
        results = []
        player_cards = self._side_bet_snapshot
        dealer_up = self.dealer_up

        evaluators = {
            "power_poker": ("Power Poker", evaluate_power_poker),
            "star21": ("Star 21", evaluate_star21),
        }
        for key, (name, fn) in evaluators.items():
            wager = self.side_bet_wagers.get(key, 0.0)
            if wager <= 0:
                continue
            outcome = fn(player_cards, dealer_up)
            label, multiplier = outcome if outcome else (None, 0.0)
            win = wager * (1 + multiplier) if outcome else 0.0
            if win:
                self.session.adjust_bankroll(win)
            results.append(SideBetResult(name, wager, label, multiplier, win))

        buster_wager = self.side_bet_wagers.get("dealer_buster", 0.0)
        if buster_wager > 0:
            outcome = evaluate_dealer_buster(self.dealer_hand)
            label, multiplier = outcome if outcome else (None, 0.0)
            win = buster_wager * (1 + multiplier) if outcome else 0.0
            if win:
                self.session.adjust_bankroll(win)
            results.append(SideBetResult("Dealer Buster", buster_wager, label, multiplier, win))

        return results

    def _settle_round(self) -> None:
        dealer_bust = self.dealer_hand.is_bust
        dealer_value = self.dealer_hand.best_value
        dealer_bj = self.dealer_hand.is_blackjack

        if dealer_bj:
            self.session.stats.record_dealer_blackjack()

        results: List[HandResult] = []
        for spot in self.spots:
            for hand in spot.hands:
                payout, outcome = self._settle_hand(hand, dealer_bust, dealer_value, dealer_bj)
                self.session.adjust_bankroll(payout)
                self.session.stats.record_hand_outcome(outcome)
                if hand.is_blackjack:
                    self.session.stats.record_player_blackjack()
                results.append(HandResult(spot.index, hand, outcome, payout))

            if spot.insurance_wager > 0 and dealer_bj:
                self.session.adjust_bankroll(spot.insurance_wager * 3)

        self.results = results
        self.side_bet_results = self._settle_side_bets()

    def summary_lines(self) -> List[str]:
        lines = []
        for r in self.results:
            label = OUTCOME_LABELS[r.outcome]
            lines.append(f"Hand {r.spot_index + 1}: {label}  (${r.payout:,.2f} returned)")
        for sb in self.side_bet_results:
            if sb.win_amount > 0:
                lines.append(f"{sb.name}: {sb.label}!  +${sb.win_amount:,.2f}")
            else:
                lines.append(f"{sb.name}: no win  (-${sb.wager:,.2f})")
        return lines
