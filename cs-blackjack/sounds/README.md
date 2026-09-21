# Sound effects

Drop the following audio files into this folder and they'll play
automatically the next time the game runs -- nothing else needs to
change. See `cs-blackjack/sound.py` for the playback logic (it silently
does nothing if a file is missing or no supported command-line player is
installed, so the game runs fine with this folder empty).

| File | Plays when |
|---|---|
| `card-deal.mp3` | Each time a card is dealt to any hand -- the initial deal, a player hit/double/split, a dealer hit -- or a face-down card (the dealer's hole card, a face-down double-down/RSA card) turns face up. The dealer's own busting card plays this file too, just ~10% louder, instead of `bust-sound.wav`. |
| `sidebet-normal-win.wav` | A side-bet win paying 49:1 or lower. |
| `sidebet-big-win.wav` | A side-bet win paying 50:1 or higher. |
| `wager-win.wav` | A round that ends with a positive net return across all wagers combined. |
| `bust-sound.wav` | A player hand busting (a hit, or a face-up double-down), a doubled hand that loses even without busting, or a confirmed dealer blackjack (once per round, regardless of what any individual spot does about it -- push, loss, or taking even money). Not the dealer's own bust -- see `card-deal.mp3` above. |

A plain main-wager loss, push, or surrender (no double, no bust) stays
silent -- only a win, a bust, a losing double, or a dealer blackjack gets
a sound beyond the ordinary card-deal ones.

Playback runs via whichever of `afplay`/`paplay`/`aplay`/`ffplay`/`mpg123`
is found on the system `PATH`.
