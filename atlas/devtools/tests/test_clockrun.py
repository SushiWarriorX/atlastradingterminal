"""The fake-clock runner (`devtools/clockrun.py`): the clock starts at the instant it is told and keeps running (or stands still), every way of asking for the time agrees, the monotonic clocks stay real, a library that derives a class from `datetime` is not stopped, a time without an offset is refused, and the command line runs pytest under it. Everything that changes the clock runs in a child process, so that none of it leaks into this one."""
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

import clockrun as C

DEV = Path(__file__).resolve().parents[1]
AT = "2031-02-03T04:05:06+00:00"                                                           # not a day this suite runs on: a real clock cannot pass by accident


def child(code, at=AT, tick="1"):
    env = {k: v for k, v in os.environ.items() if k not in (C.ENV_AT, C.ENV_TICK)}
    env.update({"PYTHONPATH": str(DEV), "TZ": "UTC", **({C.ENV_AT: at} if at else {}), **({C.ENV_TICK: tick} if at and tick else {})})        # at=None: the module is imported but not switched on; tick=None: the plugin's own default
    r = subprocess.run([sys.executable, "-c", "import clockrun\n" + textwrap.dedent(code)], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()


def cli(*args, cwd=None):
    env = {k: v for k, v in os.environ.items() if k not in (C.ENV_AT, C.ENV_TICK)}
    return subprocess.run([sys.executable, str(DEV / "clockrun.py"), *args], capture_output=True, text=True, timeout=120, cwd=cwd, env=env)


# ---------------------------------------------------------------- the instant


def test_it_does_nothing_unless_it_is_asked():
    import datetime as dt
    assert dt.datetime.__name__ == "datetime" and dt.date.__name__ == "date"                 # this process was started without the plugin: the real classes


def test_the_clock_starts_at_the_chosen_instant_and_keeps_running():
    out = child("""
        import datetime as d, time
        a = d.datetime.now(d.timezone.utc)
        time.sleep(0.3)
        b = d.datetime.now(d.timezone.utc)
        print(a.isoformat()[:19])
        print(round((b - a).total_seconds(), 1))
    """)
    assert out[0] == "2031-02-03T04:05:06" and out[1] in ("0.3", "0.4")


def test_the_clock_ticks_when_only_the_instant_is_given():
    out = child("""
        import datetime as d, time
        a = d.datetime.now(d.timezone.utc)
        time.sleep(0.3)
        print(round((d.datetime.now(d.timezone.utc) - a).total_seconds(), 1))
    """, tick=None)
    assert out[0] in ("0.3", "0.4")                                                              # the default is a clock that runs: only an explicit "0" freezes it


def test_with_no_tick_the_clock_stands_still():
    out = child("""
        import datetime as d, time
        a = d.datetime.now(d.timezone.utc)
        time.sleep(0.3)
        print(a == d.datetime.now(d.timezone.utc), time.time() == time.time())
    """, tick="0")
    assert out == ["True True"]


def test_every_way_of_asking_for_the_time_agrees():
    out = child("""
        import datetime as d, time
        print(d.datetime.now(d.timezone.utc).date(), d.date.today(), d.datetime.now().date(), d.datetime.today().date(), d.datetime.utcnow().date(), time.strftime("%Y-%m-%d", time.gmtime(time.time())))
        print(abs(time.time_ns() // 1_000_000_000 - int(time.time())) <= 1, d.datetime.fromtimestamp(time.time(), d.timezone.utc).hour, d.datetime.utcnow().hour, d.datetime.utcnow().tzinfo is None, d.datetime.today().hour)
    """)
    assert out == ["2031-02-03 2031-02-03 2031-02-03 2031-02-03 2031-02-03 2031-02-03", "True 4 4 True 4"]                  # the time zone of the child is UTC, so local and UTC agree; utcnow has no zone, as the real one has none


def test_a_time_zone_is_applied_to_the_fake_instant():
    out = child("""
        import datetime as d
        print(d.datetime.now(d.timezone(d.timedelta(hours=-5))).isoformat()[:19])
    """)
    assert out == ["2031-02-02T23:05:06"]


def test_the_monotonic_clocks_stay_real():
    out = child("""
        import time
        print(time.time() > 1.7e9, time.monotonic() < 1e9, time.perf_counter() < 1e9)
    """)
    assert out == ["True True True"]


# ---------------------------------------------------------------- the replaced classes


def test_values_made_by_the_replaced_classes_work_like_datetimes():
    out = child("""
        from datetime import date, datetime, timedelta, timezone
        n = datetime.now(timezone.utc)
        later = n + timedelta(days=1)
        print(isinstance(later, datetime), later > n, later.isoformat()[:10], later.date() == date(2031, 2, 4), isinstance(date(2026, 1, 1), datetime))
        print(datetime.fromisoformat("2026-11-25T00:00:00+00:00") < n, datetime.combine(date(2026, 1, 2), n.timetz()).isoformat()[:10], datetime(2020, 1, 1) < datetime(2021, 1, 1))
    """)
    assert out == ["True True 2031-02-04 True False", "True 2026-01-02 True"]


def test_a_subclass_of_the_replaced_classes_works():
    out = child("""
        import datetime as d
        class Yours(d.datetime):
            pass
        class Mine(d.date):
            pass
        print(Yours(2026, 1, 1).year, Mine(2026, 1, 1).year, isinstance(Yours(2026, 1, 1), d.datetime))
    """)
    assert out == ["2026 2026 True"]


def test_pydantic_v1_is_imported_before_the_clock_is_replaced():
    pytest.importorskip("pydantic")
    out = child("""
        import pydantic.v1.types as t
        print(t.ConstrainedDate.__name__)
    """)
    assert out == ["ConstrainedDate"]                                                            # pydantic v1 derives ConstrainedDate from date with a metaclass of its own: with the classes replaced first, the import stopped with a metaclass conflict (found 2026-11-25)


def test_a_datetime_made_by_a_library_is_still_a_datetime_and_a_date_to_the_replaced_classes():
    pytest.importorskip("pandas")
    pytest.importorskip("dateutil")
    out = child("""
        import datetime as d
        import pandas as pd
        from dateutil.relativedelta import relativedelta
        ts = pd.Timestamp("2031-02-03 04:05")
        print(isinstance(ts, d.datetime), isinstance(ts, d.date), isinstance(d.datetime(2026, 1, 1), d.date))
        print(type(pd.Timestamp.now().floor("D") - pd.DateOffset(years=20)).__name__, (ts.to_pydatetime() + relativedelta(years=1)).year)
    """)
    assert out == ["True True True", "Timestamp 2032"]                                                # dateutil asks isinstance(x, datetime.date) with the replaced class and refused every real datetime (42 tests failed on it, found 2026-11-25)


def test_numpy_and_pandas_are_imported_before_the_clock_is_replaced():
    pytest.importorskip("pandas")
    out = child("""
        import pandas as pd
        print(pd.Timestamp("2026-11-25").year)
    """)
    assert out == ["2026"]                                                                       # with the classes replaced first, importing pandas ended the interpreter (found 2026-11-25)


def test_a_library_that_is_not_installed_is_skipped_quietly():
    out = child("""
        import datetime as d
        clockrun.PRELOAD = ("no_such_library_for_the_clock",)
        clockrun.install(clockrun.parse_at("2031-02-03T04:05:06+00:00"))
        print(d.datetime.now(d.timezone.utc).year)
    """, at=None)
    assert out == ["2031"]                                                                       # the list of libraries imported first may name one this machine does not have


# ---------------------------------------------------------------- the instant is checked


def test_an_instant_needs_an_offset_and_may_be_written_with_z():
    assert C.parse_at("2026-11-25T05:07:00+00:00") == datetime(2026, 11, 25, 5, 7, tzinfo=timezone.utc)
    assert C.parse_at(" 2026-11-25T05:07:00Z ") == datetime(2026, 11, 25, 5, 7, tzinfo=timezone.utc)
    assert C.parse_at("2026-11-25T00:07:00-05:00") == datetime(2026, 11, 25, 5, 7, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="has no offset"):
        C.parse_at("2026-11-25T05:07:00")
    with pytest.raises(ValueError, match="is not a date and time"):
        C.parse_at("yesterday")


def test_the_command_line_refuses_a_time_without_an_offset_before_it_runs_anything():
    r = cli("--at", "2026-11-25T05:07:00", "--", "-q")
    assert r.returncode == 2 and "has no offset" in r.stderr and r.stdout == ""
    r = cli("--", "-q")
    assert r.returncode == 2 and "--at" in r.stderr


# ---------------------------------------------------------------- pytest under the fake clock


def write_suite(folder, body):
    (folder / "test_clock.py").write_text(textwrap.dedent(body))


def test_the_command_line_runs_pytest_under_the_fake_clock_and_names_it_in_the_header(tmp_path):
    write_suite(tmp_path, """
        import datetime
        def test_the_clock_is_where_it_was_put():
            assert datetime.date.today().isoformat() == "2031-02-03"
            assert datetime.datetime.now(datetime.timezone.utc).hour == 4
    """)
    r = cli("--at", "2031-02-03T04:05:06+00:00", "--cwd", str(tmp_path), "--", "-p", "no:cacheprovider")
    assert r.returncode == 0 and "1 passed" in r.stdout, r.stdout + r.stderr
    assert "fake clock: starts at 2031-02-03T04:05:06+00:00 (ticking)" in r.stdout
    r = cli("--at", "2031-02-03T04:05:06+00:00", "--no-tick", "--cwd", str(tmp_path), "--", "-p", "no:cacheprovider")
    assert r.returncode == 0 and "(frozen)" in r.stdout


def test_an_instant_written_with_z_or_another_offset_reaches_pytest_as_the_same_instant(tmp_path):
    write_suite(tmp_path, """
        import datetime
        def test_the_instant_is_the_same_whichever_way_it_was_written():
            assert datetime.datetime.now(datetime.timezone.utc).isoformat()[:16] == "2031-02-03T04:05"
    """)
    for at in ("2031-02-03T04:05:06Z", "2031-02-02T23:05:06-05:00"):
        r = cli("--at", at, "--cwd", str(tmp_path), "--", "-q", "-p", "no:cacheprovider")
        assert r.returncode == 0 and "1 passed" in r.stdout, (at, r.stdout + r.stderr)


def test_the_exit_code_is_pytests_so_a_failing_test_is_a_failing_run(tmp_path):
    write_suite(tmp_path, """
        import datetime
        def test_this_fails_on_any_other_day():
            assert datetime.date.today().isoformat() == "2031-02-04"
    """)
    r = cli("--at", "2031-02-03T04:05:06+00:00", "--cwd", str(tmp_path), "--", "-q", "-p", "no:cacheprovider")
    assert r.returncode == 1 and "1 failed" in r.stdout


def test_without_arguments_after_the_double_dash_pytest_runs_quietly(tmp_path):
    write_suite(tmp_path, """
        def test_nothing():
            pass
    """)
    r = cli("--at", AT, "--cwd", str(tmp_path))
    assert r.returncode == 0 and "1 passed" in r.stdout and "fake clock" not in r.stdout        # -q is the default, and -q leaves the header out
