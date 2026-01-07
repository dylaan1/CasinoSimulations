from blackjack.simulator import Simulator
from blackjack.settings import SimulationSettings


def test_save_results_creates_seed_snapshot(tmp_path):
    strategy_file = tmp_path / "strategy.json"
    strategy_file.write_text("{}")
    settings = SimulationSettings(
        rounds=1,
        hands_per_round=3,
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
    )
    sim = Simulator(settings)
    sim.run()
    seed_id = sim.save_results()
    cur = sim.conn.cursor()

    cur.execute("SELECT seed_id, total_rounds, total_hands FROM saved_seeds WHERE seed_id = ?", (seed_id,))
    row = cur.fetchone()
    assert row is not None
    assert row[0] == seed_id
    assert row[1] == 1
    assert row[2] > 0

    cur.execute("SELECT COUNT(*) FROM saved_seed_results WHERE seed_id = ?", (seed_id,))
    assert cur.fetchone()[0] > 0
    cur.execute("SELECT COUNT(*) FROM saved_seed_bankroll WHERE seed_id = ?", (seed_id,))
    assert cur.fetchone()[0] > 0
    sim.close()
