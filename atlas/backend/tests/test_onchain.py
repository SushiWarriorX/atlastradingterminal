"""mempool.space network health: parsed from real responses (fetched 2026-11-08), arithmetic, each section fails on its own, demo invents nothing."""
import asyncio
import json
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import onchain as O
from atlas_api.app import create_app

FX = Path(__file__).parent / "fixtures"
FEES, DIFF, MEMPOOL, HASH = (json.loads((FX / f).read_text()) for f in ("mp_fees.json", "mp_diff.json", "mp_mempool.json", "mp_hash.json"))
TIP = (FX / "mp_tip.txt").read_text().strip()
POOLS = {c: json.loads((FX / f"mp_pools_{c}.json").read_text()) for c in ("1w", "1m", "3m")}          # real responses, fetched 2026-11-15
REWARD = json.loads((FX / "mp_reward_stats.json").read_text())                                           # the real answer, fetched 2026-11-15 20:18 UTC: the 144 blocks 975,868 to 976,011
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_fees_are_read_with_a_typical_transaction_cost_by_arithmetic():
    f = O.parse_fees(FEES, MEMPOOL)
    assert f["sat_per_vbyte"]["fastest"] == FEES["fastestFee"] and f["typical_tx_sats_fastest"] == FEES["fastestFee"] * 140 and f["typical_tx_vbytes"] == 140
    assert f["mempool"]["transactions"] == MEMPOOL["count"] and f["mempool"]["megavbytes"] == round(MEMPOOL["vsize"] / 1e6, 1) and f["mempool"]["total_fees_btc"] == round(MEMPOOL["total_fee"] / 1e8, 4)
    assert "mempool" not in O.parse_fees(FEES, None)


def test_difficulty_cycle_fields_come_from_the_source():
    d = O.parse_difficulty(DIFF, int(TIP))
    assert d["remaining_blocks"] == DIFF["remainingBlocks"] and d["next_adjustment_height"] == DIFF["nextRetargetHeight"] and d["block_height"] == int(TIP)
    assert d["estimated_change_pct"] == round(DIFF["difficultyChange"], 2) and d["estimated_date"] > "2026-11-08" and "estimate" in d["note"]
    assert d["next_adjustment_height"] - d["block_height"] == d["remaining_blocks"]            # the two sources agree


def test_hashrate_headline_is_a_seven_day_average_in_exahashes():
    h = O.parse_hashrate(HASH)
    last7 = [r["avgHashrate"] for r in sorted(HASH["hashrates"], key=lambda r: r["timestamp"])[-7:]]
    assert h["seven_day_average_eh"] == round(sum(last7) / 7 / 1e18, 1) and 100 < h["seven_day_average_eh"] < 5000
    assert h["current_eh"] == round(HASH["currentHashrate"] / 1e18, 1) and len(h["history"]) == 90 and h["changes"]
    assert h["highest_day"]["eh"] >= h["latest_day_eh"] and h["highest_day"]["eh"] >= h["seven_day_average_eh"]
    assert [c["label"] for c in h["changes"]] == ["30 days", "90 days"] or [c["label"] for c in h["changes"]] == ["30 days"]


def test_too_little_hashrate_history_is_refused():
    with pytest.raises(ValueError):
        O.parse_hashrate({"hashrates": HASH["hashrates"][:5]})


def routes(req):
    path = req.url.path.replace("/api/", "")
    return {"v1/fees/recommended": httpx.Response(200, json=FEES), "mempool": httpx.Response(200, json=MEMPOOL), "v1/difficulty-adjustment": httpx.Response(200, json=DIFF),
            "blocks/tip/height": httpx.Response(200, text=TIP), "v1/mining/hashrate/3m": httpx.Response(200, json=HASH),
            **{f"v1/mining/pools/{c}": httpx.Response(200, json=POOLS[c]) for c in POOLS}, "v1/mining/reward-stats/144": httpx.Response(200, json=REWARD)}.get(path, httpx.Response(404))


def go(handler, demo=False):
    return asyncio.run(O.OnChain(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_all_five_sections_with_a_source():
    r = go(routes)
    assert all(r[k]["available"] for k in ("fees", "difficulty", "hashrate", "pools", "revenue")) and "mempool.space" in r["source"]


def test_one_failing_section_does_not_hide_the_others():
    def h(req):
        return httpx.Response(503) if "hashrate" in req.url.path else routes(req)
    r = go(h)
    assert r["fees"]["available"] and r["difficulty"]["available"] and r["pools"]["available"] and r["revenue"]["available"] and r["hashrate"]["available"] is False and "hashrate" in r["hashrate"]["reason"] and "history" not in r["hashrate"]


def test_a_missing_mempool_or_height_only_drops_the_extra():
    def h(req):
        return httpx.Response(500) if req.url.path.endswith(("/mempool", "/height")) else routes(req)
    r = go(h)
    assert r["fees"]["available"] and "mempool" not in r["fees"] and r["difficulty"]["available"] and r["difficulty"]["block_height"] is None


def test_everything_failing_says_so_five_times_and_shows_no_numbers():
    r = go(lambda req: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert not any(r[k]["available"] for k in ("fees", "difficulty", "hashrate", "pools", "revenue"))


def test_demo_mode_invents_nothing(tmp_path):
    r = go(routes, demo=True)
    assert not any(r[k]["available"] for k in ("fees", "difficulty", "hashrate", "pools", "revenue"))
    with TestClient(create_app(db_path=str(tmp_path / "o.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        assert c.get("/api/btc/network").json()["data"]["demo"] is True


# ---------------------------------------------------------------------------------------------------------- who mines the blocks
def window(pools, total=None):
    """A source answer built from (name, blocks) pairs; the total is their sum unless given."""
    return {"blockCount": sum(b for _, b in pools) if total is None else total, "pools": [{"name": n, "blockCount": b, "rank": i + 1} for i, (n, b) in enumerate(pools)]}


def three(one_week, one_month, three_months):
    return {"1w": window(one_week), "1m": window(one_month), "3m": window(three_months)}


# totals that are exactly 144 blocks a day: 1,008 in a week, 4,320 in 30 days, 13,104 in 91 days
TINY = three([("A", 400), ("B", 300), ("C", 200), ("Unknown", 108)], [("A", 1728), ("B", 1296), ("C", 864), ("Unknown", 432)], [("A", 5242), ("B", 3931), ("C", 2621), ("Unknown", 1310)])


def test_pool_shares_are_worked_out_from_the_real_responses_by_hand():
    r = O.parse_pools(POOLS)
    m = POOLS["1m"]
    named = sorted(((x["name"], x["blockCount"]) for x in m["pools"] if x["name"] != "Unknown"), key=lambda a: (-a[1], a[0]))
    total = m["blockCount"]
    assert total == sum(x["blockCount"] for x in m["pools"]) == 4383                                  # the source's total is the sum of its pools
    assert r["headline_window"] == "1 month" and [w["label"] for w in r["windows"]] == ["1 week", "1 month", "3 months"] and [w["days"] for w in r["windows"]] == [7, 30, 91]
    one = r["windows"][1]
    assert (one["blocks"], one["pools_seen"], one["top_pool"]) == (4383, len(named), "Foundry USA") and one["top_pool_pct"] == round(100 * named[0][1] / total, 1) == 25.6
    assert one["top3_pct"] == round(100 * sum(b for _, b in named[:3]) / total, 1) == 62.3
    assert one["hhi"] == round(sum((100 * b / total) ** 2 for _, b in named)) == 1538
    assert one["nakamoto"] == 3 and 2 * (named[0][1] + named[1][1]) < total < 2 * (named[0][1] + named[1][1] + named[2][1])       # two pools are under half of the blocks, three are over
    assert one["unidentified_pct"] == round(100 * (total - sum(b for _, b in named)) / total, 1) == 0.4
    assert [p["name"] for p in r["top_pools"]] == [n for n, _ in named[:6]] and [p["blocks"] for p in r["top_pools"]] == [b for _, b in named[:6]]
    assert r["top_pools"][0]["share_pct"] == 25.6 and r["others_pct"] == round(100 * sum(b for _, b in named[6:]) / total, 1) == 17.0
    assert round(sum(p["share_pct"] for p in r["top_pools"]) + r["others_pct"] + r["unidentified_pct"]) == 100
    assert r["unidentified_pct"] == one["unidentified_pct"] and "not who owns the machines" in r["note"] and "Nakamoto" in r["note"]
    json.dumps(r)


def test_concentration_measures_on_a_made_up_month_with_every_number_worked_by_hand():
    r = O.parse_pools(TINY)
    w = r["windows"][1]                                    # 4,320 blocks: A 40%, B 30%, C 20%, 10% unidentified
    assert w["top_pool"] == "A" and w["top_pool_pct"] == 40.0 and w["top3_pct"] == 90.0 and w["unidentified_pct"] == 10.0 and w["pools_seen"] == 3
    assert w["hhi"] == 2900                                # 40 squared + 30 squared + 20 squared; the unidentified blocks are not a pool
    assert w["nakamoto"] == 2                              # 40% is not half; 40% + 30% is
    assert r["others_pct"] == 0.0 and [p["share_pct"] for p in r["top_pools"]] == [40.0, 30.0, 20.0]
    one_week = r["windows"][0]
    assert one_week["blocks"] == 1008 and one_week["top_pool_pct"] == round(100 * 400 / 1008, 1) and one_week["hhi"] == round((100 * 400 / 1008) ** 2 + (100 * 300 / 1008) ** 2 + (100 * 200 / 1008) ** 2)


def test_exactly_half_of_the_blocks_is_not_a_majority_and_one_big_pool_is_one():
    half = three([("A", 504), ("B", 504)], [("A", 2160), ("B", 1728), ("Unknown", 432)], [("A", 6552), ("B", 6552)])
    assert [w["nakamoto"] for w in O.parse_pools(half)["windows"]] == [2, 2, 2]                 # 50% exactly needs a second pool
    big = three([("A", 600), ("B", 408)], [("A", 2400), ("B", 1920)], [("A", 7000), ("B", 6104)])
    assert [w["nakamoto"] for w in O.parse_pools(big)["windows"]] == [1, 1, 1]
    scattered = three([("A", 200), ("B", 200), ("Unknown", 608)], [("A", 1000), ("B", 1000), ("Unknown", 2320)], [("A", 3000), ("B", 3000), ("Unknown", 7104)])
    assert [w["nakamoto"] for w in O.parse_pools(scattered)["windows"]] == [None, None, None]         # the named pools together do not reach half: no coefficient is claimed


def test_blocks_from_unnamed_miners_are_kept_apart_whatever_the_capitalisation():
    r = O.parse_pools(three([("A", 500), ("unknown", 508)], [("A", 2000), ("UNKNOWN", 2320)], [("A", 6000), ("Unknown", 7104)]))
    assert [w["unidentified_pct"] for w in r["windows"]] == [round(100 * 508 / 1008, 1), round(100 * 2320 / 4320, 1), round(100 * 7104 / 13104, 1)] and all(w["pools_seen"] == 1 for w in r["windows"])


def test_a_response_whose_pools_do_not_add_up_to_its_total_is_refused():
    bad = dict(TINY)
    bad["1m"] = window([("A", 1728), ("B", 1296), ("C", 864), ("Unknown", 432)], total=4321)
    with pytest.raises(ValueError, match="add up"):
        O.parse_pools(bad)
    for broken in (window([], total=1008), window([("A", -5), ("B", 1013)]), window([("A", 0)], total=0), window([], total=0)):
        with pytest.raises(ValueError):
            O.parse_pools({**TINY, "1w": broken})


def test_a_window_with_no_named_pool_is_refused_rather_than_guessed():
    for none_named in (window([("Unknown", 1008)]), window([("unknown", 500), ("UNKNOWN", 508)])):
        with pytest.raises(ValueError, match="no pool is named"):
            O.parse_pools({**TINY, "1w": none_named})
    assert go(lambda req: httpx.Response(200, json=window([("Unknown", 1008)])) if "/pools/" in req.url.path else routes(req))["pools"]["available"] is False


def test_a_block_count_that_cannot_belong_to_the_window_is_refused():
    low, high = 504, 1512                                                                                   # half and one and a half times 7 x 144
    assert O.parse_pools({**TINY, "1w": window([("A", low)])})["windows"][0]["blocks"] == low
    assert O.parse_pools({**TINY, "1w": window([("A", high)])})["windows"][0]["blocks"] == high
    for n in (low - 1, high + 1, 0):
        with pytest.raises(ValueError):
            O.parse_pools({**TINY, "1w": window([("A", n)], total=n)})
    with pytest.raises(ValueError, match="not plausible"):
        O.parse_pools({**TINY, "3m": window([("A", 4383)])})                                               # a month's blocks offered as three months'


def test_a_missing_field_is_an_error_not_a_guess():
    for broken in ({"blockCount": 1008}, {"pools": [{"name": "A", "blockCount": 1008}]}, {"blockCount": 1008, "pools": [{"blockCount": 1008}]}):
        with pytest.raises((KeyError, TypeError, ValueError)):
            O.parse_pools({**TINY, "1w": broken})


def test_the_service_asks_for_all_three_windows_and_reports_pools_with_the_rest():
    asked = []

    def h(req):
        asked.append(req.url.path)
        return routes(req)
    r = go(h)
    assert sorted(p for p in asked if "/pools/" in p) == ["/api/v1/mining/pools/1m", "/api/v1/mining/pools/1w", "/api/v1/mining/pools/3m"]
    assert r["pools"]["available"] and r["pools"]["windows"][1]["top_pool"] == "Foundry USA"


def test_a_failing_pool_window_only_loses_the_pool_section_and_says_why_in_words():
    def h(req):
        return httpx.Response(503) if req.url.path.endswith("/pools/3m") else routes(req)
    r = go(h)
    assert r["fees"]["available"] and r["difficulty"]["available"] and r["hashrate"]["available"] and r["pools"]["available"] is False
    assert r["pools"]["reason"] == "mempool.space mining pools could not be read right now (the server had an error, HTTP 503)"            # in words, not an exception name
    def corrupt(req):
        return httpx.Response(200, json={"blockCount": 3}) if "/pools/1w" in req.url.path else routes(req)
    assert go(corrupt)["pools"]["available"] is False and go(corrupt)["fees"]["available"]


def test_the_pool_section_is_in_the_route_for_the_phone(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "p.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/btc/network").json()["data"]
        assert d["pools"]["available"] is False and "Demo mode" in d["pools"]["reason"]


def test_a_good_answer_is_kept_for_five_minutes_and_one_with_a_failed_section_for_one(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(O, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))                    # the module's own clock only; asyncio keeps the real one

    async def seen(handler, waits):
        calls = []

        def counting(req):
            calls.append(req.url.path)
            return handler(req)
        svc = O.OnChain(httpx.AsyncClient(transport=httpx.MockTransport(counting)))
        await svc.overview(NOW)
        first, counts = len(calls), []
        for wait in waits:
            clock[0] += wait
            await svc.overview(NOW)
            counts.append(len(calls) - first)
        return first, counts
    first, counts = asyncio.run(seen(routes, [299, 2]))
    assert first >= 9 and counts[0] == 0 and counts[1] >= 9                                              # still kept at 299 s, fetched again after 301 s
    failing_pools = lambda req: httpx.Response(503) if "/pools/" in req.url.path else routes(req)
    first, counts = asyncio.run(seen(failing_pools, [59, 2]))
    assert counts[0] == 0 and counts[1] >= 9                                                             # a failed section is kept for only a minute, so it is retried soon
    failing_revenue = lambda req: httpx.Response(503) if "/reward-stats/" in req.url.path else routes(req)
    first, counts = asyncio.run(seen(failing_revenue, [59, 2]))
    assert counts[0] == 0 and counts[1] >= 9                                                             # the miner revenue section counts too: a failure there is retried after a minute, not five


# ---------------------------------------------------------------------------------------------------------- what the miners earned
def answer(start=975868, end=976011, reward=45_173_127_020, fee=173_127_020, tx=821_183):
    return {"startBlock": start, "endBlock": end, "totalReward": str(reward), "totalFee": str(fee), "totalTx": str(tx)}


def test_the_subsidy_follows_the_halving_schedule_at_every_boundary():
    sats = {0: 5_000_000_000, 209_999: 5_000_000_000, 210_000: 2_500_000_000, 419_999: 2_500_000_000, 420_000: 1_250_000_000, 630_000: 625_000_000, 839_999: 625_000_000, 840_000: 312_500_000,
            975_868: 312_500_000, 1_049_999: 312_500_000, 1_050_000: 156_250_000}
    for h, v in sats.items():
        assert O.subsidy_sats(h) == v, h
    assert O.subsidy_sats(33 * 210_000 - 1) == 1 and O.subsidy_sats(33 * 210_000) == 0 and O.subsidy_sats(10_000_000_000) == 0          # 50 BTC shifted right 32 times is one satoshi; the 33rd halving leaves nothing
    assert sum(210_000 * O.subsidy_sats(e * 210_000) for e in range(0, 40)) == 2_099_999_997_690_000                                       # Bitcoin's total supply, 20,999,999.9769 BTC: the rule, summed over every era
    for bad in (-1, -210_000):
        with pytest.raises(ValueError, match="cannot be negative"):
            O.subsidy_sats(bad)


def test_a_window_adds_the_right_subsidy_to_each_block_even_across_halvings():
    assert O.subsidy_total(975_868, 976_011) == 144 * 312_500_000 == 45_000_000_000 and O.subsidy_total(5, 5) == 5_000_000_000
    assert O.subsidy_total(839_990, 840_009) == 10 * 625_000_000 + 10 * 312_500_000                                                    # ten blocks of 6.25 BTC, then ten of 3.125
    assert O.subsidy_total(209_999, 420_000) == 5_000_000_000 + 210_000 * 2_500_000_000 + 1_250_000_000                              # across two halvings
    assert O.subsidy_total(10, 9) == 0


def test_the_real_answer_is_worked_out_by_hand():
    r = O.parse_revenue(REWARD, date(2026, 11, 15))
    assert r["available"] and r["blocks"] == 144 and (r["first_block"], r["last_block"]) == (975_868, 976_011)
    assert (r["reward_btc"], r["subsidy_btc"], r["fees_btc"]) == (451.7313, 450.0, 1.7313)                              # 45,173,127,020 = 45,000,000,000 + 173,127,020 satoshis
    assert r["fee_share_pct"] == 0.38 and r["subsidy_per_block_btc"] == 3.125                                          # 173,127,020 / 45,173,127,020 = 0.3833%
    assert (r["avg_reward_per_block_btc"], r["avg_fee_per_block_btc"]) == (3.137, 0.012)                                 # 313,702,271 and 1,202,271 satoshis
    assert (r["transactions"], r["tx_per_block"], r["avg_fee_per_tx_sats"]) == (821_183, 5703, 211)                    # 821,183 / 144 = 5,702.7 and 173,127,020 / 821,183 = 210.8
    h = r["halving"]
    assert (h["height"], h["blocks_left"], h["days_left"], h["subsidy_after_btc"]) == (1_050_000, 73_989, 514, 1.5625)  # 73,989 blocks at ten minutes each is 513.8 days
    assert h["estimated_date"] == (date(2026, 11, 15) + timedelta(days=514)).isoformat()
    assert "not a price signal" in r["note"].lower() and "estimate" in r["note"].lower()


def test_the_next_halving_is_the_next_multiple_of_210000_after_the_newest_block():
    for end, nxt, left in ((1_049_999, 1_050_000, 1), (1_050_000, 1_260_000, 210_000), (840_000, 1_050_000, 210_000), (976_011, 1_050_000, 73_989)):
        r = O.parse_revenue(answer(start=end - 143, end=end, reward=O.subsidy_total(end - 143, end) + 1_000, fee=1_000, tx=144), date(2026, 11, 15))
        assert (r["halving"]["height"], r["halving"]["blocks_left"]) == (nxt, left), end


def test_a_window_across_a_halving_passes_with_each_block_at_its_own_subsidy():
    start, end = 839_930, 840_073                                                                                         # 70 blocks of 6.25 BTC and 74 of 3.125
    total = 70 * 625_000_000 + 74 * 312_500_000
    r = O.parse_revenue(answer(start, end, reward=total + 5_000_000, fee=5_000_000, tx=700_000), date(2026, 11, 15))
    assert r["subsidy_btc"] == total / 1e8 and r["subsidy_per_block_btc"] == 3.125 and r["halving"]["height"] == 1_050_000


def test_the_reward_minus_the_fees_must_equal_the_subsidy_of_the_window_within_a_thousand_satoshis():
    sub = 45_000_000_000
    for gap in (-1000, 0, 1000):
        assert O.parse_revenue(answer(reward=sub + 173_127_020 + gap), date(2026, 11, 15))["available"]
    for gap in (-1001, 1001, 312_500_000, -312_500_000):                                                               # one whole block's subsidy missing or extra is a real refusal
        with pytest.raises(ValueError, match="sats away from the subsidy of 144 blocks"):
            O.parse_revenue(answer(reward=sub + 173_127_020 + gap), date(2026, 11, 15))
    with pytest.raises(ValueError, match="sats away from the subsidy"):                                                 # a fee total off by a factor of ten (a unit slip)
        O.parse_revenue(answer(fee=1_731_270_200), date(2026, 11, 15))


def test_the_window_must_be_exactly_144_blocks():
    sub, fee = 45_000_000_000, 173_127_020
    for start, end in ((975_868, 976_012), (975_868, 976_010), (976_011, 975_868), (975_868, 975_868)):
        with pytest.raises(ValueError, match="blocks, not 144"):
            O.parse_revenue(answer(start, end, reward=sub + fee), date(2026, 11, 15))


def test_totals_must_be_in_range():
    today = date(2026, 11, 15)
    with pytest.raises(ValueError, match="out of range"):
        O.parse_revenue(answer(reward=45_000_000_000, fee=45_000_000_001), today)                                      # fees above the whole reward
    with pytest.raises(ValueError, match="out of range"):
        O.parse_revenue(answer(reward=45_000_000_000 - 100, fee=-100), today)                                          # a negative fee total
    with pytest.raises(ValueError, match="out of range"):
        O.parse_revenue(answer(reward=0, fee=0), today)
    assert O.parse_revenue(answer(reward=45_000_000_000, fee=0, tx=144), today)["fee_share_pct"] == 0.0              # no fees at all is a real answer; one transaction a block (the coinbase) is the least possible
    with pytest.raises(ValueError, match="out of range"):
        O.parse_revenue(answer(tx=143), today)
    assert O.parse_revenue(answer(reward=O.subsidy_total(975_868, 976_011), fee=0, tx=144), today)["avg_fee_per_tx_sats"] == 0


def test_a_missing_or_unreadable_field_is_an_error_not_a_guess():
    today = date(2026, 11, 15)
    for k in ("startBlock", "endBlock", "totalReward", "totalFee", "totalTx"):
        bad = dict(answer())
        del bad[k]
        with pytest.raises(KeyError):
            O.parse_revenue(bad, today)
    with pytest.raises(ValueError):
        O.parse_revenue({**answer(), "totalFee": "a lot"}, today)


def test_the_service_asks_for_the_144_block_statistics_and_reports_them_with_the_rest():
    asked = []

    def h(req):
        asked.append(req.url.path)
        return routes(req)
    r = go(h)
    assert "/api/v1/mining/reward-stats/144" in asked and r["revenue"]["available"] and r["revenue"]["fees_btc"] == 1.7313 and r["fees"]["available"] and r["pools"]["available"]
    assert r["revenue"]["halving"]["estimated_date"] == (NOW.date() + timedelta(days=514)).isoformat()                  # the estimate counts from the day of the request


def test_a_failing_or_corrupt_revenue_answer_only_loses_the_revenue_section_and_says_why_in_words():
    def down(req):
        return httpx.Response(503) if "/reward-stats/" in req.url.path else routes(req)
    r = go(down)
    assert r["fees"]["available"] and r["difficulty"]["available"] and r["hashrate"]["available"] and r["pools"]["available"] and r["revenue"]["available"] is False
    assert r["revenue"]["reason"] == "mempool.space miner revenue could not be read right now (the server had an error, HTTP 503)"
    def wrong(req):
        return httpx.Response(200, json=answer(fee=1_731_270_200)) if "/reward-stats/" in req.url.path else routes(req)
    w = go(wrong)
    assert w["revenue"]["available"] is False and "failed a check" in w["revenue"]["reason"] and "sats away from the subsidy" in w["revenue"]["reason"] and w["pools"]["available"]
    assert "revenue_btc" not in w["revenue"] and "fee_share_pct" not in w["revenue"]


def test_the_revenue_section_is_in_the_route_for_the_phone(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "r.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/btc/network").json()["data"]
        assert d["revenue"]["available"] is False and "Demo mode" in d["revenue"]["reason"]


def test_the_fee_share_is_of_the_whole_reward_worked_by_hand_on_a_busy_day():
    r = O.parse_revenue(answer(reward=55_000_000_000, fee=10_000_000_000, tx=1_000_000), date(2026, 11, 15))                # 100 BTC of fees on top of 450 BTC of subsidy: 100 / 550
    assert (r["fees_btc"], r["subsidy_btc"], r["reward_btc"], r["fee_share_pct"]) == (100.0, 450.0, 550.0, 18.18)
    assert (r["avg_fee_per_tx_sats"], r["tx_per_block"], r["avg_fee_per_block_btc"], r["avg_reward_per_block_btc"]) == (10_000, 6944, 0.694, 3.819)           # 10e9 / 1e6, 1e6 / 144, 100 / 144 and 550 / 144


def test_after_the_last_halving_the_whole_reward_is_fees_and_that_is_not_out_of_range():
    start = 33 * HALVING_FOR_TEST + 10                                                                                      # from the 33rd halving the subsidy is zero
    r = O.parse_revenue(answer(start, start + 143, reward=900_000, fee=900_000, tx=500), date(2026, 11, 15))
    assert r["subsidy_btc"] == 0.0 and r["fee_share_pct"] == 100.0 and r["subsidy_per_block_btc"] == 0.0 and r["halving"]["subsidy_after_btc"] == 0.0


HALVING_FOR_TEST = 210_000
