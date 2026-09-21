"""Fire-and-forget sound effects.

Drop the matching audio files into cs-blackjack/sounds/ (next to this
module -- create the folder if it doesn't exist yet) and they play
automatically the next time the game runs; nothing needs to change in
code. Expected filenames:

    card-deal.mp3           a card being dealt or turned face up
    sidebet-normal-win.wav  a side-bet win paying 49:1 or lower
    sidebet-big-win.wav     a side-bet win paying 50:1 or higher
    wager-win.wav           a round with a positive net return overall
    bust-sound.wav          a player hand or the dealer's hand busting

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

# Tried in order; the first one found on PATH is used for every play() call
# this run (checked once, not per call, so a missing player doesn't retry
# shutil.which() every time a card is dealt).
_PLAYERS = (
    ("afplay", ["afplay"]),
    ("paplay", ["paplay"]),
    ("aplay", ["aplay", "-q"]),
    ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ("mpg123", ["mpg123", "-q"]),
)

_player_cmd: list = None
_player_checked = False
_check_lock = threading.Lock()


def _find_player():
    global _player_cmd, _player_checked
    if not _player_checked:
        with _check_lock:
            if not _player_checked:
                for _name, cmd in _PLAYERS:
                    if shutil.which(cmd[0]):
                        _player_cmd = cmd
                        break
                _player_checked = True
    return _player_cmd


def play(filename: str) -> None:
    path = os.path.join(SOUNDS_DIR, filename)
    if not os.path.isfile(path):
        return
    cmd = _find_player()
    if not cmd:
        return

    def _run():
        try:
            subprocess.run(
                [*cmd, path],
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
