import argparse
import sys
import traceback
from pathlib import Path
from tkinter import TclError


def _bootstrap_imports():
    """Allow running as both a module and a standalone script.

    When executed directly (e.g. ``python blackjack/__main__.py``), the
    package-relative imports fail because Python does not set a parent
    package. This helper detects that scenario, amends ``sys.path`` to include
    the repository root, and then performs absolute imports so the rest of the
    file can run normally.
    """

    global SimulatorGUI, SimulationSettings, DEFAULT_STRATEGY_FILE, Simulator

    try:  # Running as a package ("python -m blackjack")
        from .gui import SimulatorGUI
        from .settings import SimulationSettings, DEFAULT_STRATEGY_FILE
        from .simulator import Simulator
    except ImportError:
        package_root = Path(__file__).resolve().parent.parent
        if str(package_root) not in sys.path:
            sys.path.insert(0, str(package_root))

        from blackjack.gui import SimulatorGUI
        from blackjack.settings import SimulationSettings, DEFAULT_STRATEGY_FILE
        from blackjack.simulator import Simulator


_bootstrap_imports()


def parse_args() -> SimulationSettings:
    parser = argparse.ArgumentParser(description="Blackjack simulator")
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--rounds-per-trial", type=int, default=1)
    parser.add_argument("--hands-per-round", type=int, default=100)
    parser.add_argument("--bankroll", type=float, default=1000.0)
    parser.add_argument("--payout", type=float, default=1.5)
    parser.add_argument("--das", action="store_true")
    parser.add_argument(
        "--split-aces-logic",
        choices=["single", "carnival"],
        default="single",
        help="Choose split-aces behavior (single or carnival)",
    )
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
        rounds_per_trial=args.rounds_per_trial,
        hands_per_round=args.hands_per_round,
        bankroll=args.bankroll,
        blackjack_payout=args.payout,
        double_after_split=args.das,
        split_aces_logic=args.split_aces_logic.title(),
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


def run_cli(settings: SimulationSettings | None = None):
    settings = settings or parse_args()
    sim = Simulator(settings)
    sim.run()
    if not settings.test_mode:
        sim.save_results()
    else:
        print("Test mode enabled: results kept in temporary tables only.")
    sim.close()


def main():
    try:
        if len(sys.argv) > 1:
            print(
                "Launching GUI; command line arguments will be used only if GUI startup fails.",
                file=sys.stderr,
            )
        run_gui()
    except Exception as exc:
        print(
            "An error occurred while launching the GUI. Attempting to fall back to CLI execution.\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
        traceback.print_exc()
        try:
            cli_settings = parse_args()
        except SystemExit:
            # argparse has already printed an error message
            return
        except Exception as parse_exc:
            print(
                "Failed to parse CLI arguments after GUI launch error.\n"
                f"Details: {parse_exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        run_cli(cli_settings)


if __name__ == "__main__":
    main()
