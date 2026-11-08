"""Stat calculations for ONE player across HenrikDev v4 match objects.

Definitions (also shown in the UI):
- ACS   = player.stats.score / rounds played
- ADR   = player.stats.damage.dealt / rounds played
- HS%   = headshots / (headshots + bodyshots + legshots)
- First kill / first death = the earliest kill event of a round (by time_in_round_in_ms)
- KAST  = % of rounds with a Kill, Assist, Survived, or Traded.
          Traded: a teammate killed the player who killed me within 5 s of my death.
          A death followed by a Sage revive still counts as a death (the API has no revive event).
- Side  = not a field in the API. Derived from the competitive rule: Red attacks rounds 1-12,
          Blue attacks 13-24, overtime alternates starting with Red. Every spike plant is used to
          check the rule; if plants contradict it the sides are flipped and the match is flagged.
- Multi-kill = kills by me in one round (2K, 3K, 4K, 5K = ace).
- Clutch    = I became my team's last player alive with at least one enemy alive (1vX, X = enemies
          alive at that moment); won if my team then won the round. Alive state is rebuilt from kill
          events; a player who gets a kill after dying is treated as revived.
- Buy type (tool-defined thresholds, on MY loadout value at round start): pistol = rounds 1 and 13;
          eco < 2000; light 2000-3899; full >= 3900.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from api_client import tracker_match_url
from roles import role_of

KAST_TRADE_WINDOW_MS = 5000
HALF_LENGTH = 12
ECO_MAX = 2000
LIGHT_MAX = 3900
SESSION_GAP_MIN = 60
LOW_SAMPLE_GAMES = 5


# --------------------------------------------------------------------------- small helpers
def _pid(obj: Any) -> str | None:
    return (obj or {}).get("puuid") if isinstance(obj, dict) else None


def _team(obj: Any) -> str:
    return ((obj or {}).get("team") or "").lower() if isinstance(obj, dict) else ""


def safe_div(a: float, b: float) -> float | None:
    return float(a) / float(b) if b else None


def _sum_casts(casts: dict | None, keys: tuple[str, ...]) -> int | None:
    if not casts:
        return None
    vals = [casts.get(k) for k in keys]
    vals = [v for v in vals if v is not None]
    return int(sum(vals)) if vals else None


def find_player(match: dict, puuid: str) -> dict:
    for p in match.get("players") or []:
        if p.get("puuid") == puuid:
            return p
    raise KeyError(f"Player {puuid} not in match {match.get('metadata', {}).get('match_id')}")


def parse_time(s: str | None) -> pd.Timestamp | None:
    if not s:
        return None
    try:
        return pd.Timestamp(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        return None


# --------------------------------------------------------------------------- sides
def attacking_team(round_index: int) -> str:
    """Competitive rule; returns 'red' or 'blue'. round_index is 0-based."""
    if round_index < HALF_LENGTH:
        return "red"
    if round_index < 2 * HALF_LENGTH:
        return "blue"
    return "red" if (round_index - 2 * HALF_LENGTH) % 2 == 0 else "blue"


def infer_sides(match: dict) -> tuple[dict[int, str], str]:
    """Return ({round_index: attacking team ('red'/'blue')}, check_status).
    check_status: 'verified' (all plants agree), 'flipped' (plants say opposite),
    'conflict' (mixed), 'unverified' (no plants to check against)."""
    rounds = match.get("rounds") or []
    attackers = {i: attacking_team(i) for i in range(len(rounds))}
    agree = disagree = 0
    for i, r in enumerate(rounds):
        plant = r.get("plant")
        if plant and plant.get("player"):
            planter_team = _team(plant["player"])
            if not planter_team:
                continue
            if planter_team == attackers[i]:
                agree += 1
            else:
                disagree += 1
    if agree == 0 and disagree == 0:
        return attackers, "unverified"
    if disagree == 0:
        return attackers, "verified"
    if agree == 0:
        flipped = {i: ("blue" if t == "red" else "red") for i, t in attackers.items()}
        return flipped, "flipped"
    return attackers, "conflict"


# --------------------------------------------------------------------------- per round
def buy_type(round_index: int, loadout: float | None) -> str:
    if round_index in (0, HALF_LENGTH):
        return "pistol"
    if loadout is None:
        return "unknown"
    if loadout < ECO_MAX:
        return "eco"
    if loadout < LIGHT_MAX:
        return "light"
    return "full"


def clutch_situation(round_kills: list[dict], me: str, my_team_ids: set[str], enemy_ids: set[str]) -> int | None:
    """Number of enemies alive when `me` became the team's last player alive, else None.
    `round_kills` must be sorted by time."""
    alive_team, alive_enemy = set(my_team_ids), set(enemy_ids)
    for k in round_kills:
        killer, victim = _pid(k.get("killer")), _pid(k.get("victim"))
        # a dead player getting a kill must have been revived (e.g. Sage ult)
        if killer in my_team_ids:
            alive_team.add(killer)
        elif killer in enemy_ids:
            alive_enemy.add(killer)
        alive_team.discard(victim)
        alive_enemy.discard(victim)
        if alive_team == {me} and alive_enemy:
            return len(alive_enemy)
        if me not in alive_team:
            return None
    return None


def round_rows(match: dict, puuid: str) -> list[dict]:
    """One row per round for `puuid`."""
    me = find_player(match, puuid)
    my_team = (me.get("team_id") or "").lower()
    rounds = match.get("rounds") or []
    kills = match.get("kills") or []
    attackers, side_check = infer_sides(match)
    match_id = (match.get("metadata") or {}).get("match_id")
    team_ids = {p["puuid"] for p in match.get("players") or [] if (p.get("team_id") or "").lower() == my_team}
    enemy_ids = {p["puuid"] for p in match.get("players") or [] if p.get("puuid") and p["puuid"] not in team_ids}

    # rounds are referenced by `id` in kills[].round; map id -> list index
    id_to_idx = {r.get("id", i): i for i, r in enumerate(rounds)}
    kills_by_round: dict[int, list[dict]] = defaultdict(list)
    for k in kills:
        idx = id_to_idx.get(k.get("round"))
        if idx is not None:
            kills_by_round[idx].append(k)

    out = []
    for i, r in enumerate(rounds):
        rk = sorted(kills_by_round.get(i, []), key=lambda k: k.get("time_in_round_in_ms") or 0)
        my_kills = [k for k in rk if _pid(k.get("killer")) == puuid and _pid(k.get("victim")) != puuid
                    and _team(k.get("victim")) != my_team]
        my_death = next((k for k in rk if _pid(k.get("victim")) == puuid), None)
        assisted = any(puuid in [_pid(a) for a in (k.get("assistants") or [])]
                       and _team(k.get("victim")) != my_team for k in rk)
        first = rk[0] if rk else None
        first_kill = bool(first and _pid(first.get("killer")) == puuid and _pid(first.get("victim")) != puuid)
        first_death = bool(first and _pid(first.get("victim")) == puuid)

        traded = False
        if my_death is not None:
            killer = _pid(my_death.get("killer"))
            t0 = my_death.get("time_in_round_in_ms") or 0
            if killer and killer != puuid:
                for k in rk:
                    t = k.get("time_in_round_in_ms") or 0
                    if (_pid(k.get("victim")) == killer and _team(k.get("killer")) == my_team
                            and _pid(k.get("killer")) != puuid and 0 <= t - t0 <= KAST_TRADE_WINDOW_MS):
                        traded = True
                        break

        mine = next((s for s in (r.get("stats") or []) if _pid(s.get("player")) == puuid), {}) or {}
        econ = mine.get("economy") or {}
        loadout = econ.get("loadout_value")
        casts = _sum_casts(mine.get("ability_casts"), ("ability_1", "ability_2", "grenade", "ultimate"))
        damage = sum((d.get("damage") or 0) for d in (mine.get("damage_events") or [])) if mine else None
        score = (mine.get("stats") or {}).get("score") if mine else None

        plant, defuse = r.get("plant"), r.get("defuse")
        side = "attack" if attackers[i] == my_team else "defense"
        won = (r.get("winning_team") or "").lower() == my_team
        clutch_vs = clutch_situation(rk, puuid, team_ids, enemy_ids)
        out.append({
            "match_id": match_id,
            "round": i + 1,
            "side": side,
            "won": won,
            "kills": len(my_kills),
            "kill_weapons": [((k.get("weapon") or {}).get("name") or (k.get("weapon") or {}).get("type")
                              or "Ability / other") for k in my_kills],
            "clutch_vs": clutch_vs,
            "clutch_won": bool(clutch_vs) and won,
            "died": my_death is not None,
            "survived": my_death is None,
            "assisted": assisted,
            "traded": traded,
            "kast": bool(my_kills) or assisted or my_death is None or traded,
            "first_kill": first_kill,
            "first_death": first_death,
            "score": score,
            "damage": damage,
            "loadout": loadout,
            "buy_type": buy_type(i, loadout),
            "ability_casts": casts,
            "planted": bool(plant and _pid(plant.get("player")) == puuid),
            "defused": bool(defuse and _pid(defuse.get("player")) == puuid),
            "team_planted": bool(plant and _team(plant.get("player")) == my_team),
            "enemy_planted": bool(plant and _team(plant.get("player")) not in ("", my_team)),
            "side_check": side_check,
        })
    return out


# --------------------------------------------------------------------------- per match
def match_row(match: dict, puuid: str, rr_by_match: dict[str, int] | None = None) -> dict:
    meta = match.get("metadata") or {}
    me = find_player(match, puuid)
    st = me.get("stats") or {}
    my_team = (me.get("team_id") or "").lower()
    rounds = round_rows(match, puuid)

    teams = {(t.get("team_id") or "").lower(): t for t in (match.get("teams") or [])}
    mine_t = teams.get(my_team, {})
    other_t = next((t for k, t in teams.items() if k != my_team), {})
    my_rounds = (mine_t.get("rounds") or {}).get("won")
    enemy_rounds = (mine_t.get("rounds") or {}).get("lost")
    if enemy_rounds is None:
        enemy_rounds = (other_t.get("rounds") or {}).get("won")
    if mine_t.get("won"):
        result = "Win"
    elif other_t.get("won"):
        result = "Loss"
    else:
        result = "Draw"

    n_rounds = len(rounds) or ((my_rounds or 0) + (enemy_rounds or 0))
    kills, deaths, assists = st.get("kills", 0), st.get("deaths", 0), st.get("assists", 0)
    hs, bs, ls = st.get("headshots", 0), st.get("bodyshots", 0), st.get("legshots", 0)
    shots = hs + bs + ls
    damage = (st.get("damage") or {}).get("dealt", 0)
    score = st.get("score", 0)

    casts_total = _sum_casts(me.get("ability_casts"), ("ability1", "ability2", "grenade", "ultimate"))
    if casts_total is None:
        per_round = [r["ability_casts"] for r in rounds if r["ability_casts"] is not None]
        casts_total = int(sum(per_round)) if per_round else None

    loadouts = [r["loadout"] for r in rounds if r["loadout"] is not None]
    avg_loadout = ((me.get("economy") or {}).get("loadout_value") or {}).get("average")
    if avg_loadout is None and loadouts:
        avg_loadout = sum(loadouts) / len(loadouts)

    started = parse_time(meta.get("started_at"))
    length_ms = meta.get("game_length_in_ms")
    match_id = meta.get("match_id")
    agent = (me.get("agent") or {}).get("name")
    rr = (rr_by_match or {}).get(match_id)

    atk = [r for r in rounds if r["side"] == "attack"]
    dfn = [r for r in rounds if r["side"] == "defense"]
    return {
        "match_id": match_id,
        "started_at": started,
        "game_length_min": round(length_ms / 60000, 1) if length_ms else None,
        "map": (meta.get("map") or {}).get("name"),
        "agent": agent,
        "role": role_of(agent),
        "result": result,
        "won": result == "Win",
        "score": f"{my_rounds}-{enemy_rounds}" if my_rounds is not None else None,
        "team_rounds": my_rounds,
        "enemy_rounds": enemy_rounds,
        "rounds": n_rounds,
        "kills": kills, "deaths": deaths, "assists": assists,
        "kd": safe_div(kills, deaths) if deaths else float(kills),
        "combat_score": score,
        "acs": safe_div(score, n_rounds),
        "damage": damage,
        "adr": safe_div(damage, n_rounds),
        "headshots": hs, "bodyshots": bs, "legshots": ls, "shots": shots,
        "hs_pct": safe_div(100 * hs, shots),
        "leg_pct": safe_div(100 * ls, shots),
        "first_kills": sum(r["first_kill"] for r in rounds),
        "first_deaths": sum(r["first_death"] for r in rounds),
        "kast_rounds": sum(r["kast"] for r in rounds),
        "kast_pct": safe_div(100 * sum(r["kast"] for r in rounds), len(rounds)),
        "survived_rounds": sum(r["survived"] for r in rounds),
        "k2": sum(r["kills"] == 2 for r in rounds),
        "k3": sum(r["kills"] == 3 for r in rounds),
        "k4": sum(r["kills"] == 4 for r in rounds),
        "aces": sum(r["kills"] >= 5 for r in rounds),
        "clutch_attempts": sum(r["clutch_vs"] is not None for r in rounds),
        "clutches_won": sum(r["clutch_won"] for r in rounds),
        "plants": sum(r["planted"] for r in rounds),
        "defuses": sum(r["defused"] for r in rounds),
        "avg_loadout": avg_loadout,
        "ability_casts": casts_total,
        "casts_per_round": safe_div(casts_total, n_rounds) if casts_total is not None else None,
        "rr_change": rr,
        "attack_rounds": len(atk), "attack_won": sum(r["won"] for r in atk),
        "defense_rounds": len(dfn), "defense_won": sum(r["won"] for r in dfn),
        "side_check": rounds[0]["side_check"] if rounds else "unverified",
        "tracker_url": tracker_match_url(match_id) if match_id else None,
    }


def rr_lookup(mmr_history: list[dict]) -> dict[str, int]:
    return {e["match_id"]: e.get("last_change") for e in mmr_history or [] if e.get("match_id")}


def build_frames(matches: list[dict], puuid: str, mmr_history: list[dict] | None = None,
                 agent_filter: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (per-match df sorted oldest->newest, per-round df). Adds tilt/session columns."""
    rr = rr_lookup(mmr_history or [])
    mrows, rrows = [], []
    for m in matches:
        try:
            row = match_row(m, puuid, rr)
        except KeyError:
            continue
        if agent_filter and row["agent"] != agent_filter:
            continue
        mrows.append(row)
        for r in round_rows(m, puuid):
            r.update({"agent": row["agent"], "map": row["map"], "role": row["role"]})
            rrows.append(r)
    mdf = pd.DataFrame(mrows)
    rdf = pd.DataFrame(rrows)
    if mdf.empty:
        return mdf, rdf
    mdf = mdf.sort_values("started_at", kind="stable").reset_index(drop=True)
    mdf["game_no"] = np.arange(1, len(mdf) + 1)
    mdf = add_tilt_and_sessions(mdf)
    return mdf, rdf


def add_tilt_and_sessions(mdf: pd.DataFrame) -> pd.DataFrame:
    """after_loss_streak: the game was played right after 2+ consecutive losses.
    session: new session when the gap between the previous game's end and this game's start
    exceeds SESSION_GAP_MIN minutes. session_game: 1-based index inside the session."""
    mdf = mdf.copy()
    streak = 0
    after = []
    for won, result in zip(mdf["won"], mdf["result"]):
        after.append(streak >= 2)
        streak = streak + 1 if result == "Loss" else 0
    mdf["after_loss_streak"] = after

    sessions, idx_in, sid, n = [], [], 0, 0
    prev_end = None
    for start, length in zip(mdf["started_at"], mdf["game_length_min"]):
        if start is None or pd.isna(start):
            sessions.append(None)
            idx_in.append(None)
            continue
        if prev_end is None or (start - prev_end).total_seconds() / 60 > SESSION_GAP_MIN:
            sid += 1
            n = 0
        n += 1
        sessions.append(sid)
        idx_in.append(n)
        prev_end = start + pd.Timedelta(minutes=float(length or 0))
    mdf["session"] = sessions
    mdf["session_game"] = idx_in
    return mdf


# --------------------------------------------------------------------------- aggregates
def summarize(mdf: pd.DataFrame) -> dict:
    """Round-weighted totals (not an average of per-game averages)."""
    if mdf.empty:
        return {"games": 0}
    rounds = mdf["rounds"].sum()
    casts_known = mdf.dropna(subset=["ability_casts"])
    return {
        "games": int(len(mdf)),
        "wins": int(mdf["won"].sum()),
        "win_rate": 100 * mdf["won"].mean(),
        "rounds": int(rounds),
        "kd": safe_div(mdf["kills"].sum(), mdf["deaths"].sum()),
        "kills_per_round": safe_div(mdf["kills"].sum(), rounds),
        "assists_per_round": safe_div(mdf["assists"].sum(), rounds),
        "acs": safe_div(mdf["combat_score"].sum(), rounds),
        "adr": safe_div(mdf["damage"].sum(), rounds),
        "hs_pct": safe_div(100 * mdf["headshots"].sum(), mdf["shots"].sum()),
        "leg_pct": safe_div(100 * mdf["legshots"].sum(), mdf["shots"].sum()),
        "fk_per_round": safe_div(mdf["first_kills"].sum(), rounds),
        "fd_per_round": safe_div(mdf["first_deaths"].sum(), rounds),
        "fd_pct": safe_div(100 * mdf["first_deaths"].sum(), rounds),
        "entry_success_pct": safe_div(100 * mdf["first_kills"].sum(),
                                      mdf["first_kills"].sum() + mdf["first_deaths"].sum()),
        "kast_pct": safe_div(100 * mdf["kast_rounds"].sum(), rounds),
        "survival_pct": safe_div(100 * mdf["survived_rounds"].sum(), rounds),
        "casts_per_round": (safe_div(casts_known["ability_casts"].sum(), casts_known["rounds"].sum())
                            if not casts_known.empty else None),
        "plants": int(mdf["plants"].sum()),
        "defuses": int(mdf["defuses"].sum()),
        "multikills": int(mdf[["k3", "k4", "aces"]].sum().sum()) if "k3" in mdf else 0,
        "aces": int(mdf["aces"].sum()) if "aces" in mdf else 0,
        "clutches_won": int(mdf["clutches_won"].sum()) if "clutches_won" in mdf else 0,
        "clutch_attempts": int(mdf["clutch_attempts"].sum()) if "clutch_attempts" in mdf else 0,
        "avg_loadout": mdf["avg_loadout"].mean() if mdf["avg_loadout"].notna().any() else None,
        "rr_total": int(mdf["rr_change"].dropna().sum()) if mdf["rr_change"].notna().any() else None,
    }


TABLE_COLS = ["games", "wins", "win_rate", "low_sample", "kd", "acs", "adr", "hs_pct",
              "kast_pct", "fk_per_round", "fd_per_round", "entry_success_pct",
              "assists_per_round", "casts_per_round", "survival_pct", "rr_total"]


def group_table(mdf: pd.DataFrame, key: str) -> pd.DataFrame:
    if mdf.empty:
        return pd.DataFrame(columns=[key] + TABLE_COLS)
    rows = []
    for val, g in mdf.groupby(key, dropna=False):
        s = summarize(g)
        s[key] = val
        s["low_sample"] = s["games"] < LOW_SAMPLE_GAMES
        rows.append(s)
    out = pd.DataFrame(rows)
    return out[[key] + TABLE_COLS].sort_values("games", ascending=False).reset_index(drop=True)


def side_table(rdf: pd.DataFrame) -> pd.DataFrame:
    if rdf.empty:
        return pd.DataFrame()
    rows = []
    for side, g in rdf.groupby("side"):
        n = len(g)
        rows.append({
            "side": side, "rounds": n,
            "round_win_pct": 100 * g["won"].mean(),
            "kast_pct": 100 * g["kast"].mean(),
            "kills_per_round": g["kills"].mean(),
            "survival_pct": 100 * g["survived"].mean(),
            "fk_pct": 100 * g["first_kill"].mean(),
            "fd_pct": 100 * g["first_death"].mean(),
            "acs": g["score"].dropna().mean() if g["score"].notna().any() else None,
            "adr": g["damage"].dropna().mean() if g["damage"].notna().any() else None,
        })
    return pd.DataFrame(rows)


def buy_table(rdf: pd.DataFrame) -> pd.DataFrame:
    if rdf.empty:
        return pd.DataFrame()
    order = ["pistol", "eco", "light", "full", "unknown"]
    rows = []
    for bt, g in rdf.groupby("buy_type"):
        rows.append({"buy_type": bt, "rounds": len(g),
                     "round_win_pct": 100 * g["won"].mean(),
                     "kills_per_round": g["kills"].mean(),
                     "kast_pct": 100 * g["kast"].mean(),
                     "adr": g["damage"].dropna().mean() if g["damage"].notna().any() else None})
    out = pd.DataFrame(rows)
    out["_o"] = out["buy_type"].map({b: i for i, b in enumerate(order)})
    return out.sort_values("_o").drop(columns="_o").reset_index(drop=True)


def rolling_trend(mdf: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Rolling `window`-game values, round-weighted inside the window."""
    if mdf.empty:
        return pd.DataFrame()
    m = mdf.sort_values("started_at", kind="stable").reset_index(drop=True)
    r = lambda col: m[col].rolling(window, min_periods=window).sum()
    out = pd.DataFrame({
        "game_no": m["game_no"] if "game_no" in m else np.arange(1, len(m) + 1),
        "started_at": m["started_at"],
        "acs_rolling": r("combat_score") / r("rounds"),
        "adr_rolling": r("damage") / r("rounds"),
        "hs_pct_rolling": 100 * r("headshots") / r("shots"),
        "kd_rolling": r("kills") / r("deaths").replace(0, np.nan),
        "win_rate_rolling": 100 * m["won"].astype(float).rolling(window, min_periods=window).mean(),
    })
    return out


def side_by_group(rdf: pd.DataFrame, key: str) -> pd.DataFrame:
    """Round win % per side for each value of `key` (e.g. map)."""
    if rdf.empty:
        return pd.DataFrame()
    g = rdf.groupby([key, "side"])["won"].agg(["mean", "size"]).reset_index()
    g["round_win_pct"] = 100 * g["mean"]
    return g.drop(columns="mean").rename(columns={"size": "rounds"})


def retake_postplant(rdf: pd.DataFrame) -> dict:
    """Retake = defense rounds where the enemy planted; post-plant = attack rounds where my team planted."""
    if rdf.empty:
        return {}
    ret = rdf[(rdf["side"] == "defense") & rdf["enemy_planted"]]
    post = rdf[(rdf["side"] == "attack") & rdf["team_planted"]]
    return {
        "retake_rounds": len(ret), "retake_win_pct": 100 * ret["won"].mean() if len(ret) else None,
        "postplant_rounds": len(post), "postplant_win_pct": 100 * post["won"].mean() if len(post) else None,
    }


def weapon_table(rdf: pd.DataFrame) -> pd.DataFrame:
    """Kills by weapon (from kill events). HS% per weapon is NOT available in the API data."""
    if rdf.empty or "kill_weapons" not in rdf:
        return pd.DataFrame(columns=["weapon", "kills", "share_pct"])
    w = rdf["kill_weapons"].explode().dropna()
    if w.empty:
        return pd.DataFrame(columns=["weapon", "kills", "share_pct"])
    t = w.value_counts().rename_axis("weapon").reset_index(name="kills")
    t["share_pct"] = 100 * t["kills"] / t["kills"].sum()
    return t


def clutch_table(rdf: pd.DataFrame) -> pd.DataFrame:
    """Clutch attempts and wins by situation (1v1 ... 1v5)."""
    if rdf.empty or "clutch_vs" not in rdf:
        return pd.DataFrame(columns=["situation", "attempts", "won", "win_pct"])
    c = rdf.dropna(subset=["clutch_vs"])
    if c.empty:
        return pd.DataFrame(columns=["situation", "attempts", "won", "win_pct"])
    g = c.groupby("clutch_vs").agg(attempts=("won", "size"), won=("clutch_won", "sum")).reset_index()
    g["situation"] = g["clutch_vs"].astype(int).map(lambda n: f"1v{n}")
    g["win_pct"] = 100 * g["won"] / g["attempts"]
    return g[["situation", "attempts", "won", "win_pct"]]


def recent_form(mdf: pd.DataFrame, n: int = 10) -> list[str]:
    """Results of the last n games, oldest -> newest ('Win'/'Loss'/'Draw')."""
    if mdf.empty:
        return []
    return list(mdf.sort_values("started_at", kind="stable")["result"].tail(n))
