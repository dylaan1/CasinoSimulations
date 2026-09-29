"""Drive the real curses game inside a pseudo-terminal and read its screen back with pyte (a terminal emulator
library). Nothing here imports the game: it runs as a separate process with its own throwaway HOME."""
import fcntl
import os
import pty
import re
import select
import signal
import struct
import sys
import termios
import time
from pathlib import Path

import pyte

REPO = Path(__file__).resolve().parent.parent
FORCED_LAUNCHER = Path(__file__).resolve().parent / "forced_launcher.py"
RIGHT, LEFT = "\x1bOC", "\x1bOD"


class Game:
    def __init__(self, home, rows=60, cols=220, args=(), cmd=None):
        self.rows, self.cols = rows, cols
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.raw = b""
        pid, fd = pty.fork()
        if pid == 0:  # child
            os.chdir(REPO)
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            env = {"HOME": home, "TERM": "xterm-256color", "PATH": "/nonexistent",   # no audio player on PATH: stays silent
                   "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}
            argv = cmd or [sys.executable, "-m", "cs-blackjack", *args]
            os.execve(argv[0], argv, env)
        self.pid, self.fd = pid, fd
        self.exit_status = None

    def pump(self, seconds=0.6):
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if r:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    return
                if not data:
                    return
                self.raw += data
                self.stream.feed(data)

    def send(self, data, wait=0.5):
        os.write(self.fd, data if isinstance(data, bytes) else data.encode())
        self.pump(wait)

    def text(self):
        return "\n".join(line.rstrip() for line in self.screen.display).rstrip()

    def alive(self):
        if self.exit_status is not None:
            return False
        pid, status = os.waitpid(self.pid, os.WNOHANG)
        if pid:
            self.exit_status = status
            return False
        return True

    def wait_exit(self, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.2)
            if not self.alive():
                return True
        return False

    def kill(self, sig=signal.SIGKILL):
        if self.alive():
            os.kill(self.pid, sig)

    # ---- things every test needs ----

    def line_with(self, needle):
        """The first screen line containing `needle`, with the box-drawing characters stripped."""
        for line in self.text().splitlines():
            if needle in line:
                return re.sub(r"[│┌┐└┘─]", "", line).strip()
        return None

    def command(self, text, wait=0.9):
        """Open the command line (Esc, then '/'), type `text`, press Return."""
        self.send("\x1b", 1.3)
        self.send("/", 0.3)
        self.send(text, 0.3)
        self.send("\r", wait)

    def to_idle(self, presses=16):
        """Press Return until a round is over and the game is back at the betting screen."""
        for _ in range(presses):
            if "[RETURN] to Deal" in self.text():
                return True
            self.send("\r", 1.7)
        return "[RETURN] to Deal" in self.text()

    def wager_row(self):
        """The three wager cells of the betting grid as strings, or None."""
        for line in self.text().splitlines():
            clean = re.sub(r"[│┌┐└┘─]", " ", line)
            m = re.search(r"(?<![\d.$,])(\d[\d.]*)\s+♦\s+(\d[\d.]*)\s+♦\s+(\d[\d.]*)(?![\d.])", clean)
            if m and "$" not in clean:
                return tuple(m.groups())
        return None
