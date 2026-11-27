"""Run a test suite as if the clock stood somewhere else (found 2026-11-24: one CI run was red for five minutes after midnight in New York because a test read the real clock, and nothing could have shown it earlier).

    cd atlas/backend && python3 ../devtools/clockrun.py --at 2026-11-25T05:07:00+00:00 -- -q -x
    python3 atlas/devtools/clockrun.py --at 2026-11-30T23:59:30+00:00 --no-tick --cwd atlas/backend -- -q tests/test_signal_api.py

Standard library only; nothing is installed and nothing in the repository imports this file. It starts pytest with this file loaded as a plugin (`-p clockrun`, before any test or application module is imported), and the plugin replaces `datetime.datetime`, `datetime.date`, `time.time` and `time.time_ns` with versions that start at the chosen instant. The clock then keeps ticking in real time (so a timeout, a sleep or a cache lifetime behaves as usual) unless `--no-tick` freezes it. `time.monotonic` and `time.perf_counter` stay real, so asyncio and pytest's own timings are not touched. `--at` must carry an offset (`+00:00` or `Z`): a time without one means nothing here.

What it does NOT cover: a module that imported `datetime` before the plugin did (none can, the plugin is loaded first), code that asks the operating system for the time through a C library (pandas' `Timestamp.now()` and NumPy's `datetime64('now')` do: the README says what that costs), and the time zone database (a daylight-saving date is chosen by its instant, not by changing zones). A run under a fake clock is a search, not a proof: a failure is read first, because a test that compares with a date written into it fails on any other day and says nothing about the code.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime as _real_datetime, timezone as _timezone
from pathlib import Path

ENV_AT, ENV_TICK = "ATLAS_FAKE_NOW", "ATLAS_FAKE_TICK"
PRELOAD = ("numpy", "pandas", "pydantic", "pydantic.v1")                # libraries that build classes from datetime.date or datetime.datetime when they are imported: with the classes already replaced pandas crashes the interpreter and pydantic v1 stops with a metaclass conflict (both found 2026-11-25), so they are imported first and keep the real classes


def parse_at(text: str) -> _real_datetime:
    """The instant as an aware datetime; a text without an offset is refused."""
    try:
        at = _real_datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"'{text}' is not a date and time like 2026-11-25T05:07:00+00:00")
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError(f"'{text}' has no offset: write 2026-11-25T05:07:00+00:00 (or Z) so that the instant is not a guess")
    return at


def install(start: _real_datetime, tick: bool = True) -> None:
    """Replace the clock for the rest of this process. Call it before the code under test is imported."""
    import datetime as dt
    import importlib
    import time as tm

    for name in PRELOAD:
        try:
            importlib.import_module(name)
        except ImportError:
            pass
    real_dt, real_date, real_time = dt.datetime, dt.date, tm.time
    t0, base = real_time(), start.timestamp()

    def now_ts() -> float:
        return base + ((real_time() - t0) if tick else 0.0)

    class DatetimeMeta(type):
        def __instancecheck__(cls, obj):                               # a datetime made by the real class (by pandas, by dateutil's own arithmetic) is still a datetime: dateutil asks isinstance(x, datetime.date) and refused a real datetime once the class was replaced
            return isinstance(obj, real_dt)

    class DateMeta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, real_date)

    class FakeDatetime(real_dt, metaclass=DatetimeMeta):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(now_ts(), tz)

        @classmethod
        def utcnow(cls):
            return cls.fromtimestamp(now_ts(), _timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.fromtimestamp(now_ts())

    class FakeDate(real_date, metaclass=DateMeta):
        @classmethod
        def today(cls):
            return cls.fromtimestamp(now_ts())

    dt.datetime, dt.date = FakeDatetime, FakeDate
    tm.time = now_ts
    tm.time_ns = lambda: int(now_ts() * 1_000_000_000)


def pytest_report_header(config):
    at = os.environ.get(ENV_AT)
    return f"fake clock: starts at {at} ({'ticking' if os.environ.get(ENV_TICK, '1') != '0' else 'frozen'})" if at else None


if os.environ.get(ENV_AT):                                             # loaded as a plugin by `-p clockrun`: the clock is replaced at once
    install(parse_at(os.environ[ENV_AT]), tick=os.environ.get(ENV_TICK, "1") != "0")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run pytest under a fake clock (standard library only).")
    p.add_argument("--at", required=True, help="the instant the clock starts at, with an offset: 2026-11-25T05:07:00+00:00")
    p.add_argument("--no-tick", action="store_true", help="freeze the clock at that instant instead of letting it run on")
    p.add_argument("--cwd", help="the folder to run pytest in (default: the current one)")
    p.add_argument("pytest_args", nargs="*", help="everything after -- goes to pytest")
    a = p.parse_args(argv)
    try:
        at = parse_at(a.at)
    except ValueError as e:
        print(f"clockrun: {e}", file=sys.stderr)
        return 2
    env = {**os.environ, ENV_AT: at.isoformat(), ENV_TICK: "0" if a.no_tick else "1",
           "PYTHONPATH": os.pathsep.join(x for x in (str(Path(__file__).resolve().parent), os.environ.get("PYTHONPATH", "")) if x)}
    cmd = [sys.executable, "-m", "pytest", "-p", "clockrun", *(a.pytest_args or ["-q"])]
    return subprocess.run(cmd, env=env, cwd=a.cwd or None).returncode


if __name__ == "__main__":
    sys.exit(main())
