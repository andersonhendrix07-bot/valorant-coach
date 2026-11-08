"""Generates the synthetic fixture JSON files used by the tests.

The fixtures follow the documented HenrikDev v4 match schema (GET /valorant/v4/match/{affinity}/{match_id})
but every event is hand-designed so the expected stats can be worked out on paper (see the round
tables in test_stats.py). Re-run with:  python tests/fixtures/make_fixtures.py
To add a REAL match as a fixture, use scripts/save_fixture.py instead.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
ME = {"puuid": "me-puuid", "name": "Hendrix", "tag": "NA1"}


def rp(puuid, team):
    name = "Hendrix" if puuid == "me-puuid" else puuid
    tag = "NA1" if puuid == "me-puuid" else "0000"
    return {"puuid": puuid, "name": name, "tag": tag, "team": team}


def player(puuid, team, agent, stats, casts=None, avg_loadout=3000.0):
    return {
        "puuid": puuid, "name": rp(puuid, team)["name"], "tag": rp(puuid, team)["tag"],
        "team_id": team, "platform": "pc", "party_id": "p-" + puuid,
        "agent": {"id": "agent-" + agent.lower(), "name": agent},
        "stats": stats,
        "ability_casts": casts or {"ability1": None, "ability2": None, "grenade": None, "ultimate": None},
        "economy": {"spent": {"overall": 0, "average": 0.0},
                    "loadout_value": {"overall": 0, "average": avg_loadout}},
        "behavior": {"afk_rounds": 0, "rounds_in_spawn": 0, "friendly_fire": {"incoming": 0, "outgoing": 0}},
        "tier": {"id": 15, "name": "Gold 1"},
        "customization": {"card": "c", "title": "t", "preferred_level_border": None},
        "account_level": 100, "session_playtime_in_ms": 0,
    }


def filler_stats():
    return {"score": 3000, "kills": 10, "deaths": 10, "assists": 3, "headshots": 5, "bodyshots": 20,
            "legshots": 2, "damage": {"dealt": 2000, "received": 2000}}


def round_obj(i, winner, my_team, my_loadout, my_score, my_damage, my_casts=None,
              plant=None, defuse=None):
    """plant/defuse: (puuid, team) or None."""
    stats = [{
        "player": rp("me-puuid", my_team),
        "ability_casts": my_casts or {"ability_1": None, "ability_2": None, "grenade": None, "ultimate": None},
        "damage_events": ([{"player": rp("enemy", "X"), "bodyshots": 1, "headshots": 0, "legshots": 0,
                            "damage": my_damage}] if my_damage else []),
        "stats": {"score": my_score, "kills": 0, "headshots": 0, "bodyshots": 0, "legshots": 0},
        "economy": {"loadout_value": my_loadout, "remaining": 0, "armor": None, "weapon": None},
        "was_afk": False, "received_penalty": False, "stayed_in_spawn": False,
    }]
    r = {"id": i, "result": "Elimination", "ceremony": "CeremonyDefault", "winning_team": winner,
         "plant": None, "defuse": None, "stats": stats}
    if plant:
        r["plant"] = {"round_time_in_ms": 40000, "site": "A", "location": {"x": 0, "y": 0},
                      "player": rp(*plant), "player_locations": []}
    if defuse:
        r["defuse"] = {"round_time_in_ms": 80000, "location": {"x": 0, "y": 0},
                       "player": rp(*defuse), "player_locations": []}
    return r


def kill(rnd, t, killer, ktm, victim, vtm, assistants=()):
    return {"time_in_round_in_ms": t, "time_in_match_in_ms": rnd * 100000 + t, "round": rnd,
            "killer": rp(killer, ktm), "victim": rp(victim, vtm),
            "assistants": [rp(a, at) for a, at in assistants],
            "location": {"x": 0, "y": 0}, "weapon": {"id": "w", "name": "Vandal", "type": "Weapon"},
            "secondary_fire_mode": False, "player_locations": []}


def meta(match_id, map_name, started, length_min):
    return {"match_id": match_id, "map": {"id": "m", "name": map_name}, "game_version": "release-12.10",
            "game_length_in_ms": length_min * 60000, "started_at": started, "is_completed": True,
            "queue": {"id": "competitive", "mode_type": "Standard", "name": "Competitive"},
            "season": {"id": "s", "short": "e12a3"}, "platform": "pc", "party_rr_penaltys": [],
            "cluster": "Chicago", "region": "na", "premier": None}


# --------------------------------------------------------------------------- match A
def match_a():
    R, B = "Red", "Blue"
    rounds, kills = [], []
    # R0 pistol, attack: I get first kill, die, get traded 2 s later; Red plants
    rounds.append(round_obj(0, R, R, 800, 250, 150, {"ability_1": 1, "ability_2": 0, "grenade": 1, "ultimate": 0},
                            plant=("r3", R)))
    kills += [kill(0, 10000, "me-puuid", R, "b1", B), kill(0, 15000, "b2", B, "me-puuid", R),
              kill(0, 17000, "r2", R, "b2", B)]
    # R1 eco (1500): teammate dies first, I get 2 kills, I plant, survive
    rounds.append(round_obj(1, R, R, 1500, 400, 300, plant=("me-puuid", R)))
    kills += [kill(1, 5000, "b1", B, "r2", R), kill(1, 8000, "me-puuid", R, "b1", B),
              kill(1, 9000, "me-puuid", R, "b3", B, [("r3", R)])]
    # R2 full (4500): first death, NOT traded (7 s later) -> no KAST; Blue wins
    rounds.append(round_obj(2, B, R, 4500, 0, 50))
    kills += [kill(2, 3000, "b1", B, "me-puuid", R), kill(2, 10000, "r2", R, "b1", B)]
    # R3 full (4700): assist, then die, trade comes 6 s later (outside 5 s) -> KAST via assist
    rounds.append(round_obj(3, R, R, 4700, 60, 80))
    kills += [kill(3, 4000, "r2", R, "b1", B, [("me-puuid", R)]), kill(3, 6000, "b2", B, "me-puuid", R),
              kill(3, 12000, "r3", R, "b2", B)]
    # R4..R11: filler, I survive. R4 loadout 3899 (light, boundary), R5-11 3900 (full, boundary). R4 Red plant.
    for i in range(4, 12):
        rounds.append(round_obj(i, R, R, 3899 if i == 4 else 3900, 100, 100,
                                plant=("r3", R) if i == 4 else None))
        kills.append(kill(i, 5000, "r2", R, "b1", B))
    # R12 pistol, defense: Blue plants, I get first kill and defuse
    rounds.append(round_obj(12, R, R, 800, 300, 200, plant=("b1", B), defuse=("me-puuid", R)))
    kills.append(kill(12, 20000, "me-puuid", R, "b1", B))
    # R13 full (4000), defense: teammate dies first, I trade him, I die, I'm traded 4 s later
    rounds.append(round_obj(13, R, R, 4000, 200, 250))
    kills += [kill(13, 2000, "b3", B, "r4", R), kill(13, 2500, "me-puuid", R, "b3", B),
              kill(13, 4000, "b4", B, "me-puuid", R), kill(13, 8000, "r5", R, "b4", B)]

    my_stats = {"score": 2010, "kills": 5, "deaths": 4, "assists": 1, "headshots": 6, "bodyshots": 10,
                "legshots": 4, "damage": {"dealt": 1830, "received": 600}}
    players = [player("me-puuid", R, "Jett", my_stats,
                      {"ability1": 5, "ability2": 4, "grenade": 6, "ultimate": 1}, avg_loadout=3500.0)]
    players += [player(p, R, "Sova", filler_stats()) for p in ("r2", "r3", "r4", "r5")]
    players += [player(p, B, "Omen", filler_stats()) for p in ("b1", "b2", "b3", "b4", "b5")]
    return {"metadata": meta("aaaaaaaa-0000-0000-0000-000000000001", "Ascent", "2026-11-01T18:00:00.000Z", 35),
            "players": players, "observers": [], "coaches": [],
            "teams": [{"team_id": R, "rounds": {"won": 13, "lost": 1}, "won": True, "premier_roster": None},
                      {"team_id": B, "rounds": {"won": 1, "lost": 13}, "won": False, "premier_roster": None}],
            "rounds": rounds, "kills": kills}


# --------------------------------------------------------------------------- match B
def match_b():
    """Me on Blue, Sova, 26 rounds with overtime, 12-14 loss. I win rounds 0-5 and 12-17.
    Every round has exactly one kill: me killing r1 (rounds I win) or r1 killing me (rounds I lose).
    Player-level ability casts are null -> must fall back to per-round casts (1 per round)."""
    R, B = "Red", "Blue"
    rounds, kills = [], []
    my_wins = set(range(0, 6)) | set(range(12, 18))
    for i in range(26):
        won = i in my_wins
        # attacker plants every round so the side check has data
        if i < 12:
            atk = R
        elif i < 24:
            atk = B
        else:
            atk = R if (i - 24) % 2 == 0 else B
        planter = ("me-puuid", B) if atk == B else ("r1", R)
        rounds.append(round_obj(i, B if won else R, B, 3900, 200, 100,
                                {"ability_1": 1, "ability_2": 0, "grenade": 0, "ultimate": 0}, plant=planter))
        kills.append(kill(i, 5000, "me-puuid", B, "r1", R) if won else kill(i, 3000, "r1", R, "me-puuid", B))
    my_stats = {"score": 5200, "kills": 12, "deaths": 14, "assists": 0, "headshots": 3, "bodyshots": 7,
                "legshots": 0, "damage": {"dealt": 2600, "received": 2800}}
    players = [player("me-puuid", B, "Sova", my_stats, None, avg_loadout=3900.0)]
    players += [player(p, B, "Omen", filler_stats()) for p in ("b2", "b3", "b4", "b5")]
    players += [player(p, R, "Jett", filler_stats()) for p in ("r1", "r2", "r3", "r4", "r5")]
    return {"metadata": meta("bbbbbbbb-0000-0000-0000-000000000002", "Bind", "2026-11-01T18:45:00.000Z", 50),
            "players": players, "observers": [], "coaches": [],
            "teams": [{"team_id": R, "rounds": {"won": 14, "lost": 12}, "won": True, "premier_roster": None},
                      {"team_id": B, "rounds": {"won": 12, "lost": 14}, "won": False, "premier_roster": None}],
            "rounds": rounds, "kills": kills}


def mmr_history():
    return [
        {"match_id": "bbbbbbbb-0000-0000-0000-000000000002", "tier": {"id": 15, "name": "Gold 1"},
         "map": {"id": "m", "name": "Bind"}, "season": {"id": "s", "short": "e12a3"}, "rr": 40,
         "last_change": -18, "elo": 1240, "refunded_rr": 0, "was_derank_protected": False,
         "date": "2026-11-01T19:40:00.000Z"},
        {"match_id": "aaaaaaaa-0000-0000-0000-000000000001", "tier": {"id": 15, "name": "Gold 1"},
         "map": {"id": "m", "name": "Ascent"}, "season": {"id": "s", "short": "e12a3"}, "rr": 58,
         "last_change": 21, "elo": 1258, "refunded_rr": 0, "was_derank_protected": False,
         "date": "2026-11-01T18:40:00.000Z"},
    ]


if __name__ == "__main__":
    for name, obj in (("match_a_win_jett.json", match_a()), ("match_b_loss_sova_ot.json", match_b()),
                      ("mmr_history.json", mmr_history())):
        (HERE / name).write_text(json.dumps(obj, indent=1))
        print("wrote", name)
