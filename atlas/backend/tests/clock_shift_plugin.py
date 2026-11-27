"""Date-rot check (not a test): runs the suite with the clock moved forward, to catch tests that quietly depend on today's date (the news sample stories did, on 2026-11-13).

Needs `pip install freezegun`. From atlas/backend, run the suite twice and compare the two lists of failures:
  SHIFT_TO=<today>T12:00:00      PYTHONPATH=tests python -m pytest -q -p clock_shift_plugin   # baseline: failures here are freezegun artefacts, not rot
  SHIFT_TO=<today+40 days>T12:00:00 PYTHONPATH=tests python -m pytest -q -p clock_shift_plugin   # failures that appear ONLY here are date rot
Under a frozen clock about 220 tests (paper trading, agents, telegram, auth, ibkr, alerts, ...) fail even at baseline, so they cannot be checked this way. Sample data built at import time also looks stale under a shifted clock (a harness artefact).
"""
import os

import pytest
from freezegun import freeze_time


@pytest.fixture(autouse=True)
def _shifted_clock():
    with freeze_time(os.environ["SHIFT_TO"], tick=True):
        yield
