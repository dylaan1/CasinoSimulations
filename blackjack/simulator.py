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
        self._reset_temp_tables()
        cur = self.conn.cursor()
        cur.execute("SELECT COALESCE(MAX(sim), 0) FROM results")
        self.sim_number = cur.fetchone()[0] + 1
        self.results_available = False

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
                surrender TEXT,
                hands INTEGER,
                wager REAL,
                open_bankroll REAL,
                close_bankroll REAL,
                player_cards TEXT,
                dealer_cards TEXT
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
                surrender TEXT,
                hands INTEGER,
                wager REAL,
                open_bankroll REAL,
                close_bankroll REAL,
                player_cards TEXT,
                dealer_cards TEXT
            )
            """
        )

        self.conn.commit()

    def _reset_temp_tables(self) -> None:
        cur = self.conn.cursor()
        for _, temp in TABLE_PAIRS:
            cur.execute(f"DELETE FROM {temp}")
        self.conn.commit()

    def _format_round(
        self, player_hands: List[Hand], dealer_hand: Hand
    ) -> tuple[str, str]:
        """Return compact player/dealer summaries for table display."""

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

        def describe(hand: Hand) -> str:
            cards = ", ".join(render_card(c) for c in hand.cards)
            if hand.surrendered:
                return f"{cards} | Surrender"
            if hand.is_blackjack:
                return f"{cards} | 21 (Blackjack)"
            if hand.is_bust:
                return f"{cards} | {hand.best_value} (Bust)"
            status = "Stand"
            tags = []
            if hand.bet > self.settings.bet_amount:
                tags.append("Double")
            if hand.is_split_aces:
                tags.append("Split Aces")
            elif hand.is_split:
                tags.append("Split")
            if tags:
                status = f"{status}, {'/'.join(tags)}"
            return f"{cards} | {hand.best_value} ({status})"

        player_entries = [describe(hand) for hand in player_hands]
        if len(player_entries) > 1:
            player_text = " / ".join(
                f"Hand {idx}: {text}" for idx, text in enumerate(player_entries, start=1)
            )
        else:
            player_text = player_entries[0]
        dealer_text = describe(dealer_hand)
        return player_text, dealer_text

    def run(self) -> None:
        if self.settings.seed is not None:
            random.seed(self.settings.seed)
        allow_surrender = self.settings.surrender.lower() != "none"
        strat = BasicStrategy.from_json(
            self.settings.strategy_file, allow_surrender=allow_surrender
        )
        total_hands = 0
        for trial in range(1, self.settings.trials + 1):
            shoe = Shoe(self.settings.num_decks, penetration=self.settings.penetration)
            player_settings = PlayerSettings(
                bankroll=self.settings.bankroll,
                blackjack_payout=self.settings.blackjack_payout,
                double_after_split=self.settings.double_after_split,
                resplit_aces=self.settings.resplit_aces,
                surrender=self.settings.surrender.lower(),
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

                dealer_up = dealer_hand.cards[0].rank
                dealer_checks_blackjack = dealer_up in {"10", "A"}
                dealer_has_blackjack = dealer_checks_blackjack and dealer_hand.is_blackjack
                surrender_setting = self.settings.surrender.lower()

                if surrender_setting == "late" and dealer_has_blackjack:
                    player_hands = [player_hand]
                else:
                    player_hands = player.play(
                        shoe,
                        dealer_up,
                        player_hand,
                        allow_surrender=allow_surrender,
                    )

                dealer_blackjack_active = dealer_has_blackjack and any(
                    not h.surrendered for h in player_hands
                )
                if not dealer_blackjack_active and any(
                    not h.is_bust and not h.surrendered for h in player_hands
                ):
                    dealer.play(dealer_hand, shoe)
                for h in player_hands:
                    change = self.resolve_hand(h, dealer_hand, player_settings)
                    player_settings.bankroll += change
                hands_played += len(player_hands)
                total_hands += len(player_hands)

                cur.execute(
                    "INSERT INTO temp_bankroll VALUES (?,?,?)",
                    (trial, hands_played, player_settings.bankroll),
                )

                player_text, dealer_text = self._format_round(player_hands, dealer_hand)
                cur.execute(
                    "INSERT INTO temp_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        self.sim_number,
                        trial,
                        self.settings.num_decks,
                        self.settings.penetration,
                        "3:2" if self.settings.blackjack_payout == 1.5 else "6:5",
                        "H17" if self.settings.hit_soft_17 else "S17",
                        int(self.settings.double_after_split),
                        int(self.settings.resplit_aces),
                        "E"
                        if surrender_setting == "early"
                        else "L"
                        if surrender_setting == "late"
                        else "N",
                        len(player_hands),
                        self.settings.bet_amount,
                        bankroll_before,
                        player_settings.bankroll,
                        player_text,
                        dealer_text,
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
        self.results_available = total_hands > 0

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
