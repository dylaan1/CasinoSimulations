# CasinoSimulations™

## cs-blackjack

A full-screen, terminal-based blackjack game built for practicing real-money
play and card counting. It runs in a `curses` TUI, deals against a
configurable multi-deck shoe, and tracks a live Hi-Lo running/true count so
you can rehearse bet-spread strategy against a realistic table.

**CLI-based Settings**

- **Full-screen curses UI**: launches maximized and centers the whole table
  (cards, wagers, results, stats) around whatever terminal size it gets.
- **Configurable table rules**: number of decks and penetration, double after
  split (DAS), resplit aces (RSA, with a configurable max resulting hands),
  blackjack payout (3:2 or 6:5), surrender mode (late / early / off — early
  surrender correctly restricted to Ace-only situations, with even money
  offered instead on a player blackjack), dealer hits/stands on soft 17,
  split max hands, table min/max wagers, and an optional face-down
  double-down card.
- **Multi-hand play**: bet and play 1–3 simultaneous hands per round, with
  splits (up to the configured max, including resplit aces) tracked
  independently per hand.
- **Three side bets**, each with its own paytable and settlement line:
  - **Power Poker** — your first two cards plus the dealer's up-card,
    scored as a 3-card poker hand (trips, straight, flush, straight flush,
    royal flush).
  - **Star21** — the same three cards summed like a 21 total, with bonus
    payouts for suited 20/21, suited/unsuited 6-7-8 and 7-7-7, and a 5000:1
    jackpot for Suited 7-7-7♦.
  - **Dealer Buster** — pays out when the dealer busts, scaled by how many
    cards it took (up to 250:1 for an 8+ card bust).
- **Live card counting**: running count and true count are always visible,
  and the shoe reshuffle is deliberately deferred until you're back at the
  betting screen between rounds (never mid-round), so a count you bet off
  of is never invalidated partway through a hand.
- **Bet spread reference**: a full-screen `betspread` table with $10/$25/$100
  minimum-table variants, each showing 1:10, 1:12, and 1:15 spreads by true
  count, as a quick reference while you play.
- **Bankroll and statistics**: a lifetime panel (main-bet P/L $, side-bet
  P/L $, EV% on main wagers, hands played, wins/losses/pushes/surrenders,
  8+ card dealer busts, and Star21 7-7-7♦ hits) and a session panel
  (bankroll, main/side-bet P/L $, hands played, wins/losses/pushes,
  surrenders, doubles, splits, and blackjacks dealt this session). Both are
  saved to disk automatically; `hardreset` (with a typed `confirm`) wipes
  the lifetime panel back to zero without touching your bankroll or session
  stats.
- **Shoe/session management**: `newshoe` and `newsession` commands (with a
  confirmation step) to reshuffle or fully reset stats on demand.
- **Mouse or keyboard**: the betting grid's wager and side-bet cells can be
  clicked directly, in addition to arrow-key navigation.
- **Full-screen reference screens**: `help` / `?` for the command list,
  `gamerules` for the active table rules, `betspread` for the bet-spread
  reference tables — all one keypress away, no need to memorize anything
  up front.

**Requirements**

- Python 3.9 or later
- The standard library `curses` module — this ships with Python on Linux
  and macOS; on Windows you'll need to `pip install windows-curses` first
- A terminal that supports full-screen/maximize (the game sends a maximize
  escape sequence on launch) and is at least **402x48** — the layout uses a
  fixed side margin and reserves room for a fully split 12-hand table, so it
  needs a genuinely wide terminal; it will refuse to draw the table and show
  a "too small" message below that size

No third-party packages are required to run the game itself.

**Download & Install**

```bash
git clone <repo-url>
cd CasinoSimulations
```

That's it — `cs-blackjack` is pure standard library, so there's nothing to
`pip install`.

**Launch**

Run it as a module from the repository root:

```bash
python3 -m cs-blackjack
```

The game maximizes your terminal window on launch. Your bankroll, lifetime
and session stats, and table rules are saved to `~/.cs-blackjack_state.json`
and reloaded automatically the next time you launch.

**Playing**

- **Betting grid**: arrow keys (or a mouse click) move between the wager
  cells for each spot (main wager plus the three side bets); type digits to
  set an amount for the highlighted cell, then RETURN to confirm it (or to
  deal, once your wagers are set).
- **In a hand**: `SPACE` Hit, `RETURN` Stand, `D` Double, `P` Split, `S`
  Surrender. Insurance/even money and early surrender prompts use their own
  key hints shown on screen at the time.
- **Commands**: type at the input line at the bottom of the screen. Run
  `help` at any time for the full, up-to-date command reference — it covers
  every rule toggle, bankroll/table-setup command, side bet configuration,
  and shoe/session controls.

**Data Storage**

All game state — bankroll, lifetime and session statistics, and table rules
— is persisted as JSON to `~/.cs-blackjack_state.json`. Delete that file to
reset everything back to defaults.
