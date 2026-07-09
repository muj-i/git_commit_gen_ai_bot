import itertools
import sys
import threading
import time
from contextlib import contextmanager

FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_LINE = "\r\033[2K"


@contextmanager
def spin(text: str):
    """Render a spinner on stderr while the body runs. No-op when stderr
    isn't a terminal (hooks, daemon, pipes, logs)."""
    if not sys.stderr.isatty():
        yield
        return

    stop = threading.Event()
    start = time.monotonic()

    def _spin():
        for frame in itertools.cycle(FRAMES):
            if stop.is_set():
                return
            elapsed = time.monotonic() - start
            sys.stderr.write(f"{CLEAR_LINE}{frame} {text} {elapsed:.0f}s")
            sys.stderr.flush()
            time.sleep(0.08)

    thread = threading.Thread(target=_spin, daemon=True)
    sys.stderr.write(HIDE_CURSOR)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        sys.stderr.write(CLEAR_LINE + SHOW_CURSOR)
        sys.stderr.flush()
