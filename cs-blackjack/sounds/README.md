# Sound effects

Drop the following audio files into this folder and they'll play
automatically the next time the game runs -- nothing else needs to
change. See `cs-blackjack/sound.py` for the playback logic (it silently
does nothing if a file is missing or no supported command-line player is
installed, so the game runs fine with this folder empty).

| File | Plays when |
|---|---|
| `card-deal.mp3` | Each time the dealer deals a card, or a face-down card (the dealer's hole card, a face-down double-down/RSA card) turns face up. |
| `sidebet-normal-win.wav` | A side-bet win paying 49:1 or lower. |
| `sidebet-big-win.wav` | A side-bet win paying 50:1 or higher. |
| `wager-win.wav` | A round that ends with a positive net return across all wagers combined. |
| `bust-sound.wav` | A player hand busting (on a hit, or a face-up double-down), or the dealer's hand busting. |

Playback runs via whichever of `afplay`/`paplay`/`aplay`/`ffplay`/`mpg123`
is found on the system `PATH`.
