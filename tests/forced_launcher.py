"""Launch the real game, but with a first shoe holding just five cards, so a hit empties it mid-hand.
Deal order: player 2♣, dealer 9♦, player 3♣, dealer 8♦ (hole) -- then ONE spare card, 4♥.
Used by check_ui.py; runs as its own process."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
cards = importlib.import_module("cs-blackjack.cards")
engine = importlib.import_module("cs-blackjack.engine")
ui = importlib.import_module("cs-blackjack.ui")

_first = {"pending": True}
_orig = cards.Shoe.shuffle


def _card(tok):
    rank = "10" if tok[0] == "T" else tok[0]
    return cards.Card(rank, {"♠": "spades", "♥": "hearts", "♦": "diamonds", "♣": "clubs"}[tok[1]])


def shuffle(self):
    _orig(self)
    if _first["pending"] and self.num_decks == 6:
        _first["pending"] = False
        lead = [_card(t) for t in ("2♣", "9♦", "3♣", "8♦", "4♥")]
        self._cards = list(reversed(lead))
        self._initial_order = lead[:]


cards.Shoe.shuffle = shuffle
# no minimum-cards rule, so the launch-time cut check doesn't replace the five-card shoe
engine.GameSession._min_cards_left = lambda self, num_decks: 1
ui.run()
