from blackjack.simulator import Simulator
from blackjack.settings import SimulationSettings
from blackjack.simulator import Simulator


def run_sim(tmp_path):
    strategy = tmp_path / "strategy.json"
    strategy.write_text("{}")
    settings = SimulationSettings(
        trials=1,
        hands_per_game=2,
        bankroll=10,
        blackjack_payout=1.5,
        double_after_split=True,
        resplit_aces=False,
        bet_amount=1.0,
        num_decks=1,
        hit_soft_17=False,
        penetration=0.75,
        strategy_file=str(strategy),
        database=":memory:",
        seed=1,
    )
    sim = Simulator(settings)
    sim.run()
    return sim


def test_save_results_moves_temp_to_permanent(tmp_path):
    sim = run_sim(tmp_path)
    cur = sim.conn.cursor()

    cur.execute("SELECT COUNT(*) FROM temp_summary")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM summary")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM temp_results")
    assert cur.fetchone()[0] > 0
    cur.execute("SELECT COUNT(*) FROM results")
    assert cur.fetchone()[0] == 0

    sim.save_results()

    cur.execute("SELECT COUNT(*) FROM summary")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM temp_summary")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM results")
    assert cur.fetchone()[0] > 0
    cur.execute("SELECT COUNT(*) FROM temp_results")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT COUNT(*) FROM bankroll")
    assert cur.fetchone()[0] > 0
    cur.execute("SELECT COUNT(*) FROM temp_bankroll")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT COUNT(*) FROM card_distribution")
    assert cur.fetchone()[0] > 0
    cur.execute("SELECT COUNT(*) FROM temp_card_distribution")
    assert cur.fetchone()[0] == 0

    sim.close()


def test_discard_results_clears_temp_tables(tmp_path):
    sim = run_sim(tmp_path)
    cur = sim.conn.cursor()

    cur.execute("SELECT COUNT(*) FROM temp_bankroll")
    assert cur.fetchone()[0] > 0
    cur.execute("SELECT COUNT(*) FROM temp_results")
    assert cur.fetchone()[0] > 0

    sim.discard_results()

    cur.execute("SELECT COUNT(*) FROM temp_bankroll")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM temp_summary")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM temp_card_distribution")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM temp_results")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT COUNT(*) FROM bankroll")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM summary")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM card_distribution")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM results")
    assert cur.fetchone()[0] == 0

    sim.close()
