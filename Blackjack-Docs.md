## CasinoSimulations™️ Blackjack

A full-screen, terminal-based blackjack game built for practicing real-money
play, card counting, and casino-accurate table procedure. It runs in a
`curses` TUI, deals against a configurable multi-deck shoe, mimics the order
and timing of a real table (dealing, prompts, and settlement all proceed
rightmost-spot-first, one card/decision at a time), and tracks a live Hi-Lo
running/true count so you can rehearse bet-spread strategy against a
realistic table.

### Highlights

**Table & dealing**

- **Full-screen curses UI** that launches maximized and dynamically
  re-centers the whole table (cards, wagers, results, stats) around whatever
  terminal size it gets.
- **Three always-visible spots** — Hand #1 sits center, Hand #2 fills to the
  left, Hand #3 fills to the right — separated by a decorative `♦` divider,
  evenly spaced with any leftover width left unused on the far right.
- **Real-table dealing order**: cards are dealt, and prompts/actions are
  taken, rightmost active spot first working left (mirroring how a live
  dealer works around a table), not left-to-right. The initial deal animates
  one card at a time (250ms/card) in that same order.
- **Dealer card stack**: before the hole card is revealed, the dealer's two
  cards render as a real stack — the up-card fully visible on top, the hole
  card's back peeking out just below and to the right of it — instead of
  sitting side by side. Once revealed (or during the dealer's own turn), it
  switches to the same fanned row every other hand uses.
- **Dealer's box**: a `♦`-bordered rectangle frames the dealer's hand —
  top border is the dashed line under the red status bar, sides run down
  the same dividers that separate the three spot columns, bottom border is
  its own `♦` row sitting just past the dealer's card stack. On the rare
  hand big enough to spill past it, the cards simply draw over the border
  glyphs rather than getting clipped or hidden. Each player column's own
  `♦` divider, by contrast, only starts at the settlement-banner row right
  above the wager box — it no longer runs up alongside the cards, so it
  reads as bordering just the wager area, not the whole spot.
- **Player column order, top to bottom**: any already-completed split
  hands' collapsed values, directly above the cards (no gap) — cards —
  the current hand's value (doubling as the Early Surrender?/Insurance?/
  Even Money?/Double? prompt when one applies) directly below the cards,
  no gap — the main settlement banner — the wager box — the side-bet
  boxes — the side-bet banner. The rare 13+-card overflow ticker moved
  down below the side-bet banner, out of the way of the main flow.

**Configurable table rules** (all changeable live via commands, no restart
required)

- Number of decks (1–12) and penetration (fraction of the shoe dealt before
  a reshuffle)
- Double after split (DAS)
- Resplit aces (RSA), with a configurable max resulting hands (2–4), and an
  optional face-down deal for split-ace cards (only while RSA itself is off)
- Blackjack payout: 3:2 or 6:5
- Surrender mode: late, early (Ace up-card only, and never offered on a
  player blackjack — that's an even-money decision instead), or off
- Dealer hits or stands on soft 17 (H17/S17)
- Whether the running/true count displays at all (`hilo on/off` — it's
  still tracked internally either way, just visible or not)

Deck count, penetration, blackjack payout, and dealer soft-17 behavior —
the four settings on the blue rules-summary line — only ever take effect
at the *next* shuffle, so you never play through one shoe under two
different rulesets. Change one mid-shoe and a "\* Rule Changes Pending \*"
flag lights up next to the card count until the next reshuffle (`newshoe`,
or the automatic one when the shoe runs low) actually applies it; until
then, the blue and red summary lines keep showing what's really in effect,
not what's queued up. Every other rule (DAS, RSA, surrender, table limits,
double options, side bets) applies immediately.
- Max hands from splitting non-ace pairs (1–8)
- Table min/max wagers
- Optional face-down double-down card (revealed only at the dealer's
  reveal/settlement step)
- Optional **"double on a natural blackjack"** rule (see below)

**Multi-hand play & splits**

- Bet and play 1–3 simultaneous hands per round.
- Splits (up to the configured max, including resplit aces) are tracked
  independently per hand, each playing out in turn in table order.
- A split spot's settlement banner tallies its hands in words — e.g.
  "2 Wins/1 Loss". A hand that was both split *and* doubled down is its own
  DDWin/DDLoss category rather than folded into the plain Win/Loss counts —
  e.g. splitting a pair, doubling one hand to a win while the other also
  wins, reads "1 DDWin/1 Win", not "2 Wins", since only one of those two
  hands actually had twice the money riding on it.
- **Split aces** always stand on the single hard total they're actually
  standing on once resolved — a hand that drew a ten-value card after
  splitting aces shows "\*21\*", never a lingering soft "\*11/21\*".

**Player actions**

- `Hit`, `Stand`, `Double`, `Split`, `Surrender` (late surrender only, when
  enabled), each hinted on screen for whatever's legal on the current hand.
- **Double down**: doubles the wager, draws exactly one card. With "double
  facedown" on, that card is dealt face down *only* on a hand with little
  or no bust risk — a soft total, or a hard total of 11 or fewer — computed
  from the hand's original two cards before the double card is drawn; a
  hard 12+ always deals its double card face up, so an immediate bust stays
  visible. It only flips up at the dealer's reveal step when it was dealt
  face down at all. A double that busts settles immediately either way.
- **Double on a natural blackjack** (`double blackjack on`): instead of an
  automatic 3:2 payout, a dealt blackjack prompts `Double?` (`D` accepts,
  `RETURN` declines) — a natural can never bust when doubled (Ace forced to
  1 plus any single card is always ≤21), so an accepted double just becomes
  an ordinary, still-live 3-card hand. On a dealer Ace up-card, this is only
  offered *after* even money is declined *and* the peek confirms the dealer
  does **not** also have blackjack; declining keeps the ordinary instant
  blackjack settlement.
- **Late surrender** settles immediately mid-turn — half the wager returns
  right away, posted to the settlement banner on the spot.

**Insurance, even money & the dealer peek**

- American-style peek: the dealer checks the hole card for blackjack
  whenever the up-card is an Ace or any ten-value card. A ten-value peek is
  silent (no side bet offered) — it just protects you from playing,
  doubling, or splitting into an already-decided dealer blackjack.
- On an Ace up-card only: a player blackjack is offered **even money**
  instead of insurance; every other hand is offered **insurance**, sized to
  exactly half its main wager. Insurance pays 2:1 (a 3x return) if the
  dealer has blackjack, and settles into the *same* side-bet banner as
  Power Poker/Star 21/Buster ("Side Bets Total"), not a banner of its own.
- **Early surrender** (when enabled) is offered before the peek, Ace
  up-cards only, and is never offered on a player blackjack.

**Settlement — timing and banner colors**

Every settlement type posts to its banner *as soon as it's decided*, not
all at once at the end of the round:

| Event | When it settles | Banner text | Color |
|---|---|---|---|
| Power Poker / Star 21 | Immediately after the deal (both only need the first 2 cards + dealer up-card) | side-bet label, e.g. "STRAIGHT FLUSH" | bet-specific accent |
| Insurance | The instant the dealer's hole card is peeked | "INSURANCE" (row 1), folded into "Side Bets Total" (row 2) | beige / black |
| Player blackjack (unbeaten) | Immediately, once the dealer is confirmed clean | "BLACKJACK" | yellow on dark purple |
| Dealer blackjack | Immediately, at the peek | "DEALER BLACKJACK" | white on maroon |
| Even money | Immediately, on acceptance | "EVEN MONEY" | white on dark green |
| Early/late surrender | Late: immediately on the action. Early: recorded up front, credited with the round | "Surrender"/"Surrendered" | white on dark green |
| Bust (hit or double) | Immediately, the instant it busts | "BUST" | white on deep red |
| Double down win/loss | With the rest of the round (needs the dealer's final hand) | "Double Down Win"/"Double Down Loss" | white on dark green |
| Ordinary win/loss/push | With the rest of the round | "Win"/"Lose"/"Push" | white on dark green |
| Dealer Buster | With the rest of the round (needs the dealer's full hand) | "N Card Bust" / "8+ Card Bust" | bet-specific accent |

**Side bets**

Three optional side bets, each with its own paytable shown live in the
stats bar, its own themed wager cell, and its own min/max bet:

- **Power Poker** — your first two cards plus the dealer's up-card, scored
  as a 3-card poker hand:

  | Hand | Pays |
  |---|---|
  | Royal Flush | 50:1 |
  | Straight Flush | 40:1 |
  | Trips | 25:1 |
  | Straight | 10:1 |
  | Flush | 3:1 |

  Requires **3+ decks** in the live shoe — firmly disabled below that (the
  odds swing too far in the player's favor with fewer decks in play).

- **Star 21** — the same three cards summed like a 21 total. Requires **2+
  decks**; the paytable itself depends on exactly how many:

  | Hand | Payout (Standard) | Payout (Double Deck) |
  |---|---|---|
  | Suited 7-7-7♦ | 5000:1 | –– |
  | Suited 7-7-7 | 500:1 | –– |
  | Suited 6-7-8 | 100:1 | 500:1 |
  | Unsuited 7-7-7 | 50:1 | –– |
  | Suited 21 | 30:1 | 50:1 |
  | Unsuited 6-7-8 | 20:1 | 40:1 |
  | Unsuited 21 | 8:1 | 10:1 |
  | Any 20 | 4:1 | 4:1 |
  | Any 19 | 3:1 | 3:1 |

- **Dealer Buster** — pays out when the dealer busts, scaled by how many
  cards it took. No deck-count restriction, but an 8+ card bust pays out
  higher on a single-deck shoe:

  | # of Cards | Payout (2+ decks) | Payout (Single Deck) |
  |---|---|---|
  | 8+ | 250:1 | **500:1** |
  | 7 | 100:1 | 100:1 |
  | 6 | 50:1 | 50:1 |
  | 5 | 12:1 | 12:1 |
  | 4 | 3:1 | 3:1 |
  | 3 | 2:1 | 2:1 |

  Whenever a shoe is cut (session start, `newshoe`, or the automatic
  post-round reshuffle) that no longer supports an enabled Power Poker or
  Star 21 bet, it's force-disabled automatically — the `gamerules` screen
  and the wager grid both reflect a locked bet as "off".

**Card counting**

- Running count and true count (Hi-Lo) are visible in the header by
  default — toggle them off with `hilo off` to practice counting blind
  (the count is still tracked internally either way, just not displayed)
  and `hilo on` to bring them back.
- The displayed count only ever reflects cards you've actually seen: it
  climbs one card at a time as the deal animates, never jumps ahead to the
  round's final value early, and excludes the dealer's hole card (and any
  face-down double-down/resplit-aces card) until it's actually revealed —
  so nothing about the count can tip you off to an outcome before the
  table shows it to you.
- The shoe reshuffle is deliberately deferred until you're back at the
  betting screen between rounds (never mid-round), so a count you bet off
  of is never invalidated partway through a hand.
- A "** NEW SHOE **" flash lights up the command-line input the instant a
  fresh shoe cuts in, so it's hard to miss even mid-focus.

**Bet spread reference**

A full-screen `betspread` table with $10/$25/$100 minimum-table variants,
each showing 1:10, 1:12, and 1:15 spreads by true count, as a quick
reference while you play.

**Sound effects**

Optional audio cues, played through whichever of `afplay`/`paplay`/
`aplay`/`ffplay`/`mpg123` is on your system `PATH` — the game runs
completely fine with no sound at all if none of those are found. Drop the
matching file into `cs-blackjack/sounds/` (see that folder's own
`README.md`) and it plays automatically, no restart or config needed:

| File | Plays when |
|---|---|
| `card-deal.mp3` | Each card the dealer deals, and each face-down card (the dealer's hole card, a face-down double/RSA card) turning face up. |
| `sidebet-normal-win.wav` | A side-bet win paying 49:1 or lower. |
| `sidebet-big-win.wav` | A side-bet win paying 50:1 or higher. |
| `wager-win.wav` | A round that settles with a positive net return overall. |
| `bust-sound.wav` | A player hand busting (a hit, or a face-up double-down), or the dealer's hand busting. |

**Bankroll and statistics**

- A **lifetime** panel (main-bet P/L $, side-bet P/L $, EV % on main
  wagers, hands played, wins/losses/pushes/surrenders, 8+ card dealer
  busts, and Star 21 7-7-7♦ hits) and a **session** panel (bankroll,
  main/side-bet P/L $, hands played, wins/losses/pushes, surrenders,
  doubles, splits, and blackjacks dealt this session). Both are saved to
  disk automatically.
- Both panels hold their pre-round numbers for the whole round and only
  catch up to the real values once it's fully settled — even though some
  outcomes (an immediate blackjack, a side bet win) are internally decided
  well before that. Without this, those numbers ticking up early would be
  its own tell, well before the deal animation or a settlement banner
  actually shows you the result.
- `hardreset` (type `confirm`) wipes the lifetime panel back to zero *and*
  resets the bankroll to its default, alongside the usual shoe/session
  reset.
- **Net Return**: a running "Net Return: $X.XX" figure on the red status
  bar, directly below Bankroll, tracking this round's cumulative result
  across all three spots' main wagers, side bets, and insurance combined.
  It starts as the negative of everything wagered (a debit) the instant
  your wagers are dealt, and climbs back toward — and past — zero as
  results settle in, same as the stats panel: nothing updates ahead of an
  animation or a settlement banner actually showing it to you. It
  disappears once you press RETURN to move past a settled round, and
  reappears the moment your next round's wagers are dealt.

**Shoe/session management**

- `newshoe` and `newsession` (each with a RETURN confirmation) reshuffle
  the shoe, or reshuffle plus reset session stats. Neither one touches
  your bankroll.
- `bank reset` (RETURN confirms) resets just the bankroll to its default,
  independent of the shoe or any stats.

**Mouse or keyboard**

- The betting grid's wager and side-bet cells can be clicked directly, in
  addition to arrow-key navigation.
- **Arrow-key navigation is direction-relative**, matching the cells'
  actual on-screen layout instead of a fixed left/right-for-spots,
  up/down-for-bet-type scheme: `LEFT`/`RIGHT` on a main wager cell moves
  between spots as before; `DOWN` from a main wager cell drops onto that
  spot's side-bet row, landing on Star 21 (the enabled bet closest to
  center) or whichever enabled side bet is closest to it; `LEFT`/`RIGHT`
  on a side-bet cell moves across the whole side-bet row as one continuous
  strip, crossing straight from one spot's Buster cell into the next
  spot's Power Poker cell at the boundary; `UP` from any side-bet cell
  returns to that same spot's own main wager cell. A disabled side bet is
  skipped entirely, same as before.
- The command line can be focused either by clicking it or by pressing `/`
  — typing never lands in the command line any other way, so a stray
  keystroke mid-round can't silently start building a command behind your
  back.
- Clicking anywhere that isn't a wager cell, a side-bet cell, or the
  command line clears whatever's currently highlighted; clicking a real
  cell (or using the arrow keys, or `/`) highlights it again as normal.
- Keyboard input queued up while a settlement banner is still cycling is
  discarded before the next hand starts, so a stray extra RETURN press
  can't accidentally fire an action on the next deal.

**Full-screen reference screens**

`help`/`?` for the command list, `gamerules` for the active table rules
(including any side bet currently deck-locked), `stats` for the full
lifetime/session numbers, and `betspread` for the bet-spread reference
tables — all one keypress away, no need to memorize anything up front.

### Requirements

- Python 3.9 or later
- The standard library `curses` module — this ships with Python on Linux
  and macOS; on Windows you'll need to `pip install windows-curses` first
- A terminal that supports full-screen/maximize (the game sends a maximize
  escape sequence on launch) and is at least **198x48** — it will refuse to
  draw the table and show a "too small" message below that size

No third-party packages are required to run the game itself.

### Download & Install

```bash
git clone <repo-url>
cd CasinoSimulations
```

That's it — `cs-blackjack` is pure standard library, so there's nothing to
`pip install`.

### Launch

Run it as a module from the repository root:

```bash
python3 -m cs-blackjack
```

The game maximizes your terminal window on launch. Your bankroll, lifetime
and session stats, and table rules are saved to `~/.cs-blackjack_state.json`
and reloaded automatically the next time you launch.

### Playing

- **Betting grid**: arrow keys (or a mouse click) move between the wager
  cells for each spot (main wager plus the three side bets); type digits to
  set an amount for the highlighted cell, then RETURN to confirm it (or to
  deal, once your wagers are set). The command line reads "`[RETURN] to
  Deal`" by default; after a new shoe/session message shows there instead,
  it reverts back to that default 2 seconds later.
- **In a hand**: `SPACE` Hit, `RETURN` Stand, `D` Double, `P` Split, `S`
  Surrender.
- **Prelim prompts** (shown with their own key hints on screen): early
  surrender (`S` surrender, `RETURN` continue), insurance/even money
  (`SPACE` yes, `RETURN` no), and — with `double blackjack on` — the
  natural-blackjack double offer (`D` double, `RETURN` decline).
- **Commands**: click the input line (or press `/`) and type at the bottom
  of the screen. Run `help` at any time for the full, up-to-date command
  reference — it covers every rule toggle, bankroll/table-setup command,
  side bet configuration, and shoe/session control.

### Command reference

**Rules**

| Command | Effect |
|---|---|
| `das on/off` | Double after split |
| `rsa on/off [maxsplit N]` | Resplit aces (max resulting hands, up to 4) |
| `rsa facedown on/off` | Deal split-ace cards face down (RSA off only) |
| `bj32` / `bj65` | Blackjack pays 3:2 or 6:5 (next shuffle) |
| `surr late/early/off` | Surrender mode |
| `h17` / `s17` | Dealer hits / stands on soft 17 (next shuffle) |
| `decks N` | Number of decks, 1–12 (next shuffle) |
| `deckpen 0.NN` | Deck penetration before reshuffle (next shuffle) |
| `splitmax N` | Max hands from splitting non-ace pairs |
| `tablemin N` / `tablemax N` | Table wager limits |
| `double facedown on/off` | Deal the double-down card face down |
| `double blackjack on/off` | Offer a double instead of an automatic 3:2 payout on a natural |
| `hilo on/off` | Show/hide the running and true count (still tracked either way) |

**Bankroll**

| Command | Effect |
|---|---|
| `bank N` | Set bankroll to N |
| `bank add N` | Add N to bankroll |
| `bank reset` | Reset bankroll to its default (RETURN confirms) |
| `bank default N` | Set the bankroll `bank reset`/`hardreset` resets to |

**Table setup**

| Command | Effect |
|---|---|
| `hands 1-3` | Simultaneous hands to play |

**Side bets**

| Command | Effect |
|---|---|
| `powerpoker on/off [minbet N] [maxbet N]` | Requires 3+ decks in the live shoe |
| `star21 on/off [minbet N] [maxbet N]` | Requires 2+ decks (2 decks uses its own paytable) |
| `buster on/off [minbet N] [maxbet N]` | No deck restriction; single deck pays 500:1 on an 8+ card bust |

**Shoe / session**

| Command | Effect |
|---|---|
| `newshoe` | Reshuffle a fresh shoe (RETURN confirms) |
| `newsession` | Reset shoe + session stats, bankroll untouched (RETURN confirms) |
| `hardreset` | Reset lifetime stats + session stats + shoe + bankroll (type `confirm`) |

**Reference**

| Command | Effect |
|---|---|
| `betspread` | Show the $10/$25/$100 bet spread reference tables |
| `help` / `?` | Show the full command list |
| `gamerules` | Show the full table-rules screen |
| `stats` | Show the lifetime/session stats screen |
| `quit` / `exit` | Quit cs-blackjack |

Side bet payout odds are always shown live in the stats bar below the
table, so there's no separate command to look them up.

### Round flow

1. **Wager** — set your main wager(s) and any side bets, then RETURN to
   deal.
2. **Deal** — each active spot gets two cards, then the dealer, twice —
   rightmost spot first, animated one card at a time.
3. **Side bet settlement** — Power Poker and Star 21 settle and pay out
   immediately; nothing about them waits on the peek or your play.
4. **Peek / insurance / even money / early surrender** — only on an Ace or
   ten-value dealer up-card. Insurance settles the instant the peek
   happens.
5. **Blackjack settlement** — any player and/or dealer blackjack settles
   here (or, with `double blackjack on`, offers a double instead of an
   automatic payout once a dealer blackjack is ruled out).
6. **Play** — each live hand plays in turn, in table order; a surrender or
   a bust on that hand settles immediately, right there, rather than
   waiting for the rest of the round.
7. **Dealer's hand** — drawn according to the configured S17/H17 rule.
8. **Main wager + Buster settlement** — every hand not already settled pays
   or forfeits here, and Dealer Buster (which needed the dealer's complete
   hand) settles alongside it.

### Project structure

| File | Responsibility |
|---|---|
| `cards.py` | `Card`, `Shoe` (shuffling, drawing, Hi-Lo running/true count) |
| `hand.py` | `Hand` — cards, totals (soft/hard), blackjack/bust/split/double state |
| `dealer.py` | Dealer drawing logic (S17/H17) |
| `sidebets.py` | Power Poker / Star 21 (standard + double-deck) / Dealer Buster evaluators and their deck-count gating |
| `rules.py` | `Rules`/`SideBetRules` — every configurable table rule, with JSON (de)serialization |
| `stats.py` | Lifetime and session statistics tracking |
| `persist.py` | Load/save all state to `~/.cs-blackjack_state.json` |
| `commands.py` | Parses and applies every CLI command |
| `engine.py` | `GameSession`/`Round` — the full round state machine: dealing order, prelim prompts, player actions, settlement timing |
| `ui.py` | The `curses` TUI: layout, rendering, animation, input handling |
| `sound.py` | Fire-and-forget sound-effect playback (see `sounds/README.md`) |
| `__main__.py` | `python3 -m cs-blackjack` entry point |

### Data storage

All game state — bankroll, lifetime and session statistics, and table rules
— is persisted as JSON to `~/.cs-blackjack_state.json`. Delete that file to
reset everything back to defaults.
