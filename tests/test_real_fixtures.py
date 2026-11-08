"""Invariant checks on REAL API responses saved with scripts/save_fixture.py.
Skipped when no tests/fixtures/real_*.json files exist."""
import json
from pathlib import Path

import pytest

import stats

REAL = sorted((Path(__file__).parent / "fixtures").glob("real_*.json"))


@pytest.mark.skipif(not REAL, reason="no real fixtures saved yet (see scripts/save_fixture.py)")
@pytest.mark.parametrize("path", REAL, ids=[p.stem for p in REAL])
def test_real_match_invariants(path):
    match = json.loads(path.read_text())
    n_rounds = len(match["rounds"])
    assert match["metadata"]["queue"]["id"]
    _, side_check = stats.infer_sides(match)
    assert side_check in ("verified", "unverified"), f"side rule disagrees with plants: {side_check}"
    fk_total = 0
    for p in match["players"]:
        row = stats.match_row(match, p["puuid"])
        assert row["rounds"] == n_rounds
        assert row["attack_rounds"] + row["defense_rounds"] == n_rounds
        assert 0 <= row["kast_pct"] <= 100
        assert row["first_kills"] + row["first_deaths"] <= n_rounds
        if row["hs_pct"] is not None:
            assert 0 <= row["hs_pct"] <= 100
        fk_total += row["first_kills"]
        # kill events attributed to the player should not exceed the API's kill count
        rr = stats.round_rows(match, p["puuid"])
        assert sum(r["kills"] for r in rr) <= row["kills"]
    rounds_with_kills = len({k["round"] for k in match["kills"]})
    assert fk_total <= rounds_with_kills
