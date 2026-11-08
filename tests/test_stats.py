"""Stat tests against hand-designed fixtures.

Match A (Ascent, me = Jett on Red, 13-1 win, 14 rounds)
 rnd side    buy     events for me                               K  died FK FD KAST traded
 1   attack  pistol  first kill, killed, traded 2 s later        1  yes  Y  -  Y    Y
 2   attack  eco     2 kills (after a teammate died first), plant 2  no   -  -  Y    -
 3   attack  full    first death, trade 7 s later (too late)     0  yes  -  Y  N    N
 4   attack  full    assist, killed, trade 6 s later (too late)  0  yes  -  -  Y(A) N
 5   attack  light   (loadout 3899) survive                      0  no   -  -  Y    -
 6-12 attack full    (loadout 3900) survive                      0  no   -  -  Y    -
 13  defense pistol  first kill, defuse (enemy planted)          1  no   Y  -  Y    -
 14  defense full    kill, killed, traded 4 s later              1  yes  -  -  Y    Y
 Totals: K5 D4 A1, FK 2, FD 1, KAST 13/14, score 2010, damage 1830, HS 6/20, casts 16.

Match B (Bind, me = Sova on Blue, 12-14 OT loss, 26 rounds)
 Blue defends 1-12, attacks 13-24; OT round 25 Red attacks, round 26 Blue attacks.
 I win rounds 1-6 (defense) and 13-18 (attack). One kill per round: mine when we win, my death when we lose.
"""
import math

import pandas as pd
import pytest

import stats
from conftest import ME


# --------------------------------------------------------------------------- sides
def test_attacking_team_regulation_and_overtime():
    assert [stats.attacking_team(i) for i in (0, 11)] == ["red", "red"]
    assert [stats.attacking_team(i) for i in (12, 23)] == ["blue", "blue"]
    assert [stats.attacking_team(i) for i in (24, 25, 26, 27)] == ["red", "blue", "red", "blue"]


def test_infer_sides_verified(match_a, match_b):
    assert stats.infer_sides(match_a)[1] == "verified"
    assert stats.infer_sides(match_b)[1] == "verified"


def test_infer_sides_flipped_when_plants_contradict(match_a):
    for r in match_a["rounds"]:
        if r["plant"]:
            p = r["plant"]["player"]
            p["team"] = "Blue" if p["team"] == "Red" else "Red"
    attackers, status = stats.infer_sides(match_a)
    assert status == "flipped"
    assert attackers[0] == "blue" and attackers[12] == "red"


def test_infer_sides_conflict_and_unverified(match_a):
    match_a["rounds"][0]["plant"]["player"]["team"] = "Blue"  # one contradicting plant, others agree
    assert stats.infer_sides(match_a)[1] == "conflict"
    for r in match_a["rounds"]:
        r["plant"] = None
    assert stats.infer_sides(match_a)[1] == "unverified"


# --------------------------------------------------------------------------- per round
def test_round_rows_match_a(match_a):
    rows = stats.round_rows(match_a, ME)
    assert len(rows) == 14
    assert [r["side"] for r in rows] == ["attack"] * 12 + ["defense"] * 2
    assert [r["kills"] for r in rows] == [1, 2, 0, 0] + [0] * 8 + [1, 1]
    assert [r["first_kill"] for r in rows].count(True) == 2
    assert rows[0]["first_kill"] and rows[12]["first_kill"]
    assert [i for i, r in enumerate(rows) if r["first_death"]] == [2]
    assert [i for i, r in enumerate(rows) if r["died"]] == [0, 2, 3, 13]


def test_trade_window_5_seconds(match_a):
    rows = stats.round_rows(match_a, ME)
    assert rows[0]["traded"] is True     # 2 s
    assert rows[2]["traded"] is False    # 7 s
    assert rows[3]["traded"] is False    # 6 s
    assert rows[13]["traded"] is True    # 4 s


def test_kast_components(match_a):
    rows = stats.round_rows(match_a, ME)
    assert [r["kast"] for r in rows] == [True, True, False] + [True] * 11
    assert rows[3]["assisted"] and not rows[3]["survived"]


def test_buy_type_boundaries(match_a):
    rows = stats.round_rows(match_a, ME)
    assert rows[0]["buy_type"] == "pistol" and rows[12]["buy_type"] == "pistol"
    assert rows[1]["buy_type"] == "eco"
    assert rows[4]["buy_type"] == "light"   # 3899
    assert rows[5]["buy_type"] == "full"    # 3900
    assert stats.buy_type(5, None) == "unknown"
    assert stats.buy_type(5, 1999) == "eco" and stats.buy_type(5, 2000) == "light"


def test_plants_defuses_and_retake_flags(match_a):
    rows = stats.round_rows(match_a, ME)
    assert [i for i, r in enumerate(rows) if r["planted"]] == [1]
    assert [i for i, r in enumerate(rows) if r["defused"]] == [12]
    assert rows[12]["enemy_planted"] and not rows[12]["team_planted"]
    assert rows[0]["team_planted"]


def test_round_damage_and_score(match_a):
    rows = stats.round_rows(match_a, ME)
    assert sum(r["damage"] for r in rows) == 1830
    assert sum(r["score"] for r in rows) == 2010


# --------------------------------------------------------------------------- per match
def test_match_row_a(match_a, mmr_hist):
    row = stats.match_row(match_a, ME, stats.rr_lookup(mmr_hist))
    assert row["result"] == "Win" and row["score"] == "13-1"
    assert row["map"] == "Ascent" and row["agent"] == "Jett" and row["role"] == "Duelist"
    assert row["rounds"] == 14
    assert (row["kills"], row["deaths"], row["assists"]) == (5, 4, 1)
    assert row["kd"] == pytest.approx(1.25)
    assert row["acs"] == pytest.approx(2010 / 14)
    assert row["adr"] == pytest.approx(1830 / 14)
    assert row["hs_pct"] == pytest.approx(30.0)          # 6 / (6+10+4)
    assert row["leg_pct"] == pytest.approx(20.0)
    assert (row["first_kills"], row["first_deaths"]) == (2, 1)
    assert row["kast_pct"] == pytest.approx(100 * 13 / 14)
    assert (row["plants"], row["defuses"]) == (1, 1)
    assert row["avg_loadout"] == 3500.0
    assert row["ability_casts"] == 16
    assert row["casts_per_round"] == pytest.approx(16 / 14)
    assert row["rr_change"] == 21
    assert (row["attack_rounds"], row["attack_won"]) == (12, 11)
    assert (row["defense_rounds"], row["defense_won"]) == (2, 2)
    assert row["side_check"] == "verified"
    assert row["tracker_url"] == "https://tracker.gg/valorant/match/aaaaaaaa-0000-0000-0000-000000000001"
    assert row["game_length_min"] == 35.0


def test_match_row_b_overtime_and_cast_fallback(match_b, mmr_hist):
    row = stats.match_row(match_b, ME, stats.rr_lookup(mmr_hist))
    assert row["result"] == "Loss" and row["score"] == "12-14"
    assert row["rounds"] == 26
    assert (row["attack_rounds"], row["attack_won"]) == (13, 6)   # 12 regulation + OT round 26
    assert (row["defense_rounds"], row["defense_won"]) == (13, 6)
    assert row["ability_casts"] == 26                              # summed from rounds (player-level null)
    assert row["casts_per_round"] == pytest.approx(1.0)
    assert (row["first_kills"], row["first_deaths"]) == (12, 14)
    assert row["kast_pct"] == pytest.approx(100 * 12 / 26)
    assert row["acs"] == pytest.approx(200.0) and row["adr"] == pytest.approx(100.0)
    assert row["rr_change"] == -18
    assert row["kd"] == pytest.approx(12 / 14)


def test_ot_round_sides(match_b):
    rows = stats.round_rows(match_b, ME)
    assert rows[24]["side"] == "defense" and rows[25]["side"] == "attack"


def test_draw_and_zero_deaths(match_a):
    for t in match_a["teams"]:
        t["won"] = False
    for p in match_a["players"]:
        if p["puuid"] == ME:
            p["stats"]["deaths"] = 0
    row = stats.match_row(match_a, ME)
    assert row["result"] == "Draw"
    assert row["kd"] == 5.0
    assert row["rr_change"] is None


def test_missing_shots_gives_none(match_a):
    for p in match_a["players"]:
        if p["puuid"] == ME:
            p["stats"].update(headshots=0, bodyshots=0, legshots=0)
    assert stats.match_row(match_a, ME)["hs_pct"] is None


def test_player_not_in_match(match_a):
    with pytest.raises(KeyError):
        stats.find_player(match_a, "nobody")


# --------------------------------------------------------------------------- aggregates
def test_build_frames_and_summary(match_a, match_b, mmr_hist):
    mdf, rdf = stats.build_frames([match_b, match_a], ME, mmr_hist)
    assert list(mdf["map"]) == ["Ascent", "Bind"]                  # sorted oldest first
    assert len(rdf) == 40
    s = stats.summarize(mdf)
    assert s["games"] == 2 and s["wins"] == 1 and s["win_rate"] == 50.0
    assert s["acs"] == pytest.approx((2010 + 5200) / 40)            # round-weighted
    assert s["adr"] == pytest.approx((1830 + 2600) / 40)
    assert s["hs_pct"] == pytest.approx(100 * 9 / 30)
    assert s["kd"] == pytest.approx(17 / 18)
    assert s["kast_pct"] == pytest.approx(100 * 25 / 40)
    assert s["fd_pct"] == pytest.approx(100 * 15 / 40)
    assert s["entry_success_pct"] == pytest.approx(100 * 14 / 29)
    assert s["casts_per_round"] == pytest.approx(42 / 40)
    assert s["rr_total"] == 3
    assert s["survival_pct"] == pytest.approx(100 * (10 + 12) / 40)


def test_agent_filter(match_a, match_b):
    mdf, rdf = stats.build_frames([match_a, match_b], ME, agent_filter="Sova")
    assert list(mdf["agent"]) == ["Sova"] and len(rdf) == 26


def test_group_table_low_sample(match_a, match_b):
    mdf, _ = stats.build_frames([match_a, match_b], ME)
    t = stats.group_table(mdf, "agent")
    assert set(t["agent"]) == {"Jett", "Sova"}
    assert t["low_sample"].all()
    jett = t[t["agent"] == "Jett"].iloc[0]
    assert jett["win_rate"] == 100.0 and jett["games"] == 1


def test_side_table(match_a, match_b):
    _, rdf = stats.build_frames([match_a, match_b], ME)
    st = stats.side_table(rdf).set_index("side")
    assert st.loc["attack", "rounds"] == 25 and st.loc["defense", "rounds"] == 15
    assert st.loc["attack", "round_win_pct"] == pytest.approx(100 * 17 / 25)
    assert st.loc["defense", "round_win_pct"] == pytest.approx(100 * 8 / 15)


def test_buy_table(match_a):
    _, rdf = stats.build_frames([match_a], ME)
    bt = stats.buy_table(rdf).set_index("buy_type")
    assert list(bt.index) == ["pistol", "eco", "light", "full"]
    assert bt.loc["pistol", "rounds"] == 2 and bt.loc["eco", "kills_per_round"] == 2.0
    assert bt.loc["full", "rounds"] == 10


def test_retake_postplant(match_a):
    _, rdf = stats.build_frames([match_a], ME)
    rp = stats.retake_postplant(rdf)
    assert rp["retake_rounds"] == 1 and rp["retake_win_pct"] == 100.0
    assert rp["postplant_rounds"] == 3 and rp["postplant_win_pct"] == 100.0


def _fake_mdf(results, start="2026-11-01 12:00", gaps_min=None, length=40):
    rows, t = [], pd.Timestamp(start, tz="UTC")
    for i, res in enumerate(results):
        rows.append({"started_at": t, "game_length_min": length, "result": res, "won": res == "Win"})
        t = t + pd.Timedelta(minutes=length + (gaps_min[i] if gaps_min else 5))
    return pd.DataFrame(rows)


def test_tilt_flag():
    df = stats.add_tilt_and_sessions(_fake_mdf(["Loss", "Loss", "Win", "Loss", "Loss", "Loss", "Win"]))
    assert list(df["after_loss_streak"]) == [False, False, True, False, False, True, True]


def test_sessions_split_on_gap():
    df = stats.add_tilt_and_sessions(_fake_mdf(["Win"] * 5, gaps_min=[5, 5, 120, 5, 5]))
    assert list(df["session"]) == [1, 1, 1, 2, 2]
    assert list(df["session_game"]) == [1, 2, 3, 1, 2]


def test_rolling_trend():
    df = pd.DataFrame({
        "started_at": pd.date_range("2026-11-01", periods=6, freq="h", tz="UTC"),
        "game_no": range(1, 7),
        "combat_score": [2000] * 6, "rounds": [20] * 6, "damage": [3000] * 6,
        "headshots": [2, 2, 2, 2, 2, 8], "shots": [10] * 6,
        "kills": [10] * 6, "deaths": [10, 10, 10, 10, 10, 0],
        "won": [True, False, True, False, True, True],
    })
    tr = stats.rolling_trend(df, window=5)
    assert tr["acs_rolling"].isna().sum() == 4
    assert tr["acs_rolling"].iloc[4] == pytest.approx(100.0)
    assert tr["hs_pct_rolling"].iloc[5] == pytest.approx(100 * 16 / 50)
    assert tr["win_rate_rolling"].iloc[4] == pytest.approx(60.0)
    assert tr["kd_rolling"].iloc[5] == pytest.approx(50 / 40)


def test_roles():
    from roles import role_of
    assert role_of("KAY/O") == "Initiator" and role_of("miks") == "Controller"
    assert role_of("NewAgent") == "Unknown" and role_of(None) == "Unknown"
