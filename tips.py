"""Rule-based, transparent tips. Every tip compares you against YOUR OWN baseline
(other agents, other maps, earlier games, the other side). No rank benchmarks are used.

Impact score (used for ranking):
    relative_gap = |value - baseline| / max(|baseline|, floor)
    sample       = number of games in the SMALLER of the two groups being compared
    impact       = relative_gap * sqrt(sample)
A tip fires only when relative_gap >= MIN_REL_GAP and both groups have >= MIN_GAMES games.
Tips where the smaller group has < 5 games are labelled "low sample".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import pandas as pd

from stats import LOW_SAMPLE_GAMES, summarize, safe_div

MIN_REL_GAP = 0.15
MIN_GAMES = 2
TREND_WINDOW = 5
ENTRY_BREAK_EVEN = 50.0  # 50% = you win as many opening duels as you lose (math, not a benchmark)


@dataclass
class Tip:
    category: str
    title: str
    data_shows: str
    interpretation: str
    practice: str
    value: float
    baseline: float
    rel_gap: float
    sample: int
    impact: float = field(init=False)
    low_sample: bool = field(init=False)

    def __post_init__(self):
        self.impact = round(self.rel_gap * math.sqrt(max(self.sample, 0)), 3)
        self.low_sample = self.sample < LOW_SAMPLE_GAMES

    def as_dict(self) -> dict:
        return asdict(self)


def rel_gap(value: float | None, baseline: float | None, floor: float) -> float | None:
    if value is None or baseline is None or pd.isna(value) or pd.isna(baseline):
        return None
    return abs(value - baseline) / max(abs(baseline), floor)


def _fmt(v: float | None, unit: str = "", nd: int = 1) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v:.{nd}f}{unit}"


def _ok(gap: float | None, n_a: int, n_b: int) -> bool:
    return gap is not None and gap >= MIN_REL_GAP and n_a >= MIN_GAMES and n_b >= MIN_GAMES


def _worse_gap(pairs: list[tuple]) -> float | None:
    """Largest relative gap among metrics where value < baseline (i.e. you did worse)."""
    gaps = [rel_gap(v, b, f) for v, b, f in pairs if v is not None and b is not None and v < b]
    gaps = [g for g in gaps if g is not None]
    return max(gaps) if gaps else None


def _games(n: int) -> str:
    return f"{n} game{'s' if n != 1 else ''}"


# =========================================================================== climbing
def _group_vs_rest(mdf: pd.DataFrame, key: str):
    for val, g in mdf.groupby(key):
        rest = mdf[mdf[key] != val]
        if len(g) >= MIN_GAMES and len(rest) >= MIN_GAMES:
            yield val, g, rest, summarize(g), summarize(rest)


def tips_agents_maps(mdf: pd.DataFrame) -> list[Tip]:
    tips: list[Tip] = []
    for key, label in (("agent", "agent"), ("map", "map")):
        best = worst = None
        for val, g, rest, s, r in _group_vs_rest(mdf, key):
            gap = rel_gap(s["win_rate"], r["win_rate"], 10)
            if not _ok(gap, len(g), len(rest)):
                continue
            cand = (gap * math.sqrt(min(len(g), len(rest))), val, s, r, gap, min(len(g), len(rest)))
            if s["win_rate"] < r["win_rate"]:
                worst = max(worst, cand, key=lambda c: c[0]) if worst else cand
            else:
                best = max(best, cand, key=lambda c: c[0]) if best else cand
        if worst:
            _, val, s, r, gap, n = worst
            shows = (f"Win rate on {val} is {_fmt(s['win_rate'], '%', 0)} ({_games(s['games'])}) vs "
                     f"{_fmt(r['win_rate'], '%', 0)} on your other {label}s ({_games(r['games'])}); "
                     f"ACS {_fmt(s['acs'], '', 0)} vs {_fmt(r['acs'], '', 0)}.")
            if key == "agent":
                interp = (f"You may not yet have the fundamentals (lineups, timings, role duties) on {val} "
                          "that you have on your other agents, so ranked games on it cost RR.")
                practice = (f"Stop locking {val} in ranked for now. Play it in Unrated/Swiftplay until its "
                            f"ACS approaches {_fmt(r['acs'], '', 0)} (your other-agent level); in ranked, pick "
                            "your best-performing agent instead.")
            else:
                interp = (f"You likely lack a default plan on {val} (where to stand, what util to use per "
                          "site); you can't dodge maps in queue, so this is a knowledge gap to close.")
                practice = (f"Load a Custom game on {val} with your main agent: walk each site, pick 2 "
                            "defensive positions and 1 attack plan per site, and practice the utility for "
                            "each (15 minutes) before your next ranked session.")
            tips.append(Tip("Climbing", f"Weakest {label}: {val}", shows, interp, practice,
                            s["win_rate"], r["win_rate"], gap, n))
        if best:
            _, val, s, r, gap, n = best
            shows = (f"Win rate on {val} is {_fmt(s['win_rate'], '%', 0)} ({_games(s['games'])}) vs "
                     f"{_fmt(r['win_rate'], '%', 0)} on your other {label}s ({_games(r['games'])}); "
                     f"ACS {_fmt(s['acs'], '', 0)} vs {_fmt(r['acs'], '', 0)}.")
            if key == "agent":
                interp = f"{val} is currently your most reliable way to gain RR."
                practice = (f"Make {val} your first pick in ranked. Also learn one backup agent of the same "
                            "role in Unrated so you still have a strong pick when it is taken.")
            else:
                interp = f"Your habits on {val} are working; they may transfer to weaker maps."
                practice = (f"Write down what you do on {val} (positions, default, util timing) and copy one "
                            "of those habits onto your weakest map next session.")
            tips.append(Tip("Climbing", f"Strongest {label}: {val}", shows, interp, practice,
                            s["win_rate"], r["win_rate"], gap, n))
    return tips


def tips_tilt(mdf: pd.DataFrame) -> list[Tip]:
    if "after_loss_streak" not in mdf:
        return []
    tilt, normal = mdf[mdf["after_loss_streak"]], mdf[~mdf["after_loss_streak"]]
    if len(tilt) < MIN_GAMES or len(normal) < MIN_GAMES:
        return []
    t, n = summarize(tilt), summarize(normal)
    out = []
    gap = _worse_gap([(t["win_rate"], n["win_rate"], 10), (t["acs"], n["acs"], 50)])
    if _ok(gap, len(tilt), len(normal)):
        shows = (f"In games played right after 2+ straight losses: win rate {_fmt(t['win_rate'], '%', 0)}, "
                 f"ACS {_fmt(t['acs'], '', 0)} ({_games(t['games'])}) vs {_fmt(n['win_rate'], '%', 0)} "
                 f"and ACS {_fmt(n['acs'], '', 0)} otherwise ({_games(n['games'])}).")
        out.append(Tip("Climbing", "Tilt: you play worse after a losing streak", shows,
                       "Losing streaks seem to carry into your next game (frustration, rushed decisions).",
                       "Stop-loss rule: after 2 losses in a row, stop ranked. Take a 10-minute break or play "
                       "one Deathmatch before you queue again, and end the session after 3 straight losses.",
                       t["win_rate"], n["win_rate"], gap, min(len(tilt), len(normal))))
    return out


def tips_session(mdf: pd.DataFrame) -> list[Tip]:
    if "session_game" not in mdf or mdf["session_game"].isna().all():
        return []
    late = mdf[mdf["session_game"] >= 4]
    early = mdf[mdf["session_game"] <= 3]
    if len(late) < MIN_GAMES or len(early) < MIN_GAMES:
        return []
    l, e = summarize(late), summarize(early)
    gap = _worse_gap([(l["win_rate"], e["win_rate"], 10), (l["acs"], e["acs"], 50)])
    if not _ok(gap, len(late), len(early)):
        return []
    shows = (f"Game 4+ of a session: ACS {_fmt(l['acs'], '', 0)}, win rate {_fmt(l['win_rate'], '%', 0)} "
             f"({_games(l['games'])}) vs games 1-3: ACS {_fmt(e['acs'], '', 0)}, win rate "
             f"{_fmt(e['win_rate'], '%', 0)} ({_games(e['games'])}). Sessions are split at gaps over 60 min.")
    return [Tip("Climbing", "Your performance drops late in long sessions", shows,
                "Fatigue or loss of focus after ~3 games is likely costing rounds.",
                "Cap ranked sessions at 3 games. If you want to keep playing, switch to Deathmatch or Unrated.",
                l["acs"] or 0, e["acs"] or 0, gap, min(len(late), len(early)))]


# =========================================================================== aim
def _trend_split(mdf: pd.DataFrame):
    m = mdf.sort_values("started_at", kind="stable")
    if len(m) < TREND_WINDOW + MIN_GAMES:
        return None
    return m.tail(TREND_WINDOW), m.head(len(m) - TREND_WINDOW)


def tips_aim(mdf: pd.DataFrame) -> list[Tip]:
    out = []
    split = _trend_split(mdf)
    if split:
        recent, earlier = split
        r, e = summarize(recent), summarize(earlier)
        n = min(len(recent), len(earlier))
        g = rel_gap(r["hs_pct"], e["hs_pct"], 5)
        if r["hs_pct"] is not None and e["hs_pct"] is not None and r["hs_pct"] < e["hs_pct"] and _ok(g, len(recent), len(earlier)):
            out.append(Tip("Aim", "Headshot % is trending down",
                           f"HS% over your last {TREND_WINDOW} games is {_fmt(r['hs_pct'], '%')} vs "
                           f"{_fmt(e['hs_pct'], '%')} in your {_games(len(earlier))} before that.",
                           "Your crosshair placement may be drifting lower (aiming at chest/legs before shooting).",
                           "Before ranked: Range > Shooting Test on Hard, 2 runs, then 1 Deathmatch where you only "
                           "tap/burst at head height and count head kills. Keep the crosshair at head level when "
                           "clearing angles.",
                           r["hs_pct"], e["hs_pct"], g, n))
        g = rel_gap(r["adr"], e["adr"], 30)
        if r["adr"] is not None and e["adr"] is not None and r["adr"] < e["adr"] and _ok(g, len(recent), len(earlier)):
            out.append(Tip("Aim", "Damage per round is trending down",
                           f"ADR over your last {TREND_WINDOW} games is {_fmt(r['adr'], '', 0)} vs "
                           f"{_fmt(e['adr'], '', 0)} in your {_games(len(earlier))} before that.",
                           "You're winning fewer gunfights or taking fewer of them.",
                           "Deathmatch warm-up (1 game) focused on first-bullet accuracy: stop moving before you "
                           "shoot, and reset your crosshair to head height after every kill.",
                           r["adr"], e["adr"], g, n))
    # body-shot heavy on a specific agent vs your other agents
    for agent, g_df, rest, s, rst in _group_vs_rest(mdf, "agent"):
        g = rel_gap(s["hs_pct"], rst["hs_pct"], 5)
        if s["hs_pct"] is not None and rst["hs_pct"] is not None and s["hs_pct"] < rst["hs_pct"] and _ok(g, len(g_df), len(rest)):
            out.append(Tip("Aim", f"Body-shot heavy on {agent}",
                           f"HS% on {agent} is {_fmt(s['hs_pct'], '%')} vs {_fmt(rst['hs_pct'], '%')} on your other "
                           f"agents; leg-shot share {_fmt(s['leg_pct'], '%')} vs {_fmt(rst['leg_pct'], '%')}.",
                           f"Your aim on {agent} may suffer from how you play it (e.g. shooting while moving "
                           "after abilities, or spraying at close range).",
                           f"Range: 3 rounds of strafe bots on Medium using the gun you buy most on {agent}. "
                           "In game: after using a movement ability, stop fully before your first shot.",
                           s["hs_pct"], rst["hs_pct"], g, min(len(g_df), len(rest))))
    return out


# =========================================================================== agent roles
def _role_rows(rdf: pd.DataFrame, agent: str) -> pd.DataFrame:
    return rdf[rdf["agent"] == agent] if not rdf.empty else rdf


def tips_roles(mdf: pd.DataFrame, rdf: pd.DataFrame) -> list[Tip]:
    out: list[Tip] = []
    for agent, g in mdf.groupby("agent"):
        if len(g) < MIN_GAMES:
            continue
        role = g["role"].iloc[0]
        rest = mdf[mdf["agent"] != agent]
        s, r = summarize(g), summarize(rest) if len(rest) else None
        n_rest = len(rest)
        if role == "Duelist":
            out += _duelist(agent, s, r, len(g), n_rest)
        elif role == "Initiator":
            out += _wins_vs_losses(agent, g, "assists_per_round", "Assists per round",
                                   "Your utility isn't turning into team kills in the games you lose.",
                                   f"Custom game: practice 2 info/flash lineups per site for {agent}. In ranked, "
                                   "call your util ('flashing A main now') and use it right before a teammate peeks.")
            out += _wins_vs_losses(agent, g, "casts_per_round", "Ability casts per round",
                                   "You may be holding utility in the games you lose.",
                                   f"Rule for next session: on {agent}, use at least one ability before the first "
                                   "fight of every round.")
        elif role == "Controller":
            out += _wins_vs_losses(agent, g, "casts_per_round", "Ability casts per round",
                                   "Fewer smokes/util in losses suggests late or missing smokes.",
                                   f"Custom game on your most-played map: practice the default smokes for each site "
                                   f"on {agent} until you can place them in under 5 seconds.")
            if r and n_rest >= MIN_GAMES:
                gap = rel_gap(s["survival_pct"], r["survival_pct"], 10)
                if s["survival_pct"] < r["survival_pct"] and _ok(gap, len(g), n_rest):
                    out.append(Tip("Agent role", f"{agent}: you die too often for a controller",
                                   f"You survive {_fmt(s['survival_pct'], '%', 0)} of rounds on {agent} vs "
                                   f"{_fmt(r['survival_pct'], '%', 0)} on your other agents.",
                                   "Controllers losing their life loses the team's smokes for later in the round.",
                                   "Smoke from safe positions, then play behind your team. In Deathmatch, practise "
                                   "holding one angle without re-peeking.",
                                   s["survival_pct"], r["survival_pct"], gap, min(len(g), n_rest)))
        elif role == "Sentinel":
            out += _sentinel(agent, mdf, rdf, len(g))
    return out


def _duelist(agent, s, r, n_a, n_rest) -> list[Tip]:
    out = []
    fk, fd = s["fk_per_round"] or 0, s["fd_per_round"] or 0
    if r and n_rest >= MIN_GAMES:
        gap = rel_gap(s["fd_pct"], r["fd_pct"], 5)
        if s["fd_pct"] > r["fd_pct"] and _ok(gap, n_a, n_rest):
            out.append(Tip("Agent role", f"{agent}: too many first deaths",
                           f"First death in {_fmt(s['fd_pct'], '%', 0)} of rounds on {agent} vs "
                           f"{_fmt(r['fd_pct'], '%', 0)} on your other agents (FK:FD {fk:.2f}:{fd:.2f} per round).",
                           "You're likely entering without utility or teammate support.",
                           "Habit: only take the first fight with your entry ability ready, with a teammate close "
                           "enough to trade. Deathmatch: practise jiggle-peeking for info before committing.",
                           s["fd_pct"], r["fd_pct"], gap, min(n_a, n_rest)))
    es = s["entry_success_pct"]
    if es is not None:
        vs_rest = bool(r and n_rest >= MIN_GAMES and r["entry_success_pct"] is not None)
        base = r["entry_success_pct"] if vs_rest else ENTRY_BREAK_EVEN
        base_txt = "your other agents" if vs_rest else "the 50% break-even point"
        n = min(n_a, n_rest) if vs_rest else n_a
        gap = rel_gap(es, base, 10)
        if es < base and _ok(gap, n_a, n_rest if vs_rest else MIN_GAMES):
            out.append(Tip("Agent role", f"{agent}: entry duels losing",
                           f"Entry success (first kills / first duels you are in) on {agent} is "
                           f"{_fmt(es, '%', 0)} vs {_fmt(base, '%', 0)} for {base_txt}.",
                           "Your opening fights are being taken on bad terms (wide swings, no flash/dash).",
                           "Range: practise your entry ability + peek combo (e.g. flash then swing) 20 times. "
                           "In ranked, pre-aim the most common angle at head height before you swing.",
                           es, base, gap, n))
    return out


def _wins_vs_losses(agent, g, col, label, interp, practice) -> list[Tip]:
    w, l = g[g["won"]], g[g["result"] == "Loss"]
    if len(w) < MIN_GAMES or len(l) < MIN_GAMES:
        return []
    sw, sl = summarize(w), summarize(l)
    vw, vl = sw.get(col), sl.get(col)
    if vw is None or vl is None or vl >= vw:
        return []
    gap = rel_gap(vl, vw, 0.1)
    if not _ok(gap, len(w), len(l)):
        return []
    return [Tip("Agent role", f"{agent}: {label.lower()} drops in losses",
                f"{label} on {agent}: {vl:.2f} in losses ({_games(len(l))}) vs {vw:.2f} in wins ({_games(len(w))}).",
                interp, practice + f" Target: about {vw:.1f} per round, your own level in wins.",
                vl, vw, gap, min(len(w), len(l)))]


def _sentinel(agent, mdf, rdf, n_a) -> list[Tip]:
    out = []
    if rdf.empty:
        return out
    mine = rdf[rdf["agent"] == agent]
    other = rdf[rdf["agent"] != agent]
    n_other = mdf[mdf["agent"] != agent].shape[0]
    d_mine = mine[mine["side"] == "defense"]
    d_other = other[other["side"] == "defense"]
    if len(d_mine) and len(d_other) and n_other >= MIN_GAMES:
        a, b = 100 * d_mine["first_death"].mean(), 100 * d_other["first_death"].mean()
        gap = rel_gap(a, b, 5)
        if a > b and _ok(gap, n_a, n_other):
            out.append(Tip("Agent role", f"{agent}: dying first on defense",
                           f"First death in {a:.0f}% of defense rounds on {agent} vs {b:.0f}% on your other agents.",
                           "As a sentinel you're probably holding the first-contact angle instead of letting your "
                           "setup slow the push.",
                           f"Set your {agent} utility to delay, play one step back from it, and fall back after "
                           "first contact. Custom game: set up each site and check which angles your util covers.",
                           a, b, gap, min(n_a, n_other)))
    ret_m = mine[(mine["side"] == "defense") & mine["enemy_planted"]]
    ret_o = other[(other["side"] == "defense") & other["enemy_planted"]]
    if len(ret_m) >= 5 and len(ret_o) >= 5 and n_other >= MIN_GAMES:
        a, b = 100 * ret_m["won"].mean(), 100 * ret_o["won"].mean()
        gap = rel_gap(a, b, 10)
        if a < b and _ok(gap, n_a, n_other):
            out.append(Tip("Agent role", f"{agent}: retakes failing",
                           f"Your team wins {a:.0f}% of retakes ({len(ret_m)} rounds) when you play {agent} vs "
                           f"{b:.0f}% ({len(ret_o)} rounds) on your other agents.",
                           "You may be dying before the retake or retaking alone instead of with your team.",
                           "Range > Spike Defuse practice to learn defuse timings; in ranked, wait for one "
                           "teammate and use utility before you retake.",
                           a, b, gap, min(n_a, n_other)))
    return out


# =========================================================================== sides
def tips_sides(mdf: pd.DataFrame, rdf: pd.DataFrame) -> list[Tip]:
    if rdf.empty:
        return []
    atk, dfn = rdf[rdf["side"] == "attack"], rdf[rdf["side"] == "defense"]
    if not len(atk) or not len(dfn):
        return []
    a, d = 100 * atk["won"].mean(), 100 * dfn["won"].mean()
    ka, kd = 100 * atk["kast"].mean(), 100 * dfn["kast"].mean()
    weak, strong = ("attack", "defense") if a < d else ("defense", "attack")
    wv, sv = min(a, d), max(a, d)
    gap = rel_gap(wv, sv, 10)
    n = len(mdf)
    if not _ok(gap, n, n):
        return []
    if weak == "attack":
        practice = ("Before each attack round, agree on one default with utility (who takes control where). "
                    "Range > Spike Plant practice: learn 2 safe plant spots per site.")
        interp = "Your team (and you) may be attacking without a plan or committing too late."
    else:
        practice = ("Play crossfires with a teammate and avoid repeeking after first contact. "
                    "Range > Spike Defuse practice to sharpen retake timing.")
        interp = "You may be taking risky duels on defense instead of holding for trades."
    shows = (f"Round win rate on {weak} is {wv:.0f}% ({len(atk if weak == 'attack' else dfn)} rounds) vs "
             f"{sv:.0f}% on {strong}; your KAST is {ka:.0f}% attacking and {kd:.0f}% defending.")
    return [Tip("Side", f"Weaker on {weak}", shows, interp, practice, wv, sv, gap, n)]


# =========================================================================== entry point
def generate_tips(mdf: pd.DataFrame, rdf: pd.DataFrame) -> list[Tip]:
    if mdf is None or mdf.empty:
        return []
    tips = (tips_agents_maps(mdf) + tips_tilt(mdf) + tips_session(mdf) + tips_aim(mdf)
            + tips_roles(mdf, rdf) + tips_sides(mdf, rdf))
    return sorted(tips, key=lambda t: t.impact, reverse=True)
