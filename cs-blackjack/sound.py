"""Fire-and-forget sound effects.

Drop the matching audio files into cs-blackjack/sounds/ (next to this
module -- create the folder if it doesn't exist yet) and they play
automatically the next time the game runs; nothing needs to change in
code. Expected filenames:

    card-deal.mp3           a card being dealt to any hand (initial deal,
                            hit, double, split, dealer hit) or turned face
                            up (dealer hole card, a face-down double/RSA
                            card) -- including the dealer's own busting
                            card, just ~10% louder instead of bust-sound
    sidebet-normal-win.wav  a side-bet win paying 49:1 or lower
    sidebet-big-win.wav     a side-bet win paying 50:1 or higher
    wager-win.wav           a round with a positive net return overall
    bust-sound.wav          a player hand busting (hit or a face-up
                            double), a doubled hand losing even without
                            busting, or a confirmed dealer blackjack
                            (whatever any one spot does about it -- push,
                            loss, or taking even money). NOT the dealer's
                            own bust -- see card-deal.mp3 above.

A plain main-wager loss, push, or surrender (no double, no bust) stays
silent -- only a win, a bust, a losing double, or a dealer blackjack gets
a sound beyond the ordinary card-deal ones.

Playback runs in a background thread via whatever command-line player is
already on the system (afplay/paplay/aplay/ffplay/mpg123) -- there's no
bundled audio backend, so nothing plays until both a file and a player are
present. Every failure mode (file missing, no player installed, playback
error) is silently swallowed: sound is a layer of polish, never something
that should crash or stall a round.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading

SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "sounds")

CARD_DEAL = "card-deal.mp3"
SIDEBET_NORMAL_WIN = "sidebet-normal-win.wav"
SIDEBET_BIG_WIN = "sidebet-big-win.wav"
WAGER_WIN = "wager-win.wav"
BUST = "bust-sound.wav"

# Big enough odds to feel like a jackpot rather than a routine side-bet
# win -- 50:1 and up gets the bigger sting, per spec.
BIG_WIN_ODDS_THRESHOLD = 50.0

# The dealer's own busting card plays card-deal.mp3 a bit louder instead of
# the bust-sound -- the win sound (for the player hand(s) it just decided)
# already covers the "something happened" cue.
DEALER_BUST_CARD_VOLUME = 1.1

# Tried in order; the first one found on PATH is used for every play() call
# this run (checked once, not per call, so a missing player doesn't retry
# shutil.which() every time a card is dealt). Each entry also carries how to
# spell a volume-scale flag for that player, for play()'s `volume` argument
# -- None means the player has no simple per-invocation volume control, so a
# non-default volume is silently ignored for it (falls back to 100%).
_PLAYERS = (
    ("afplay", ["afplay"], lambda v: ["-v", str(v)]),
    ("paplay", ["paplay"], lambda v: [f"--volume={round(65536 * v)}"]),
    ("aplay", ["aplay", "-q"], None),
    ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], lambda v: ["-af", f"volume={v}"]),
    ("mpg123", ["mpg123", "-q"], lambda v: ["-f", str(round(32768 * v))]),
)

_player: tuple = None  # (cmd, volume_flag_fn) once resolved
_player_checked = False
_check_lock = threading.Lock()


def _find_player():
    global _player, _player_checked
    if not _player_checked:
        with _check_lock:
            if not _player_checked:
                for _name, cmd, volume_flag_fn in _PLAYERS:
                    if shutil.which(cmd[0]):
                        _player = (cmd, volume_flag_fn)
                        break
                _player_checked = True
    return _player


def play(filename: str, volume: float = 1.0) -> None:
    """volume=1.0 is the file's/system's normal level; e.g. 1.1 plays it
    ~10% louder. Ignored (plays at normal volume) on a player that has no
    simple way to scale a single invocation's volume."""
    path = os.path.join(SOUNDS_DIR, filename)
    if not os.path.isfile(path):
        return
    found = _find_player()
    if not found:
        return
    cmd, volume_flag_fn = found
    extra = volume_flag_fn(volume) if (volume_flag_fn and volume != 1.0) else []

    def _run():
        try:
            subprocess.run(
                [*cmd, *extra, path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,  # a misbehaving player (e.g. no audio device at all)
                            # should never tie up a background thread for long
            )
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def play_sidebet_win(payout_multiplier: float) -> None:
    play(SIDEBET_BIG_WIN if payout_multiplier >= BIG_WIN_ODDS_THRESHOLD else SIDEBET_NORMAL_WIN)
