import argparse
import sys
from pathlib import Path
from tkinter import TclError

from .gui import SimulatorGUI
from .settings import SimulationSettings, DEFAULT_STRATEGY_FILE
from .simulator import Simulator


def parse_args() -> SimulationSettings:
    parser = argparse.ArgumentParser(description="Blackjack simulator")
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--hands", type=int, default=100)
    parser.add_argument("--bankroll", type=float, default=1000.0)
    parser.add_argument("--payout", type=float, default=1.5)
    parser.add_argument("--das", action="store_true")
    parser.add_argument("--resplit-aces", action="store_true")
    parser.add_argument("--bet", type=float, default=1.0, help="Base wager per hand")
    parser.add_argument("--decks", type=int, default=6)
    parser.add_argument("--h17", action="store_true", help="Dealer hits on soft 17")
    parser.add_argument("--penetration", type=float, default=0.75)
    parser.add_argument("--strategy", type=str, default=str(DEFAULT_STRATEGY_FILE))
    parser.add_argument("--database", type=str, default="simulation.db")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--test-mode", action="store_true", help="Run without persisting results")
    args = parser.parse_args()
    if not Path(args.strategy).is_file():
        parser.error(f"Strategy file '{args.strategy}' not found.")
    settings = SimulationSettings(
        trials=args.trials,
        hands_per_game=args.hands,
        bankroll=args.bankroll,
        blackjack_payout=args.payout,
        double_after_split=args.das,
        resplit_aces=args.resplit_aces,
        bet_amount=args.bet,
        num_decks=args.decks,
        hit_soft_17=args.h17,
        penetration=args.penetration,
        strategy_file=args.strategy,
        database=args.database,
        seed=args.seed,
        test_mode=args.test_mode,
    )
    return settings


def run_gui():
    gui = SimulatorGUI()
    gui.run()


def run_cli():
    settings = parse_args()
    sim = Simulator(settings)
    sim.run()
    if not settings.test_mode:
        sim.save_results()
    else:
        print("Test mode enabled: results kept in temporary tables only.")
    sim.close()


def main():
    if len(sys.argv) > 1:
        run_cli()
        return

    try:
        run_gui()
    except TclError:
        print("GUI not available. Falling back to CLI.")
        run_cli()


if __name__ == "__main__":
    main()
