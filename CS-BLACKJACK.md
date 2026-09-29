# CasinoSimulations™

## Blackjack

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
  down below the side-bet banner, out of the way of the main flow. A
  split-ace spot is the one exception to the "collapsed values above the
  cards" convention above: since every ace-split hand is shown in full at
  once (see **Multi-hand play & splits** below), each hand's own value
  sits directly below its own cards, the same relative spot every other
  hand's value occupies — never collapsed above.
- **Two dashed dividers close out the table**, splitting the screen into
  three clear sections stacked top to bottom: the table itself (dealer,
  spots, wagers, side bets), then the command-line section (the
  hint/message line and the input line), then the stats/payout panel.

**Configurable table rules** (all changeable live via commands, no restart
required)

- Number of decks (1–12) and penetration (fraction of the shoe dealt before
  a reshuffle) — either a fixed value (`deckpen 0.NN`) or randomized
  (`deckpen rand`), which re-rolls somewhere in 0.65–0.80 every time a
  fresh shoe is actually cut, so the cut isn't the exact same depth every
  single shoe. A single deck is cut once fewer than 24 cards would be left,
  and a two-deck shoe is never cut deeper than 80% — see **Deck-size limits
  and running out of cards** below
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
- Max hands from splitting non-ace pairs (1–8; 2 on a single-deck shoe)
- Table min/max wagers
- Optional face-down double-down card (revealed only at the dealer's
  reveal/settlement step)
- Optional **"double on a natural blackjack"** rule (see below)

**Multi-hand play & splits**

- Bet and play 1–3 simultaneous hands per round (1–2 on a single-deck
  shoe — see **Deck-size limits and running out of cards** below).
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
  splitting aces shows "\*21\*", never a lingering soft "\*11/21\*". Every
  ace-split hand (up to 4, with RSA) is shown in full at once, each in its
  own equal slice of the spot's column, its value directly below its own
  cards — never collapsed into the above-the-cards chip row non-ace splits
  use.

**Deck-size limits and running out of cards**

A round can run out of cards part-way through — the dealer's hand included —
if a shoe is cut too deep for the hands in play. Two layers keep that from
happening, and from mattering if it does.

*Prevention.* A round only starts if the shoe has enough cards left for the
most a round is likely to use, and the small shoes have tighter rules:

- **A single deck** only starts a round with at least **24 cards left**, so
  no new round starts once more than 28 cards (about 54%) have been dealt —
  the shoe is reshuffled first — whatever `deckpen` says (a shallower
  `deckpen` still applies). It's also held to **at most 2 hands** per round —
  1 or 2, and you can change it any time between rounds (`hands N`, or funding
  or clearing Hand #2 in the wager grid); `hands 3` and funding Hand #3 are
  refused — and to **one split per hand**: a spot splits into at most 2
  hands, so `splitmax` and `rsa on maxsplit` are held to 2 (aces can be split
  once but never resplit). Your own `splitmax`/`rsa` settings aren't
  overwritten; they apply again on any multi-deck shoe.
- **Two decks** are never cut deeper than **80%**, whatever `deckpen` says
  (the command tells you when it caps your setting), and never with fewer
  than 15 cards left.
- **Three or more decks** need **16 cards plus 12 for every hand you're
  playing** left when a round starts: 28 for 1 hand, 40 for 2, 52 for 3. The
  shoe is cut early if a deeper `deckpen` would go past that, and changing
  `hands` between rounds reshuffles right away if the shoe is now too short
  for the new number of hands, before you size a bet against its count. The
  floors come from measurement: over 200,000 rounds per row, one round never
  drew more than 25 cards with 1 hand, 37 with 2, or 44 with 3 — even for a
  player who splits and hits at every chance — so each floor clears the worst
  round seen.

The blue rules-summary line and `gamerules` show the depth a shoe is really
cut at, and the history log records it. Switching to one deck from a game
with 3 hands set (`decks 1`, then the next shuffle) cuts the hands back to 2
automatically.

*The failsafe.* If a shoe runs out in the middle of a round anyway, the game
does what a dealer does: **the discards are shuffled back in and the round
carries on.** Every card already on the table stays put; everything else —
including cards from earlier rounds — is shuffled into a fresh order, with the
table cards counted as already dealt from it. That means the count starts
over: the running count becomes the Hi-Lo total of the cards on the table, and
the true count and "Cards Left" follow from the new shuffle. A "\*\* NEW SHOE
\*\*" flash and a message tell you it happened. Rules queued for the next
shuffle are not applied mid-round. In the history log the exhausted shoe closes
with every card dealt, a new shoe row is opened (`cut_reason` `mid_round`),
and the round's hands are flagged — see **Data storage**.

*How often it matters.* Simulated in 96,000 rounds per configuration, three
play styles each (basic strategy, random legal moves, and split-and-hit
everything). Under the previous rules a round could run out of cards in a real
crash — 2 decks cut at 95% with 3 hands, for instance, about once per 12,000
rounds under basic strategy, and 3 to 8 decks at deep cuts once per 14,000 to
48,000. Now there are **no crashes anywhere**, and the failsafe itself almost
never has a job to do:

- **Single deck:** it never fires, and no line of play at all can even reach it
  — checked against every legal decision sequence on 40,000 shuffles at the
  deepest legal start.
- **Three or more decks:** it never fired in 3, 4, 6 or 8 decks × 1, 2 or 3
  hands, whatever the play style; the same exhaustive search over every line of
  play found none that needs it at the floors above (a few very branchy
  shuffles hit the search's size limit rather than being proven).
- **Two decks:** it fires only for a player who splits every pair and hits every
  hand (about 1 round in 200).

When it does fire, the round just finishes.

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
stats bar, its own themed wager cell, and its own min/max bet. Every
payout figure below is just the shipped default — any of them can be
adjusted live via `powerpoker`/`star21`/`buster <category> <payout>` (see
**Command reference**), and the inline paytable updates immediately to
match, no restart needed.

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
| `card-deal.mp3` | Each card dealt to any hand — the initial deal, a player hit/double/split, or a dealer hit — and each face-down card (the dealer's hole card, a face-down double/RSA card) turning face up. The dealer's own busting card plays this same file, just ~10% louder, instead of `bust-sound.wav`. |
| `sidebet-normal-win.wav` | A side-bet win paying 49:1 or lower, **and** any unbeaten player blackjack, the instant its "BLACKJACK" banner shows (an even-money take shows its own "EVEN MONEY" banner instead and doesn't get this). |
| `sidebet-big-win.wav` | A side-bet win paying 50:1 or higher. |
| `wager-win.wav` | A round that settles with a positive net return overall — except when you're only playing one hand and that hand is the blackjack that just played `sidebet-normal-win.wav`: it alone marks the win then, so this one is skipped rather than doubling up on the same event. Playing more than one hand always gets both, since the win sound there is about the round's overall result, not just the one blackjack hand. |
| `bust-sound.wav` | A player hand busting (a hit, or a face-up double-down), a doubled hand that loses without busting, or a confirmed dealer blackjack (once per round, regardless of push/loss/even-money on any one spot) — not the dealer's own bust. |

A plain main-wager loss, push, or surrender (no double, no bust) stays
silent; only a win, a bust, a losing double, a player or dealer blackjack
adds a sound beyond the ordinary card-deal ones.

**Bankroll and statistics**

- A **lifetime** panel and a **session** panel, side by side, both read
  straight from the history database (see **Data storage**) — the Main UI
  shows both in full (2 sub-columns apiece); the full-screen `stats` command shows the same two tables, plus
  a dedicated payout/occurrence table per side bet underneath them (see
  below). Every table follows the same convention throughout: names
  left-aligned, values right-aligned, columns fixed-width so nothing
  staggers row to row.
- **Lifetime**: EV % (on main wagers only), total lifetime/main-bet/
  side-bet P/L $, Power Poker P/L $, Star 21 P/L $, sessions played, total
  hands dealt, wins/losses/pushes/surrenders.
- **Session**: player/dealer wins, pushes, surrenders, doubles, splits,
  Dealer Pulled 21s (the dealer hitting to a non-blackjack 21), player/
  dealer blackjacks, shoes played, hands dealt, session/main/side-bet
  P/L $, aces split (the number of times you split a pair of aces, not
  the number of aces involved), tens split (same, for ten-value pairs),
  dealer busts, and your **current streak** — "W2"/"L3"-style, a run of
  consecutive winning or losing hands. A push or surrender doesn't touch
  it either way; a win or loss either extends the current streak or
  starts a fresh one in the other direction.
- **Side-bet tables** (full-screen `stats` only): Power Poker, Star 21,
  and Buster each get their own table, sorted lowest payout to highest,
  showing every category's current payout, how many times it's been
  *dealt* (occurred at all, wagered on or not), and how many times it's
  actually *won* (occurred **and** you had a wager on it that round). That
  data exists to help gauge whether a payout (adjustable live — see
  **Side bets**) is priced the way you want it, not just to show off a
  big number. Star 21 always shows its full 9-category standard table
  and Buster its 6-category multi-deck table here, regardless of the
  shoe's live deck count, so this history reads the same no matter what
  the table's playing right now — only the *live* inline payout table on
  the Main UI tracks the deck-count-specific variant actually in effect.
- Both panels hold their pre-round numbers for the whole round and only
  catch up to the real values once it's fully settled — even though some
  outcomes (an immediate blackjack, a side bet win) are internally decided
  well before that. Without this, those numbers ticking up early would be
  its own tell, well before the deal animation or a settlement banner
  actually shows you the result.
- **Every number on both panels is computed from the history database** —
  nothing in the game keeps its own running totals. Lifetime means
  everything in the database (plus any lifetime numbers from before the
  database existed, imported once — see **Data storage**); session means the
  current session's hands. There is no command to zero the lifetime numbers,
  because that would mean erasing data: to start over with a clean slate,
  launch with a different database file (`python3 -m cs-blackjack --db
  ~/fresh.db`) and the old one stays exactly as it is.
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
- `newsession` ends the current session in the history log and starts a new
  one, so the session panel starts over; nothing is ever erased.

**Data keeping**

- **A SQLite history log** at `~/.cs-blackjack/blackjack.db` records every
  settled hand (cards, bets, outcome, P/L, side bets, insurance, and the
  Hi-Lo running/true count and shoe depth the round started at), every
  session, and every shoe — readable from any SQLite tool without launching
  the game. See **Data storage** for the schema.
- **Every shuffle is recorded exactly**: each shoe gets a `shoe_id`, its
  deck count, its penetration setting, and its full card order as run-together
  tokens (`K♣T♦3♠…`), so any past hand can be replayed against the cards
  that were actually coming. The order is held only in memory while the shoe
  is in play — the database gets each round's dealt cards as the round ends,
  and the never-dealt remainder, marked off after a `|`, when the shoe is
  retired (including when you quit, press Ctrl-C, or close the window) — so
  it can't be peeked at mid-shoe.
- **New tracked metrics**, kept per session and all-time: peak and lowest
  bankroll, max drawdown, longest win/loss streaks, biggest hand win and
  loss, and results by hand type (hard / soft / pairs / blackjacks /
  doubled / split), shown in a new block at the bottom of the `stats`
  screen. The Main UI's panels are unchanged.
- **`export`, `backup`, `backups`, `restore`** — CSV/JSON export, an
  `export mysql` script that recreates the whole database in MySQL/MariaDB,
  and validated snapshots that can be restored (with an automatic safety
  backup first). Pandas reads the database directly — see **Analyzing with
  pandas**.
- **Safer saves**: atomic writes, a schema version, and a corrupt save file is
  set aside instead of overwritten.
- A round you quit in the middle of (or Ctrl-C out of) is logged with its
  unsettled hands as `abandoned`, wager forfeited — matching what your saved
  bankroll actually does. Nothing in the game erases the history log.

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
lifetime/session numbers (plus the history-database block), `backups` for
saved backups, and `betspread` for the bet-spread reference tables — all
one keypress away, no need to memorize anything up front. A screen taller
than your terminal (`help` on a short window, say) is split into pages: any
key shows the next one.

### Requirements

- Python 3.9 or later
- The standard library `curses` module — this ships with Python on Linux
  and macOS; on Windows you'll need to `pip install windows-curses` first
- The standard library `sqlite3` module (ships with Python) for the history
  database
- A terminal that supports full-screen/maximize (the game sends a maximize
  escape sequence on launch) and is at least **193x49** — it will refuse to
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

The game maximizes your terminal window on launch. Your bankroll, wagers,
and table rules are saved to `~/.cs-blackjack_state.json` and reloaded
automatically the next time you launch. Every hand, session, and shoe is
logged to a SQLite database at `~/.cs-blackjack/blackjack.db`, and all of
the game's lifetime and session stats are computed from it — see **Data
storage** below.

To start with a clean slate without deleting anything, point the game at a
different database file (it's created if it doesn't exist):

```bash
python3 -m cs-blackjack --db ~/blackjack-2027.db
```

The original database is left exactly as it was, and you can go back to it
any time by launching without `--db`.

### Playing

- **Betting grid**: arrow keys (or a mouse click) move between the wager
  cells for each spot (main wager plus the three side bets); type digits to
  set an amount for the highlighted cell, then RETURN to confirm it (or to
  deal, once your wagers are set). The command line reads "`[RETURN] to
  Deal`" by default; after a new shoe/session message shows there instead,
  it reverts back to that default 2 seconds later.
- **Half-dollar wagers**: the main wager cell (not the side bets, which
  stay whole-dollar) also accepts a decimal point — type e.g. `25.5` and
  it commits rounded to the nearest 50 cents, same [table min, table max]
  check as any other wager. That's what lets a $25 bet actually collect
  its full 3:2 blackjack payout ($37.50) instead of losing the odd fifty
  cents to a whole-dollar-only bankroll.
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
| `rsa on/off [maxsplit N]` | Resplit aces (max resulting hands, up to 4; single deck: aces can't be resplit) |
| `rsa facedown on/off` | Deal split-ace cards face down (RSA off only) |
| `bj32` / `bj65` | Blackjack pays 3:2 or 6:5 (next shuffle) |
| `surr late/early/off` | Surrender mode |
| `h17` / `s17` | Dealer hits / stands on soft 17 (next shuffle) |
| `decks N` | Number of decks, 1–12 (next shuffle); a single deck allows 2 hands max and one split per hand |
| `deckpen 0.NN` | Deck penetration before reshuffle (next shuffle); a single deck is cut when fewer than 24 cards would be left, two decks max 0.80, 3+ decks when fewer than 16 + 12 per hand would be left |
| `deckpen rand` | Random penetration, 0.65–0.80, re-rolled on every new shoe (next shuffle) |
| `splitmax N` | Max hands from splitting non-ace pairs (single deck: 2 — one split per hand) |
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
| `bank default N` | Set the bankroll `bank reset` resets to |

**Table setup**

| Command | Effect |
|---|---|
| `hands 1-3` | Simultaneous hands to play (single deck: 1–2); changeable any time between rounds, and cuts a new shoe first if the current one is too short for that many hands |

**Side bets**

| Command | Effect |
|---|---|
| `powerpoker on/off [minbet N] [maxbet N]` | Requires 3+ decks in the live shoe |
| `star21 on/off [minbet N] [maxbet N]` | Requires 2+ decks (2 decks uses its own paytable) |
| `buster on/off [minbet N] [maxbet N]` | No deck restriction; single deck pays 500:1 on an 8+ card bust |
| `powerpoker <category> <payout>` | Adjust a Power Poker payout, e.g. `powerpoker royalflush 60` |
| `star21 <category> <payout>` | Adjust a Star 21 payout, e.g. `star21 suited777d 3000` or `star21 unsuited21 9` |
| `buster <category> <payout>` | Adjust a Dealer Buster payout, e.g. `buster 8+ 300` or `buster 7 50` |

A payout change applies to every table variant that shares that category
key — e.g. `star21 unsuited21 9` updates both the standard and the
double-deck Star 21 tables at once, so the odds stay consistent
regardless of how the deck count changes later. Payouts persist to disk
like everything else, so they carry over between sessions.

**Shoe / session**

| Command | Effect |
|---|---|
| `newshoe` | Reshuffle a fresh shoe (RETURN confirms) |
| `newsession` | Start a new session on a new shoe (session panel starts over, bankroll untouched; RETURN confirms) |

**Data & backups** (see **Data storage** below)

| Command | Effect |
|---|---|
| `export [hands\|sessions\|shoes\|stats\|all] [csv\|json]` | Write history (or the stats counters) to `~/.cs-blackjack/exports/` |
| `export mysql` | Write the whole database as a MySQL/MariaDB `.sql` script to `~/.cs-blackjack/exports/` |
| `backup` | Snapshot the history database + live state to `~/.cs-blackjack/backups/` |
| `backups` | List saved backups |
| `restore <name>` | Replace all current data with a backup (type `confirm`; a safety backup is taken first) |

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
| `stats.py` | `Stats` — the lifetime/session numbers the panels show (a read-only snapshot of what the database says) |
| `persist.py` | Load/save the live game state to `~/.cs-blackjack_state.json` (atomic writes, schema version, corrupt-file quarantine) |
| `history.py` | The SQLite history log (`sessions`/`shoes`/`hands` in `~/.cs-blackjack/blackjack.db`), every stat query, plus `export` (CSV/JSON/MySQL), `backup`, and `restore` |
| `commands.py` | Parses and applies every CLI command |
| `engine.py` | `GameSession`/`Round` — the full round state machine: dealing order, prelim prompts, player actions, settlement timing |
| `ui.py` | The `curses` TUI: layout, rendering, animation, input handling |
| `sound.py` | Fire-and-forget sound-effect playback (see `sounds/README.md`) |
| `__main__.py` | `python3 -m cs-blackjack` entry point (`--db FILE` picks a different history database) |
| `tests/` | The test suite and analysis tools — see **Testing** |

### Testing

The `tests/` folder holds checks that drive the real game code (not copies of
it) against known answers. It uses only the standard library, apart from one
optional package for the on-screen tests, and every script runs with its own
throwaway home folder, so **it never touches `~/.cs-blackjack` or your saved
game**.

```bash
python3 -m unittest discover -s tests -v      # everything (about 3–4 minutes)
python3 tests/check_failsafe.py               # or any one check on its own
CSBJ_FULL=1 python3 -m unittest discover -s tests   # also the mutation check and a longer audit
```

| Script | What it proves |
|---|---|
| `check_failsafe.py` | The mid-round reshuffle: every draw path (deal, hit, double, both split draws, the dealer), the cards on the table stay put, the count and card accounting stay exact, and the prevention limits and their messages |
| `check_split_cap.py` | One split per hand on a single deck, and only there |
| `check_history_reshuffle.py` | How the log records a round that ran the shoe dry (start shoe, the `reshuffled_mid_round` flag, the exact cards of both shoes), and upgrades of older database versions |
| `check_stats_and_import.py` | Every lifetime and session figure comes from the database; the one-time import of an older game's stats (including negative figures); `newsession`, `bank reset`, and `--db` |
| `check_data_safety.py` | `export`, `backup`, `restore` (and rejecting bad backups), crash recovery, corrupt or newer files, atomic saves, and playing on with no database |
| `check_locked_db.py` | Another program holding the database: nothing is dropped or mis-attributed, and it all lands, in order, once the lock lifts |
| `check_audit.py` | Thousands of random rounds with the log attached, checked against ground truth: bankroll conservation, the exact cards dealt, every stat against an independent implementation, the running counts |
| `check_ui.py` | The real screen in a pseudo-terminal: the deck rules and their messages, a mid-hand reshuffle on screen, what's saved on quit / `SIGTERM` / `SIGHUP`. Needs `pip install pyte`; skipped without it |
| `tools/mutation_check.py` | Injects known bugs and confirms the checks above fail for each — a check that can't fail proves nothing |
| `tools/consumption.py`, `tools/montecarlo.py`, `tools/adversary.py` | The measurements behind the minimum-cards floors: cards used per round, crash / failsafe rates per configuration over millions of rounds, and a search over every legal line of play (run them directly; `--help`-style usage is in each file's docstring) |

Runs are repeatable: the game's shuffles use a fixed seed unless you set
`CSBJ_SEED=n`.

### Data storage

The game keeps two kinds of data:

| Where | What |
|---|---|
| `~/.cs-blackjack_state.json` | The *live* game state: bankroll, table rules, side-bet payouts, and wagers. Written after every round and on quit. |
| `~/.cs-blackjack/blackjack.db` | The *history log*: a SQLite database with every hand, session, and shoe ever played, and the source of every stat the game displays. Append-only — nothing in the game erases it. |
| `~/.cs-blackjack/exports/` | Files written by `export`. |
| `~/.cs-blackjack/backups/` | Snapshots made by `backup` (and the automatic safety backup before a `restore`). |

Delete `~/.cs-blackjack_state.json` to reset the live state back to
defaults. To start over with fresh stats, launch with `--db <file>` (see
**Launch**) rather than deleting anything; deleting `~/.cs-blackjack/` erases
the history for good.

**Stats come from the database.** The lifetime and session panels are
computed from the `hands`, `sessions` and `shoes` tables after every round.
Hand tallies count settled hands; the money figures also include the
forfeited wager of a hand still unsettled when the game was quit. Before the
database existed, the game counted lifetime numbers itself and kept them in
the state file: the first launch that finds them imports them into the
database's `imported_stats` table (only the part the database doesn't
already hold), and from then on the state file no longer carries any stats.
Figures come across with their sign (a losing side bet stays a loss). Until
that import succeeds they stay in the state file untouched, so they can never
be lost. (They go into the first database the game opens after the
upgrade — if that's a fresh `--db` file rather than your usual one, that's
where they land.)

**Safer saves.** The state file is written to a temporary file and renamed
into place, so a crash or full disk mid-save can't leave a truncated file,
and it carries a `schema_version`. If the file ever can't be read, it's
renamed aside to `~/.cs-blackjack_state.json.corrupt-<timestamp>` (and the
game says so on launch) rather than being silently overwritten by the next
save. The history database is versioned with SQLite's `user_version` and
upgrades itself on launch. If the database can't be opened at all, the game
tells you at launch and plays on without logging — history problems never
stop a hand.

**If another program has the database locked** (a SQLite browser sitting on an
open edit, say), the game keeps playing and holds what it couldn't write — every
round, and every shoe change (a shoe closing, the next one being cut, including
a mid-round reshuffle) — in memory, in order, and the stats screen notes how
many rounds are waiting. The next successful write, or the game quitting, saves
them all, each attached to the right shoe and session. Only if the lock is still
there when the game closes do those waiting rounds go unsaved; whatever was
already written is untouched, and a `newsession` or `restore` requested while
the database is busy is declined or carried on in the current session rather
than half-done.

#### The history database

Open it with any SQLite tool, **without launching the game** — the `sqlite3`
command line, [DB Browser for SQLite](https://sqlitebrowser.org/), DBeaver,
DataGrip, TablePlus, pandas (`pd.read_sql`), and so on:

```bash
sqlite3 -header -column ~/.cs-blackjack/blackjack.db \
  "SELECT session_id, started_at, hands_played, net_pl, max_drawdown FROM sessions ORDER BY session_id DESC LIMIT 5"
```

> It's a **SQLite** database, not a MySQL server, so a MySQL client such as
> MySQL Workbench can't open the file directly. To use it from MySQL, run
> `export mysql` in the game (see **Using it from MySQL** below) — it writes
> a script that recreates every table, row and view.

Conventions: timestamps are UTC ISO-8601 text (`2026-09-29T15:04:05Z`; use
`datetime(col, 'localtime')` in SQLite to convert); booleans are `0`/`1`;
money is dollars. A **card** is a two-character token — rank (`T` = ten)
then suit glyph, e.g. `T♦`, `K♣`, `3♠` — and a **card sequence** is those
tokens run together, e.g. `K♣T♦3♠`, so it splits cleanly every two
characters.

**`sessions`** — one row per session. A session runs from launch (or from
`newsession`) until the next of those or quit. If the game is killed rather
than quit, the leftover session is closed as `abandoned` the next time it
launches. The row is updated after every round, so it's always current.

| Columns | Meaning |
|---|---|
| `session_id`, `started_at`, `ended_at`, `end_reason` | `end_reason`: `quit`, `newsession`, `restore`, or `abandoned` (databases from older versions of the game may also contain `hardreset`); `ended_at` is `NULL` while running |
| `starting_bankroll`, `ending_bankroll`, `peak_bankroll`, `lowest_bankroll` | Bankroll as observed at round boundaries |
| `max_drawdown` | Largest peak-to-trough fall in cumulative session P/L (a `bank add` can't distort it) |
| `rounds_played`, `hands_played`, `hands_won`, `hands_lost`, `hands_pushed`, `hands_surrendered` | Tallies (a round cut off by quitting isn't counted as played) |
| `doubles`, `splits`, `aces_split`, `tens_split`, `player_blackjacks`, `dealer_blackjacks`, `dealer_pulled_21s`, `dealer_busts`, `shoes_played` | Same definitions as the in-game Session Stats |
| `main_wagered`, `main_pl`, `sidebet_pl`, `net_pl` | Summed from the session's own `hands` rows (`sidebet_pl` includes insurance) |
| `longest_win_streak`, `longest_loss_streak` | Consecutive hands; pushes and surrenders don't break a streak |

**`shoes`** — one row per unique shuffle.

| Columns | Meaning |
|---|---|
| `shoe_id`, `session_id` | The shoe's ID, and the session it was cut in |
| `cut_at`, `retired_at`, `cut_reason` | `cut_reason`: `start`, `penetration` (cut card or minimum-cards rule reached), `newshoe`, `newsession`, `mid_round` (the shoe ran out during a round and the discards were reshuffled), `restore` (older databases may also contain `hardreset`) |
| `num_decks`, `penetration`, `total_cards`, `cards_dealt` | Deck count; the depth the shoe is really cut at (with `deckpen rand`, the value that was rolled; a two-deck shoe is at most 0.80; a single deck is cut by card count, so at most 28/52 ≈ 0.54); cards actually dealt from it |
| `blackjack_payout`, `hit_soft_17`, `rules_json` | Table rules as of the cut, including every side-bet payout |
| `card_order` | **The exact order of the whole shuffle, first card dealt first**, with the never-dealt cards marked off after a `\|` — e.g. `K♣T♦3♠\|7♥A♠…` reads *dealt* `\|` *never dealt* (624 characters plus the `\|` for six decks) |

**How `card_order` gets written.** The shuffle exists only in the game's
memory while the shoe is in play, so the file never holds cards that haven't
been dealt yet — no peeking mid-shoe. After each round, the cards dealt so
far are written (no `|` yet, which means "still in play"). When the shoe is
retired — a reshuffle, `newshoe`, `newsession`, `quit`, Ctrl-C, or closing the
terminal window (SIGHUP/SIGTERM are handled the same way) — the rest of the
shuffle is appended after a `|`, so every retired shoe shows exactly which
cards were dealt and which never were. Split it in SQL or pandas with
`substr`/`split('|')`. The one thing that can still lose a tail is the
process being killed outright (`kill -9`, power loss): that shoe keeps its
dealt cards but has no `|`.

**A shoe that runs out mid-round.** The exhausted shoe is retired on the spot
with all of its cards dealt and nothing after the `|` (`…|`). The new shoe's row
(`cut_reason` `mid_round`) starts with the cards that were on the table, in the
order they were drawn, as its dealt part — they count as dealt from the new
shuffle — followed by everything drawn after the reshuffle.

**`hands`** — one row per player hand (a spot that splits logs one row per
resulting hand; `round_id` groups the hands dealt together, and
`bankroll_before`/`bankroll_after`, the count columns, and the dealer's
columns repeat on every hand of a round).

| Columns | Meaning |
|---|---|
| `hand_id`, `round_id`, `session_id`, `shoe_id`, `played_at` | Keys and time; `hand_id` order is settlement order. `shoe_id` is the shoe the round **started** on |
| `reshuffled_mid_round` | `1` on every hand of a round during which the shoe ran out and the discards were reshuffled, else `0`. Such a round straddles two shoes: `shoe_id` and the `running_count_before` / `true_count_before` / `cards_dealt_before` columns describe the shoe it started on, while the cards drawn after the reshuffle came from the next shoe row (`cut_reason` `mid_round`). For strict count-versus-bet analysis, leave these rounds out (`WHERE reshuffled_mid_round = 0`) |
| `spot_number`, `hand_number` | The on-screen "Hand #" (1–3), and the hand's position within its spot after splits |
| `initial_bet`, `final_bet` | Wager before and after any double |
| `hand_type`, `initial_total` | From the first two cards: `blackjack`, `pair` (anything splittable, so two different ten-value cards count), `soft`, or `hard`; and their total |
| `player_cards`, `player_total`, `player_soft`, `player_bust`, `player_blackjack` | The final hand |
| `is_split`, `is_split_aces`, `doubled`, `surrendered`, `even_money` | How it was played |
| `dealer_up`, `dealer_cards`, `dealer_total`, `dealer_bust`, `dealer_blackjack` | The dealer's hand |
| `outcome` | `win`, `loss`, `push`, `surrender`, or `abandoned` (a hand still unsettled when the game was quit; its wager is forfeited, as it is in your saved bankroll) |
| `payout`, `main_pl` | Total returned for the hand, and `payout − final_bet` |
| `insurance_*`, `power_poker_*`, `star21_*`, `dealer_buster_*` | `_wager`, `_pl`, and (for the three side bets) `_category` — which payout category the cards made, recorded whether or not you wagered on it, which is what you want for judging a payout |
| `sidebet_pl`, `total_pl` | All side bets + insurance; and `main_pl + sidebet_pl` |
| `running_count_before`, `true_count_before`, `cards_dealt_before` | The Hi-Lo count and shoe depth the round started at — i.e. what your bet was sized against |
| `bankroll_before`, `bankroll_after` | Bankroll around the whole round |

Side bets and insurance belong to a spot, not to one of its split hands, so
they're recorded on the spot's **first** hand (`hand_number = 1`) and are
`0`/`NULL` on its other hands — summing any column across hands never
double-counts. For every settled round, `bankroll_after − bankroll_before`
equals the sum of `total_pl` over that round's hands.

Two read-only views summarize the results: **`hand_type_summary`** (results
by `hand_type`) and **`bet_size_summary`** (results and average true count
by `initial_bet`). For example, results by bet size:

```sql
SELECT * FROM bet_size_summary ORDER BY initial_bet;
```

or your win rate by true count (`true_count_before` is already stored in exact
half-steps, so it groups cleanly with no casting — and this exact query gives
the same answer in SQLite and MySQL):

```sql
SELECT true_count_before AS tc, COUNT(*) AS hands,
       ROUND(SUM(main_pl) / SUM(final_bet) * 100, 2) AS ev_pct
FROM hands WHERE outcome <> 'abandoned' AND reshuffled_mid_round = 0
GROUP BY true_count_before ORDER BY true_count_before;
```

#### Export, backup, and restore

- **`export [hands|sessions|shoes|stats|all] [csv|json]`** — writes to
  `~/.cs-blackjack/exports/<table>-<timestamp>.<csv|json>` (default: all
  three history tables as CSV). `export stats` writes the lifetime/session
  counters shown on the `stats` screen.
- **`export mysql`** — writes `~/.cs-blackjack/exports/mysql-<timestamp>.sql`,
  the whole database as a MySQL/MariaDB script (see **Using it from MySQL**).
- **`backup`** — saves a consistent snapshot of the history database plus the
  live state to `~/.cs-blackjack/backups/<timestamp>/`. Not available in the
  middle of a round.
- **`backups`** — lists them.
- **`restore <name>`** — replaces *all* current data (history, bankroll,
  rules, stats) with a backup, after you type `confirm`. A prefix of the
  name is enough. The backup is validated first, and a
  `<timestamp>-pre-restore` safety backup of what you're replacing is taken
  before anything is touched — so a restore can itself be undone with
  another `restore`.

#### Analyzing with pandas

pandas reads the database directly — no export step and no extra packages
beyond pandas itself. Reading while the game is running is fine (open it
read-only with `sqlite3.connect("file:<path>?mode=ro", uri=True)` if you
want to be sure you can't change anything). If another program does hold the
database when a round ends — a long query, or a GUI tool left with an
uncommitted edit — the game waits up to two seconds, then keeps that round
queued (the message line and the `stats` screen say so) and writes it, in
order, along with the next round once the database is free; when you quit it
tries again before giving up. Nothing is dropped, but closing analysis tools
or working from an `export`/`backup` keeps things simple:

```python
from pathlib import Path
import sqlite3
import pandas as pd

con = sqlite3.connect(Path.home() / ".cs-blackjack" / "blackjack.db")

hands    = pd.read_sql_query("SELECT * FROM hands",    con, parse_dates=["played_at"])
sessions = pd.read_sql_query("SELECT * FROM sessions", con, parse_dates=["started_at", "ended_at"])
shoes    = pd.read_sql_query("SELECT * FROM shoes",    con, parse_dates=["cut_at", "retired_at"])

# Timestamps come back as UTC; convert to your own time zone if you like:
hands["played_at"] = hands["played_at"].dt.tz_convert("America/Los_Angeles")
```

Flags (`doubled`, `is_split`, …) load as `0`/`1` integers — add `.astype(bool)`
if you'd rather have booleans. A few things worth trying:

```python
import numpy as np, re

# (rounds where the shoe ran out mid-hand straddle two shoes, so their count
# columns don't apply cleanly -- leave them out of count-versus-bet work)
settled = hands[(hands["outcome"] != "abandoned") & (hands["reshuffled_mid_round"] == 0)].copy()

# Your edge by true count (buckets of one count):
settled["tc"] = np.floor(settled["true_count_before"]).astype(int)
by_tc = settled.groupby("tc").agg(hands=("hand_id", "count"),
                                  wagered=("final_bet", "sum"), pl=("main_pl", "sum"))
by_tc["ev_pct"] = by_tc["pl"] / by_tc["wagered"] * 100

# Results by bet size, with the average count you bet it at:
by_bet = settled.groupby("initial_bet").agg(hands=("hand_id", "count"),
                                            pl=("main_pl", "sum"),
                                            avg_tc=("true_count_before", "mean"))

# Bankroll after every round:
curve = hands.groupby("round_id").agg(played_at=("played_at", "first"),
                                      bankroll=("bankroll_after", "first"))

# Card strings are two characters per card, so re.findall splits them:
hands["player_cards"].map(lambda c: re.findall(r".{2}", c))

# Each shoe's dealt cards vs the cards that were never dealt (a shoe still in
# play has no "|" yet, so its undealt part comes back empty):
parts = shoes["card_order"].str.split("|", n=1, expand=True)
shoes["dealt"]   = parts[0].map(lambda o: re.findall(r".{2}", o))
shoes["undealt"] = parts[1].map(lambda o: re.findall(r".{2}", o) if isinstance(o, str) else None)

# Join hands to the shoe they were dealt from:
hands.merge(shoes[["shoe_id", "num_decks", "penetration"]], on="shoe_id")

# The summary views load like any table:
pd.read_sql_query("SELECT * FROM hand_type_summary", con)
```

#### Using it from MySQL

SQLite files can't be opened by a MySQL server or MySQL Workbench directly, so
`export mysql` writes a script that recreates the whole database — every table,
every row, the two views, and the foreign keys and indexes — in MySQL or
MariaDB. Load it into an **empty schema you've chosen** (the script drops and
recreates these tables, so don't point it at a schema holding anything else
under those names):

```bash
mysql -u root -p -e "CREATE DATABASE blackjack CHARACTER SET utf8mb4"
mysql -u root -p blackjack < ~/.cs-blackjack/exports/mysql-20260929-131943.sql
```

or, in MySQL Workbench: pick the schema, then **Server → Data Import → Import
from Self-Contained File**. The script is safe to re-run; it rebuilds the tables
from the file each time, so re-export and re-import whenever you want the
MySQL copy brought up to date (it's a snapshot, not a live sync).

Things to know on the MySQL side:

- Timestamps become `DATETIME` columns holding UTC; use
  `CONVERT_TZ(played_at, '+00:00', 'America/Los_Angeles')` (or `'-07:00'`) to
  see local time. The card glyphs (`♠♥♦♣`) need the `utf8mb4` character set,
  which the script sets for the session and for every table.
- `CAST(x AS SIGNED)` **rounds** in MySQL where SQLite's `CAST(x AS INTEGER)`
  **truncates**, so don't bucket the count by casting — group by
  `true_count_before` itself (as above), or use `FLOOR()`.
- The script's table definitions are generated from the live SQLite schema, so
  they track any columns added in later versions of the game.
