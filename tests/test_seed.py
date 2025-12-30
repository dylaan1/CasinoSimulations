from blackjack.simulator import Simulator
from blackjack.settings import SimulationSettings


def test_simulator_seed_reproducible(tmp_path):
    strategy_file = tmp_path / "strategy.json"
    strategy_file.write_text("{}")
    settings = SimulationSettings(
        trials=1,
        rounds_per_trial=1,
        hands_per_round=5,
        bankroll=10,
        blackjack_payout=1.5,
        double_after_split=True,
        split_aces_logic="Single",
        bet_amount=1.0,
        num_decks=1,
        hit_soft_17=False,
        penetration=0.75,
        strategy_file=str(strategy_file),
        database=":memory:",
        seed=42,
    )
    sim1 = Simulator(settings)
    sim1.run()
    cur1 = sim1.conn.cursor()
    cur1.execute("SELECT card, count FROM temp_card_distribution ORDER BY card")
    dist1 = cur1.fetchall()
    sim1.close()

    sim2 = Simulator(settings)
    sim2.run()
    cur2 = sim2.conn.cursor()
    cur2.execute("SELECT card, count FROM temp_card_distribution ORDER BY card")
    dist2 = cur2.fetchall()
    sim2.close()

    assert dist1 == dist2

