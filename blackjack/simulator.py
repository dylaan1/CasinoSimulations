from __future__ import annotations
import sqlite3
import random

from dataclasses import asdict

from importlib import import_module

from typing import List

from .settings import SimulationSettings
from .cards import Shoe, Card
from .player import Player, PlayerSettings
from .dealer import Dealer
from .strategy import BasicStrategy
from .hand import Hand


# Mapping of permanent tables to their temporary counterparts
TABLE_PAIRS = [
    ("bankroll", "temp_bankroll"),
    ("summary", "temp_summary"),
    ("card_distribution", "temp_card_distribution"),
    ("results", "temp_results"),
]


class Simulator:
    def __init__(self, settings: SimulationSettings):
        self.settings = settings
        self.conn = sqlite3.connect(self.settings.database)
        self._init_db()
        cur = self.conn.cursor()
        cur.execute("SELECT COALESCE(MAX(sim), 0) FROM results")
        self.sim_number = cur.fetchone()[0] + 1

    def _init_db(self) -> None:
        cur = self.conn.cursor()

        cur.execute(
            "CREATE TABLE IF NOT EXISTS bankroll (trial INTEGER, hand INTEGER, bankroll REAL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS summary (trial INTEGER, hands_played INTEGER, bankroll REAL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS card_distribution (trial INTEGER, card TEXT, count INTEGER)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS temp_bankroll (trial INTEGER, hand INTEGER, bankroll REAL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS temp_summary (trial INTEGER, hands_played INTEGER, bankroll REAL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS temp_card_distribution (trial INTEGER, card TEXT, count INTEGER)"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                sim INTEGER,
                trial INTEGER,
                decks INTEGER,
                penetration REAL,
                payout TEXT,
                soft17 TEXT,
                das INTEGER,
                rsa INTEGER,
                surrender INTEGER,
                hands INTEGER,
                wager REAL,
                open_bankroll REAL,
                close_bankroll REAL,
                cards TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS temp_results (
                sim INTEGER,
                trial INTEGER,
                decks INTEGER,
                penetration REAL,
                payout TEXT,
                soft17 TEXT,
                das INTEGER,
                rsa INTEGER,
                surrender INTEGER,
                hands INTEGER,
                wager REAL,
                open_bankroll REAL,
                close_bankroll REAL,
                cards TEXT
            )
            """
        )

        self.conn.commit()

    def _format_round(
        self, initial_cards: List[Card], player_hands: List[Hand], dealer_hand: Hand
    ) -> str:
        """Return a human-readable, multi-line summary of the round.

        The previous compact encoding (e.g. ``AAvv7s_v8_``) was terse but
        difficult to parse when inspecting results. This formatter trades a bit
        of horizontal space for clarity by rendering each hand on its own line
        with cards, totals, wagers, and status labels.
        """

        suit_glyphs = {
            "hearts": "♥",
            "diamonds": "♦",
            "clubs": "♣",
            "spades": "♠",
        }

        def render_card(card: Card) -> str:
            glyph = suit_glyphs.get(card.suit, "")
            rank = "T" if card.rank == "10" else card.rank
            return f"{rank}{glyph}" if glyph else rank

        def describe_hand(hand: Hand, index: int) -> str:
            cards = ", ".join(render_card(c) for c in hand.cards)
            total = hand.best_value
            status: str
            if hand.surrendered:
                status = "Surrendered"
            elif hand.is_blackjack:
                status = "Blackjack"
            elif hand.is_bust:
                status = "Bust"
            else:
                status = f"Finished {total}"

            labels = []
            if hand.is_split_aces:
                labels.append("Split Aces")
            elif hand.is_split:
                labels.append("Split")
            if hand.bet > self.settings.bet_amount:
                labels.append("Doubled")

            label_text = f" ({', '.join(labels)})" if labels else ""
            return (
                f"  {index}) Bet {hand.bet:.2f}{label_text} — Cards: {cards} — "
                f"Status: {status}"
            )

        player_lines = ["Player Hands:"]
        for idx, hand in enumerate(player_hands, start=1):
            player_lines.append(describe_hand(hand, idx))

        dealer_cards = ", ".join(render_card(c) for c in dealer_hand.cards)
        dealer_status = "Bust" if dealer_hand.is_bust else f"Finished {dealer_hand.best_value}"
        dealer_section = f"Dealer — Cards: {dealer_cards} — Status: {dealer_status}"

        return "\n".join(player_lines + [dealer_section])

    def run(self) -> None:
        if self.settings.seed is not None:
            random.seed(self.settings.seed)
        strat = BasicStrategy.from_json(
            self.settings.strategy_file, allow_surrender=self.settings.allow_surrender
        )
        for trial in range(1, self.settings.trials + 1):
            shoe = Shoe(self.settings.num_decks, penetration=self.settings.penetration)
            player_settings = PlayerSettings(
                bankroll=self.settings.bankroll,
                blackjack_payout=self.settings.blackjack_payout,
                double_after_split=self.settings.double_after_split,
                resplit_aces=self.settings.resplit_aces,
                allow_surrender=self.settings.allow_surrender,
                bet_amount=self.settings.bet_amount,
            )
            player = Player(player_settings, strat)
            dealer = Dealer(hit_soft_17=self.settings.hit_soft_17)
            hands_played = 0
            cur = self.conn.cursor()
            while (
                hands_played < self.settings.hands_per_game
                and player_settings.bankroll >= player_settings.bet_amount
            ):
                if shoe.penetration_reached:
                    shoe.shuffle()
                bankroll_before = player_settings.bankroll
                player_settings.bankroll -= player_settings.bet_amount
                player_hand = Hand(bet=player_settings.bet_amount)
                dealer_hand = Hand()
                player_hand.add_card(shoe.draw())
                dealer_hand.add_card(shoe.draw())
                player_hand.add_card(shoe.draw())
                dealer_hand.add_card(shoe.draw())

                initial_cards = list(player_hand.cards)
                player_hands = player.play(shoe, dealer_hand.cards[0].rank, player_hand)
                if any(not h.is_bust and not h.surrendered for h in player_hands):
                    dealer.play(dealer_hand, shoe)
                for h in player_hands:
                    change = self.resolve_hand(h, dealer_hand, player_settings)
                    player_settings.bankroll += change
                hands_played += len(player_hands)

                cur.execute(
                    "INSERT INTO temp_bankroll VALUES (?,?,?)",
                    (trial, hands_played, player_settings.bankroll),
                )

                layout = self._format_round(initial_cards, player_hands, dealer_hand)
                cur.execute(
                    "INSERT INTO temp_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        self.sim_number,
                        trial,
                        self.settings.num_decks,
                        self.settings.penetration,
                        "3:2" if self.settings.blackjack_payout == 1.5 else "6:5",
                        "H17" if self.settings.hit_soft_17 else "S17",
                        int(self.settings.double_after_split),
                        int(self.settings.resplit_aces),
                        int(self.settings.allow_surrender),
                        len(player_hands),
                        self.settings.bet_amount,
                        bankroll_before,
                        player_settings.bankroll,
                        layout,
                    ),
                )
            cur.execute(
                "INSERT INTO temp_summary VALUES (?,?,?)",
                (trial, hands_played, player_settings.bankroll),
            )
            for card, count in shoe.drawn_counts.items():
                # Store tens as "T" for compact distribution records
                rank = "T" if card == "10" else card
                cur.execute(
                    "INSERT INTO temp_card_distribution VALUES (?,?,?)",
                    (trial, rank, count),
                )
            self.conn.commit()

    def save_results(self) -> None:
        """Persist temporary tables into permanent storage."""
        if self.settings.test_mode:
            raise RuntimeError("Cannot save results while in test mode")
        cur = self.conn.cursor()
        for permanent, temp in TABLE_PAIRS:
            cur.execute(f"INSERT INTO {permanent} SELECT * FROM {temp}")
            cur.execute(f"DELETE FROM {temp}")
        self.conn.commit()

    def discard_results(self) -> None:
        """Remove any data from the temporary tables."""
        cur = self.conn.cursor()
        for _, temp in TABLE_PAIRS:
            cur.execute(f"DELETE FROM {temp}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def resolve_hand(self, hand, dealer_hand, settings: PlayerSettings) -> float:
        if hand.surrendered:
            return hand.bet  # half wager already deducted
        if hand.is_bust:
            return 0
        dealer_bust = dealer_hand.is_bust
        if hand.is_blackjack and not dealer_hand.is_blackjack:
            return hand.bet * (1 + settings.blackjack_payout)
        if dealer_hand.is_blackjack and not hand.is_blackjack:
            return 0
        if dealer_bust:
            return hand.bet * 2
        player_value = hand.best_value
        dealer_value = dealer_hand.best_value
        if player_value > dealer_value:
            return hand.bet * 2
        if player_value < dealer_value:
            return 0
        return hand.bet
