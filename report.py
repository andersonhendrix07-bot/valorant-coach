"""CSV and Markdown exports."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from api_client import tracker_profile_url
from stats import (KAST_TRADE_WINDOW_MS, LOW_SAMPLE_GAMES, group_table, side_table, buy_table,
                   summarize, ECO_MAX, LIGHT_MAX)
from tips import Tip

CSV_COLS = ["started_at", "match_id", "map", "agent", "role", "result", "score", "rounds",
            "kills", "deaths", "assists", "kd", "acs", "adr", "hs_pct", "first_kills", "first_deaths",
            "kast_pct", "k2", "k3", "k4", "aces", "clutch_attempts", "clutches_won", "plants", "defuses", "avg_loadout", "casts_per_round", "rr_change",
            "attack_rounds", "attack_won", "defense_rounds", "defense_won", "side_check",
            "after_loss_streak", "session", "session_game", "tracker_url"]


def matches_csv(mdf: pd.DataFrame) -> str:
    cols = [c for c in CSV_COLS if c in mdf.columns]
    out = mdf[cols].copy()
    num = out.select_dtypes("number").columns
    out[num] = out[num].round(2)
    return out.to_csv(index=False)


def _v(x, nd=1, unit=""):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    if isinstance(x, (int,)) and not isinstance(x, bool):
        return f"{x}{unit}"
    return f"{x:.{nd}f}{unit}"


def _md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No data._\n"
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].map(lambda x: "n/a" if pd.isna(x) else f"{x:.0f}" if float(x).is_integer() or abs(x) >= 10
                              else f"{x:.2f}")
    header = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "| " + " | ".join("---" for _ in df.columns) + " |"
    rows = ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join([header, sep, *rows]) + "\n"


def tip_md(i: int, t: Tip) -> str:
    flag = " _(low sample)_" if t.low_sample else ""
    return (f"### {i}. [{t.category}] {t.title}{flag}\n"
            f"- **What the data shows:** {t.data_shows}\n"
            f"- **What it likely means (interpretation):** {t.interpretation}\n"
            f"- **Practice next session:** {t.practice}\n"
            f"- _Impact {t.impact:.2f} = gap {t.rel_gap:.0%} × √{t.sample} games_\n")


def markdown_report(riot_id: str, region: str, mmr: dict | None, mdf: pd.DataFrame,
                    rdf: pd.DataFrame, tips: list[Tip], agent_filter: str | None = None) -> str:
    s = summarize(mdf)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cur = (mmr or {}).get("current") or {}
    rank = f"{(cur.get('tier') or {}).get('name', 'Unknown')} — {cur.get('rr', 'n/a')} RR" if cur else "Unavailable"
    lines = [
        f"# VALORANT improvement report — {riot_id}",
        f"_Generated {now} · region {region} · {s.get('games', 0)} competitive matches"
        + (f" · agent filter: {agent_filter}" if agent_filter else "") + "_",
        "",
        f"- Current rank: **{rank}**",
        f"- Tracker.gg profile (cross-check): {tracker_profile_url(riot_id)}",
        "",
        "## Overall",
    ]
    if s.get("games"):
        lines += [
            f"- Record: {s['wins']}-{s['games'] - s['wins']} ({_v(s['win_rate'], 0, '%')}), "
            f"RR net {_v(s['rr_total'])}",
            f"- K/D {_v(s['kd'], 2)} · ACS {_v(s['acs'], 0)} · ADR {_v(s['adr'], 0)} · HS% {_v(s['hs_pct'])} · "
            f"KAST {_v(s['kast_pct'], 0, '%')}",
            f"- First kills/round {_v(s['fk_per_round'], 2)} · first deaths/round {_v(s['fd_per_round'], 2)} · "
            f"ability casts/round {_v(s['casts_per_round'], 2)}",
            f"- Clutches won {s.get('clutches_won', 0)}/{s.get('clutch_attempts', 0)} · 3K+ rounds "
            f"{s.get('multikills', 0)} · aces {s.get('aces', 0)}",
            "",
        ]
    lines += ["## Top tips", ""]
    if tips:
        for i, t in enumerate(tips[:5], 1):
            lines.append(tip_md(i, t))
        if len(tips) > 5:
            lines += ["## More tips", ""]
            for i, t in enumerate(tips[5:], 6):
                lines.append(tip_md(i, t))
    else:
        lines.append("_No gaps large enough to trigger a tip yet. Play more games or widen the match count._\n")

    lines += ["## Agents", _md_table(group_table(mdf, "agent")[["agent", "games", "win_rate", "low_sample",
                                                                  "kd", "acs", "adr", "hs_pct", "kast_pct"]]),
              "## Maps", _md_table(group_table(mdf, "map")[["map", "games", "win_rate", "low_sample",
                                                              "kd", "acs", "adr", "kast_pct"]]),
              "## Sides", _md_table(side_table(rdf)),
              "## Buy rounds", _md_table(buy_table(rdf)),
              "## Definitions",
              f"- KAST: round with a kill, assist, survival, or trade. **Traded** = a teammate killed the "
              f"player who killed you within {KAST_TRADE_WINDOW_MS // 1000} seconds of your death.",
              "- Sides are derived (Red attacks first half; sides swap at round 13; overtime alternates) and "
              "checked against spike plants per match.",
              f"- Buy types (tool-defined, your own loadout value): pistol = rounds 1 and 13, eco < {ECO_MAX}, "
              f"light < {LIGHT_MAX}, full ≥ {LIGHT_MAX}.",
              f"- 'Low sample' = fewer than {LOW_SAMPLE_GAMES} games.",
              "- Tips compare you against your own baselines only; no rank benchmarks are used.",
              ""]
    return "\n".join(lines)
