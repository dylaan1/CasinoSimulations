from __future__ import annotations
import sqlite3
import random
import string
from datetime import datetime

from dataclasses import asdict

from importlib import import_module

from typing import List

from .sys_settings import SimulationSettings
from .game_cards import Shoe, Card
from .game_player import Player, PlayerSettings
from .game_dealer import Dealer
from .sys_strategy import BasicStrategy
from .game_hand import Hand


# Mapping of permanent tables to their temporary counterparts
TABLE_PAIRS = [
    ("bankroll", "temp_bankroll"),
    ("summary", "temp_summary"),
    ("card_distribution", "temp_card_distribution"),
    ("results", "temp_results"),
]

TABLE_COLUMNS = {
    "bankroll": ("round_number", "hand", "bankroll"),
    "summary": ("round_number", "hands_played", "bankroll"),
    "card_distribution": ("round_number", "card", "count"),
    "results": (
        "sim",
        "round_number",
        "decks",
        "penetration",
        "payout",
        "soft17",
        "das",
        "rsa",
        "surrender",
        "hands",
        "wager",
        "open_bankroll",
        "close_bankroll",
        "player_hand_a",
        "player_hand_b",
        "player_hand_c",
        "player_hand_d",
        "result_a",
        "result_b",
        "result_c",
        "result_d",
        "dealer_cards",
        "running_count",
        "true_count",
        "cards_dealt",
    ),
}


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

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        """Add the given column to table if it is missing."""
        cur = self.conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        if column not in {row[1] for row in cur.fetchall()}:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _init_db(self) -> None:
        cur = self.conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bankroll (
                round_number INTEGER,
                hand INTEGER,
                bankroll REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS summary (
                round_number INTEGER,
                hands_played INTEGER,
                bankroll REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS card_distribution (
                round_number INTEGER,
                card TEXT,
                count INTEGER
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                sim INTEGER,
                round_number INTEGER,
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
                player_hand_a TEXT,
                player_hand_b TEXT,
                player_hand_c TEXT,
                player_hand_d TEXT,
                result_a TEXT,
                result_b TEXT,
                result_c TEXT,
                result_d TEXT,
                dealer_cards TEXT,
                running_count INTEGER,
                true_count REAL,
                cards_dealt INTEGER
            )
            """
        )
        self._create_temp_tables(cur)

        for table in ("results", "temp_results"):
            self._ensure_column(table, "round_number", "INTEGER")
            self._ensure_column(table, "player_hand_a", "TEXT")
            self._ensure_column(table, "player_hand_b", "TEXT")
            self._ensure_column(table, "player_hand_c", "TEXT")
            self._ensure_column(table, "player_hand_d", "TEXT")
            self._ensure_column(table, "result_a", "TEXT")
            self._ensure_column(table, "result_b", "TEXT")
            self._ensure_column(table, "result_c", "TEXT")
            self._ensure_column(table, "result_d", "TEXT")
            self._ensure_column(table, "running_count", "INTEGER")
            self._ensure_column(table, "true_count", "REAL")
            self._ensure_column(table, "cards_dealt", "INTEGER")
            self._ensure_column(table, "dealer_cards", "TEXT")

        for table in (
            "bankroll",
            "summary",
            "card_distribution",
            "temp_bankroll",
            "temp_summary",
            "temp_card_distribution",
        ):
            self._ensure_column(table, "round_number", "INTEGER")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_seeds (
                seed_id TEXT PRIMARY KEY,
                created_at TEXT,
                total_rounds INTEGER,
                total_hands INTEGER,
                total_pl REAL,
                starting_bankroll REAL,
                favorite INTEGER DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_seed_results (
                seed_id TEXT,
                round_number INTEGER,
                hand INTEGER,
                wager REAL,
                open_bankroll REAL,
                close_bankroll REAL,
                player_hand_a TEXT,
                player_hand_b TEXT,
                player_hand_c TEXT,
                player_hand_d TEXT,
                result_a TEXT,
                result_b TEXT,
                result_c TEXT,
                result_d TEXT,
                dealer_cards TEXT,
                cards_dealt INTEGER,
                running_count INTEGER,
                true_count REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_seed_bankroll (
                seed_id TEXT,
                round_number INTEGER,
                hand INTEGER,
                bankroll REAL
            )
            """
        )
        self._ensure_column("saved_seeds", "favorite", "INTEGER")
        for column in ("result_a", "result_b", "result_c", "result_d"):
            self._ensure_column("saved_seed_results", column, "TEXT")

        self.conn.commit()

    def _reset_temp_tables(self) -> None:
        cur = self.conn.cursor()
        for _, temp in TABLE_PAIRS:
            cur.execute(f"DROP TABLE IF EXISTS {temp}")
        self._create_temp_tables(cur)
        self.conn.commit()

    def _create_temp_tables(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS temp_bankroll (
                round_number INTEGER,
                hand INTEGER,
                bankroll REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS temp_summary (
                round_number INTEGER,
                hands_played INTEGER,
                bankroll REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS temp_card_distribution (
                round_number INTEGER,
                card TEXT,
                count INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS temp_results (
                sim INTEGER,
                round_number INTEGER,
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
                player_hand_a TEXT,
                player_hand_b TEXT,
                player_hand_c TEXT,
                player_hand_d TEXT,
                result_a TEXT,
                result_b TEXT,
                result_c TEXT,
                result_d TEXT,
                dealer_cards TEXT,
                running_count INTEGER,
                true_count REAL,
                cards_dealt INTEGER
            )
            """
        )

    def _format_hand(self, hand: Hand, base_bet: float) -> str:
        """Return a compact hand summary for table display."""

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

        cards = ", ".join(render_card(c) for c in hand.cards)
        if hand.surrendered:
            return f"{cards} | Surrender"
        if hand.is_blackjack:
            return f"{cards} | 21 (Blackjack)"
        if hand.is_bust:
            return f"{cards} | {hand.best_value} (Bust)"
        status = "Stand"
        if hand.bet > base_bet:
            status = "Double"
        return f"{cards} | {hand.best_value} ({status})"

    def _format_dealer(self, hand: Hand) -> str:
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

        cards = ", ".join(render_card(c) for c in hand.cards)
        if hand.is_blackjack:
            return f"{cards} | 21 (Blackjack)"
        if hand.is_bust:
            return f"{cards} | {hand.best_value} (Bust)"
        return f"{cards} | {hand.best_value} (Stand)"

    def _hand_result(self, hand: Hand, dealer_hand: Hand) -> str:
        if hand.surrendered:
            return "Loss"
        if hand.is_bust:
            return "Loss"
        if dealer_hand.is_bust:
            return "Win"
        player_value = hand.best_value
        dealer_value = dealer_hand.best_value
        if player_value > dealer_value:
            return "Win"
        if player_value < dealer_value:
            return "Loss"
        return "Push"

    def run(self) -> None:
        allow_surrender = self.settings.surrender.lower() != "none"
        strat = BasicStrategy.from_json(
            self.settings.strategy_file, allow_surrender=allow_surrender
        )
        total_hands = 0
        for round_number in range(1, self.settings.rounds + 1):
            shoe = Shoe(self.settings.num_decks, penetration=self.settings.penetration)
            player_settings = PlayerSettings(
                bankroll=self.settings.bankroll,
                blackjack_payout=self.settings.blackjack_payout,
                double_after_split=self.settings.double_after_split,
                split_aces_logic=self.settings.split_aces_logic,
                surrender=self.settings.surrender.lower(),
                bet_amount=self.settings.bet_amount,
            )
            player = Player(player_settings, strat)
            dealer = Dealer(hit_soft_17=self.settings.hit_soft_17)
            hands_played = 0
            hand_counter = 0
            deal_counter = 0
            cur = self.conn.cursor()
            for _ in range(self.settings.hands_per_round):
                if player_settings.bankroll < player_settings.bet_amount:
                    break
                if shoe.penetration_reached:
                    shoe.shuffle()
                deal_counter += 1
                hand_open_bankroll = player_settings.bankroll
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

                dealer_text = self._format_dealer(dealer_hand)
                running_count = shoe.running_count
                true_count = round(shoe.true_count, 1)
                cards_dealt = shoe.cards_dealt
                player_entries = ["", "", "", ""]
                result_entries = ["", "", "", ""]
                total_wager = 0.0
                for hand_index, hand in enumerate(player_hands):
                    hand_counter += 1
                    hands_played += 1
                    total_hands += 1
                    slot = min(hand_index, len(player_entries) - 1)
                    player_entries[slot] = self._format_hand(
                        hand, self.settings.bet_amount
                    )
                    result_entries[slot] = self._hand_result(hand, dealer_hand)
                    total_wager += hand.bet * (2 if hand.surrendered else 1)
                    change = self.resolve_hand(hand, dealer_hand, player_settings)
                    player_settings.bankroll += change
                    cur.execute(
                        """
                        INSERT INTO temp_bankroll (round_number, hand, bankroll)
                        VALUES (?,?,?)
                        """,
                        (round_number, hand_counter, player_settings.bankroll),
                    )
                cur.execute(
                    """
                    INSERT INTO temp_results (
                        sim,
                        round_number,
                        decks,
                        penetration,
                        payout,
                        soft17,
                        das,
                        rsa,
                        surrender,
                        hands,
                        wager,
                        open_bankroll,
                        close_bankroll,
                        player_hand_a,
                        player_hand_b,
                        player_hand_c,
                        player_hand_d,
                        result_a,
                        result_b,
                        result_c,
                        result_d,
                        dealer_cards,
                        running_count,
                        true_count,
                        cards_dealt
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        self.sim_number,
                        round_number,
                        self.settings.num_decks,
                        self.settings.penetration,
                        "3:2" if self.settings.blackjack_payout == 1.5 else "6:5",
                        "H17" if self.settings.hit_soft_17 else "S17",
                        int(self.settings.double_after_split),
                        1 if self.settings.split_aces_logic.lower() == "carnival" else 0,
                        "E"
                        if surrender_setting == "early"
                        else "L"
                        if surrender_setting == "late"
                        else "N",
                        deal_counter,
                        total_wager,
                        hand_open_bankroll,
                        player_settings.bankroll,
                        player_entries[0],
                        player_entries[1],
                        player_entries[2],
                        player_entries[3],
                        result_entries[0],
                        result_entries[1],
                        result_entries[2],
                        result_entries[3],
                        dealer_text,
                        running_count,
                        true_count,
                        cards_dealt,
                    ),
                )
            cur.execute(
                "INSERT INTO temp_summary (round_number, hands_played, bankroll) VALUES (?,?,?)",
                (round_number, hands_played, player_settings.bankroll),
            )
            for card, count in shoe.drawn_counts.items():
                # Store tens as "T" for compact distribution records
                rank = "T" if card == "10" else card
                cur.execute(
                    "INSERT INTO temp_card_distribution (round_number, card, count) VALUES (?,?,?)",
                    (round_number, rank, count),
                )
            self.conn.commit()
        self.results_available = total_hands > 0

    def save_results(self) -> str:
        """Persist temporary tables into permanent storage."""
        if self.settings.test_mode:
            raise RuntimeError("Cannot save results while in test mode")
        seed_id = self._save_seed_snapshot()
        cur = self.conn.cursor()
        for permanent, temp in TABLE_PAIRS:
            columns = TABLE_COLUMNS[permanent]
            column_list = ", ".join(columns)
            cur.execute(
                f"INSERT INTO {permanent} ({column_list}) "
                f"SELECT {column_list} FROM {temp}"
            )
            cur.execute(f"DELETE FROM {temp}")
        self.conn.commit()
        return seed_id

    def discard_results(self) -> None:
        """Remove any data from the temporary tables."""
        cur = self.conn.cursor()
        for _, temp in TABLE_PAIRS:
            cur.execute(f"DELETE FROM {temp}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _generate_seed_id(self) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(random.choice(alphabet) for _ in range(7))

    def _save_seed_snapshot(self) -> str:
        cur = self.conn.cursor()
        seed_id = self._generate_seed_id()
        cur.execute("SELECT seed_id FROM saved_seeds WHERE seed_id = ?", (seed_id,))
        while cur.fetchone():
            seed_id = self._generate_seed_id()
            cur.execute("SELECT seed_id FROM saved_seeds WHERE seed_id = ?", (seed_id,))

        cur.execute("SELECT COUNT(*) FROM temp_results")
        total_hands = cur.fetchone()[0]

        cur.execute("SELECT DISTINCT round_number FROM temp_bankroll")
        rounds = [row[0] for row in cur.fetchall() if row[0] is not None]
        total_rounds = len(rounds)

        cur.execute(
            """
            SELECT b.round_number, b.bankroll
            FROM temp_bankroll b
            JOIN (
                SELECT round_number, MAX(hand) AS max_hand
                FROM temp_bankroll
                GROUP BY round_number
            ) m
            ON b.round_number = m.round_number AND b.hand = m.max_hand
            """
        )
        ending_rows = cur.fetchall()
        total_pl = sum(
            bankroll - self.settings.bankroll for _, bankroll in ending_rows
        )

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """
            INSERT INTO saved_seeds (
                seed_id,
                created_at,
                total_rounds,
                total_hands,
                total_pl,
                starting_bankroll,
                favorite
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                seed_id,
                created_at,
                total_rounds,
                total_hands,
                total_pl,
                self.settings.bankroll,
                0,
            ),
        )

        cur.execute(
            """
            INSERT INTO saved_seed_bankroll (
                seed_id,
                round_number,
                hand,
                bankroll
            )
            SELECT ?, round_number, hand, bankroll FROM temp_bankroll
            """,
            (seed_id,),
        )
        cur.execute(
            """
            INSERT INTO saved_seed_results (
                seed_id,
                round_number,
                hand,
                wager,
                open_bankroll,
                close_bankroll,
                player_hand_a,
                player_hand_b,
                player_hand_c,
                player_hand_d,
                result_a,
                result_b,
                result_c,
                result_d,
                dealer_cards,
                cards_dealt,
                running_count,
                true_count
            )
            SELECT
                ?,
                round_number,
                hands,
                wager,
                open_bankroll,
                close_bankroll,
                player_hand_a,
                player_hand_b,
                player_hand_c,
                player_hand_d,
                result_a,
                result_b,
                result_c,
                result_d,
                dealer_cards,
                cards_dealt,
                running_count,
                true_count
            FROM temp_results
            """,
            (seed_id,),
        )
        self.conn.commit()
        return seed_id

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
