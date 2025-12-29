from blackjack.player import Player, PlayerSettings
from blackjack.hand import Hand
from blackjack.cards import Card


class AlwaysSurrenderStrategy:
    def decide(self, hand, dealer_up, options):
        return 'surrender'


class DummyShoe:
    def draw(self):
        raise AssertionError('draw should not be called after surrender')


def resolve(hand, dealer_hand):
    if hand.surrendered:
        return hand.bet
    if hand.is_bust:
        return 0
    dealer_bust = dealer_hand.is_bust
    if dealer_bust:
        return hand.bet * 2
    player_value = hand.best_value
    dealer_value = dealer_hand.best_value
    if player_value > dealer_value:
        return hand.bet * 2
    if player_value < dealer_value:
        return 0
    return hand.bet


def test_surrender_payout_returns_half_bet():
    settings = PlayerSettings(bankroll=100)
    bet = 10
    settings.bankroll -= bet
    initial = Hand(cards=[Card('9', 'spades'), Card('7', 'hearts')], bet=bet)
    player = Player(settings=settings, strategy=AlwaysSurrenderStrategy())
    hands = player.play(DummyShoe(), dealer_up='6', initial=initial, allow_surrender=True)
    hand = hands[0]
    assert hand.surrendered
    assert hand.bet == bet / 2
    dealer_hand = Hand(cards=[Card('10', 'clubs'), Card('7', 'diamonds')])
    payout = resolve(hand, dealer_hand)
    settings.bankroll += payout
    assert settings.bankroll == 95


class CountingShoe:
    def __init__(self):
        self.count = 0

    def draw(self):
        self.count += 1
        return Card('2', 'hearts')


class OptionAwareStrategy:
    def decide(self, hand, dealer_up, options):
        return 'surrender' if options.get('can_surrender') else 'hit'


def test_no_surrender_hits_when_disabled():
    settings = PlayerSettings(bankroll=100, surrender="none")
    bet = 10
    settings.bankroll -= bet
    initial = Hand(cards=[Card('9', 'spades'), Card('7', 'hearts')], bet=bet)
    shoe = CountingShoe()
    player = Player(settings=settings, strategy=OptionAwareStrategy())
    hands = player.play(shoe, dealer_up='9', initial=initial, allow_surrender=False)
    hand = hands[0]
    assert not hand.surrendered
