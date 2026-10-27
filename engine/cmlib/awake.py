"""awake.py - keep Windows from sleeping while there is publishing work to do.

Uses SetThreadExecutionState (the same call video players use); it changes no system
setting and stops having any effect the moment this process exits.
Note: closing the laptop lid follows the Windows lid setting and still sleeps the laptop.
"""

import datetime as dt
import sys
import time

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def hold():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def release():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def in_window(frm, to, at=None):
    at = (at or dt.datetime.now()).time()
    a = dt.time.fromisoformat(frm)
    b = dt.time.fromisoformat(to)
    return a <= at < b if a <= b else (at >= a or at < b)


def loop(should_stay_awake, check_every=60, out=print):
    """Hold the system awake while should_stay_awake() is True; exit when it turns False."""
    held = False
    try:
        while True:
            want = should_stay_awake()
            if want and not held:
                hold()
                held = True
                out(f"{dt.datetime.now():%H:%M} awake: holding")
            elif not want:
                if held:
                    out(f"{dt.datetime.now():%H:%M} awake: releasing")
                return
            time.sleep(check_every)
    finally:
        release()
