# CasinoSimulations™ Blackjack

A desktop blackjack simulator that lets you configure casino rules, run Monte Carlo-style simulations, and visualize results. The app stores run data in SQLite and provides a Tkinter UI for exploring deals, bankroll changes, and saved seeds.

## Features

- **Rule configuration**: adjust decks, penetration, payouts, soft-17 logic, double-after-split, split-aces logic, surrender rules, and base wager/bankroll.
- **Strategy engine**: plug in JSON basic strategy tables (`hard`, `soft`, `pair`) to drive hit/stand/double/split/surrender decisions.
- **Run analysis**: view per-deal results in the data table, including player hands (A–D for splits), dealer cards, running/true count, and bankroll changes.
- **Statistics panel**: aggregate wins/losses/pushes, doubles, splits, surrenders, and average bankroll metrics.
- **Bankroll chart**: plot profit/loss over hands played, filter by round, and hover for round summaries.
- **Seed management**: save or discard runs, favorite seeds, reload saved data, and delete unneeded seeds from the Seed Manager.
- **Test mode**: run simulations without writing to permanent tables for quick experimentation.

## Requirements

- Python 3.11+
- Dependencies (installed via `pip`):
  - `pandas`
  - `matplotlib`
  - `tkinter` (bundled with most Python distributions)

## Download & Install

```bash
git clone <your-repo-url>
cd CasinoSimulations
pip install .
```

Alternatively, for editable development installs:

```bash
pip install -e .
```

## Launch

```bash
python -m blackjack
```

The `blackjack-sim` console entry point is also available after installation:

```bash
blackjack-sim
```

### Test Mode

Run without saving to the permanent SQLite tables:

```bash
python -m blackjack --test-mode
```

Or toggle **Test Mode** in the GUI settings. A red banner appears when test mode is active.

## Data Storage

Simulation output is persisted to the configured SQLite database (`simulation.db` by default). Temporary tables are used for in-progress runs and are only saved when you click **Save**. The Seed Manager provides access to saved runs by seed ID.

## Testing

```bash
pytest
```
