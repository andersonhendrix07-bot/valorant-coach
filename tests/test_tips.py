import math

import pandas as pd
import pytest

import stats
import tips
from conftest import ME


def game(agent, won, *, rounds=20, kills=15, deaths=15, assists=4, score=4000, damage=2800,
         hs=20, body=70, legs=10, fk=2, fd=2, kast=14, survived=6, casts=None, t=0, map_="Ascent"):
    return {
        "started_at": pd.Timestamp("2026-11-01", tz="UTC") + pd.Timedelta(hours=t * 3),
        "game_length_min": 40, "map": map_, "agent": agent, "role": stats.role_of(agent) if hasattr(stats, "role_of") else None,
        "result": "Win" if won else "Loss", "won": won, "rounds": rounds,
        "kills": kills, "deaths": deaths, "assists": assists, "combat_score": score, "damage": damage,
        "headshots": hs, "bodyshots": body, "legshots": legs, "shots": hs + body + legs,
        "first_kills": fk, "first_deaths": fd, "kast_rounds": kast, "survived_rounds": survived,
        "plants": 0, "defuses": 0, "avg_loadout": 3500.0, "ability_casts": casts, "rr_change": None,
    }


def frame(games):
    from roles import role_of
    df = pd.DataFrame(games)
    df["role"] = df["agent"].map(role_of)
    df = df.sort_values("started_at").reset_index(drop=True)
    df["game_no"] = range(1, len(df) + 1)
    return stats.add_tilt_and_sessions(df)


def test_rel_gap_and_impact_formula():
    assert tips.rel_gap(22, 11, 5) == pytest.approx(1.0)
    assert tips.rel_gap(1, 0, 5) == pytest.approx(0.2)   # floor prevents divide-by-zero blow-ups
    assert tips.rel_gap(None, 3, 1) is None
    t = tips.Tip("X", "t", "d", "i", "p", 22, 11, 1.0, 9)
    assert t.impact == pytest.approx(3.0) and not t.low_sample
    assert tips.Tip("X", "t", "d", "i", "p", 1, 1, 0.5, 4).low_sample


def test_duelist_first_death_tip_cites_numbers():
    games = [game("Jett", False, fd=5, fk=2, t=i) for i in range(5)]           # FD 25% of rounds
    games += [game("Sova", True, fd=2, fk=2, t=10 + i) for i in range(5)]     # FD 10%
    mdf = frame(games)
    found = [t for t in tips.generate_tips(mdf, pd.DataFrame()) if t.title == "Jett: too many first deaths"]
    assert found, "expected a first-death tip"
    t = found[0]
    assert "25%" in t.data_shows and "10%" in t.data_shows
    assert t.value == pytest.approx(25.0) and t.baseline == pytest.approx(10.0)
    assert t.rel_gap == pytest.approx(1.5) and t.sample == 5
    assert t.impact == pytest.approx(1.5 * math.sqrt(5), abs=1e-3)   # stored rounded to 3 dp


def test_entry_success_falls_back_to_break_even_when_no_other_agents():
    mdf = frame([game("Reyna", i % 2 == 0, fk=1, fd=4, t=i) for i in range(4)])   # 20% entry success
    t = next(t for t in tips.generate_tips(mdf, pd.DataFrame()) if "entry duels" in t.title)
    assert "50% break-even" in t.data_shows
    assert t.value == pytest.approx(20.0) and t.low_sample


def test_worst_and_best_agent():
    games = [game("Jett", False, t=i) for i in range(4)] + [game("Jett", True, t=4)]
    games += [game("Omen", True, t=10 + i) for i in range(4)] + [game("Omen", False, t=14)]
    out = tips.tips_agents_maps(frame(games))
    titles = {t.title for t in out}
    assert "Weakest agent: Jett" in titles and "Strongest agent: Omen" in titles
    worst = next(t for t in out if t.title == "Weakest agent: Jett")
    assert worst.value == pytest.approx(20.0) and worst.baseline == pytest.approx(80.0)


def test_no_tip_when_gap_small():
    games = [game("Jett", i % 2 == 0, t=i) for i in range(6)] + [game("Omen", i % 2 == 0, t=10 + i) for i in range(6)]
    out = tips.tips_agents_maps(frame(games))
    assert out == []


def test_tilt_tip():
    seq = [False, False, False, False, True, False, False, False, True, True, True, True]
    score = []
    games = []
    streak = 0
    for i, won in enumerate(seq):
        tilted = streak >= 2
        games.append(game("Jett", won, score=2400 if tilted else 4000, t=i))
        streak = 0 if won else streak + 1
    mdf = frame(games)
    assert mdf["after_loss_streak"].sum() >= 2
    out = tips.tips_tilt(mdf)
    assert out and "after 2+ straight losses" in out[0].data_shows


def test_hs_trend_tip():
    games = [game("Jett", True, hs=25, body=65, legs=10, t=i) for i in range(5)]
    games += [game("Jett", True, hs=12, body=78, legs=10, t=5 + i) for i in range(5)]
    out = tips.tips_aim(frame(games))
    t = next(t for t in out if t.title == "Headshot % is trending down")
    assert t.value == pytest.approx(12.0) and t.baseline == pytest.approx(25.0)


def test_initiator_util_wins_vs_losses():
    games = [game("Sova", True, casts=40, assists=8, t=i) for i in range(3)]
    games += [game("Sova", False, casts=20, assists=3, t=5 + i) for i in range(3)]
    out = tips.tips_roles(frame(games), pd.DataFrame())
    titles = [t.title for t in out]
    assert "Sova: ability casts per round drops in losses" in titles
    assert "Sova: assists per round drops in losses" in titles
    t = next(t for t in out if "ability casts" in t.title)
    assert "1.00 in losses" in t.data_shows and "2.00 in wins" in t.data_shows


def test_side_tip_from_rounds(match_a, match_b):
    mdf, rdf = stats.build_frames([match_a, match_b], ME)
    out = tips.tips_sides(mdf, rdf)
    assert out and out[0].title == "Weaker on defense"
    assert "53%" in out[0].data_shows and "68%" in out[0].data_shows


def test_generate_sorted_by_impact(match_a, match_b):
    games = [game("Jett", False, fd=5, t=i) for i in range(6)] + [game("Omen", True, fd=1, t=10 + i) for i in range(6)]
    out = tips.generate_tips(frame(games), pd.DataFrame())
    assert len(out) >= 2
    assert [t.impact for t in out] == sorted([t.impact for t in out], reverse=True)


def test_empty_input():
    assert tips.generate_tips(pd.DataFrame(), pd.DataFrame()) == []
