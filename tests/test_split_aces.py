import pytest
from blackjack.player import Player, PlayerSettings
from blackjack.hand import Hand
from blackjack.cards import Card

class AlwaysSplitStrategy:
    def decide(self, hand, dealer_up, options):
        if options.get("can_split") and hand.can_split:
            return "split"
        return "stand"

class MockShoe:
    def __init__(self, cards):
        self.cards = list(cards)
        self.drawn = []
    def draw(self):
        card = self.cards.pop(0)
        self.drawn.append(card)
        return card


def test_no_extra_card_when_resplit_disabled():
    # prepare initial hand of two aces
    initial = Hand(cards=[Card('A','spades'), Card('A','hearts')], bet=1.0)
    # shoe will deal Ace then 5, and extra 9 if bug occurs
    shoe = MockShoe([
        Card('A','clubs'),
        Card('5','diamonds'),
        Card('9','hearts'),
    ])
    player = Player(
        settings=PlayerSettings(bankroll=100, split_aces_logic="Single"),
        strategy=AlwaysSplitStrategy(),
    )
    hands = player.play(shoe, dealer_up='5', initial=initial)
    # two hands should have only two cards each
    assert all(len(h.cards) == 2 for h in hands)
    # only two cards should be drawn from the shoe (for the split)
    assert len(shoe.drawn) == 2

class SplitThenDoubleStrategy:
    def __init__(self):
        self.calls = 0
    def decide(self, hand, dealer_up, options):
        self.calls += 1
        if options.get("can_split") and hand.can_split:
            return "split"
        return "double"


def test_split_aces_prevent_double_attempt():
    initial = Hand(cards=[Card('A', 'spades'), Card('A', 'hearts')], bet=1.0)
    shoe = MockShoe([
        Card('2', 'clubs'),
        Card('3', 'diamonds'),
        Card('9', 'hearts'),  # extra card if double were allowed
    ])
    strat = SplitThenDoubleStrategy()
    player = Player(
        settings=PlayerSettings(bankroll=100, split_aces_logic="Single", double_after_split=True),
        strategy=strat,
    )
    hands = player.play(shoe, dealer_up='5', initial=initial)
    assert all(len(h.cards) == 2 for h in hands)
    assert len(shoe.drawn) == 2
    assert player.settings.bankroll == 99


def test_carnival_allows_hits_and_doubles():
    initial = Hand(cards=[Card('A', 'spades'), Card('A', 'hearts')], bet=1.0)
    shoe = MockShoe([
        Card('5', 'clubs'),
        Card('6', 'diamonds'),
        Card('9', 'hearts'),
        Card('T', 'spades'),
    ])
    strat = SplitThenDoubleStrategy()
    player = Player(
        settings=PlayerSettings(bankroll=100, split_aces_logic="Carnival", double_after_split=True),
        strategy=strat,
    )
    hands = player.play(shoe, dealer_up='5', initial=initial)
    assert all(len(h.cards) == 3 for h in hands)
    assert len(hands) == 2
    assert player.settings.bankroll == 97


def test_carnival_split_limit_enforced():
    initial = Hand(cards=[Card('A', 'spades'), Card('A', 'hearts')], bet=1.0)
    shoe = MockShoe([
        Card('A', 'clubs'),
        Card('A', 'diamonds'),
        Card('A', 'hearts'),
        Card('A', 'spades'),
        Card('5', 'clubs'),
        Card('6', 'clubs'),
        Card('7', 'clubs'),
        Card('8', 'clubs'),
    ])
    player = Player(
        settings=PlayerSettings(bankroll=100, split_aces_logic="Carnival"),
        strategy=AlwaysSplitStrategy(),
    )
    hands = player.play(shoe, dealer_up='5', initial=initial)
    assert len(hands) == 4
    assert all(hand.is_split_aces for hand in hands)
