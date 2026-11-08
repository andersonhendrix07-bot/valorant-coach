"""Presentation helpers: CSS, HTML cards and Vega-Lite chart specs.

Pure functions (no Streamlit import) so they can be unit-tested and previewed in a browser.
Every value that comes from the API or the visitor is HTML-escaped: this is a public site and
Riot IDs are user-controlled text.

Colors (dark UI; chart colors validated with the dataviz palette checker on #0e1117):
- data series / RR gain: blue #3987e5 · RR loss: red #e66767 (diverging pair, never alone: +/- labels)
- win / loss state: status good #0ca30c / critical #d03b3b, always paired with a WIN/LOSS label
- brand accent (non-data chrome only): VALORANT red #ff4655
"""
from __future__ import annotations

import html
import math
import re

import pandas as pd

ACCENT = "#ff4655"
SERIES = "#3987e5"
NEG = "#e66767"
GOOD = "#0ca30c"
BAD = "#d03b3b"
INK = "#f0efec"
INK_2 = "#c3c2b7"
MUTED = "#898781"
GRID = "#2c2c2a"
AXIS = "#383835"

ROLE_ICON = {"Duelist": "⚔️", "Initiator": "🔎", "Controller": "🌫️", "Sentinel": "🛡️", "Unknown": "❔"}
CATEGORY_COLOR = {"Climbing": "#3987e5", "Aim": "#d95926", "Agent role": "#9085e9", "Side": "#199e70"}

e = lambda v: html.escape("" if v is None else str(v), quote=True)  # noqa: E731


def flat(markup: str) -> str:
    """Collapse newlines + indentation. Streamlit's Markdown would otherwise turn indented HTML
    that follows a blank line into a code block."""
    return re.sub(r"\s*\n\s*", " ", markup).strip()


def num(v, nd=0, unit="", plus=False) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    s = f"{v:+.{nd}f}" if plus else f"{v:.{nd}f}"
    return s + unit


# --------------------------------------------------------------------------- CSS
CSS = f"""
<style>
:root {{ --accent:{ACCENT}; --ink:{INK}; --ink2:{INK_2}; --muted:{MUTED};
        --card:rgba(255,255,255,0.035); --line:rgba(255,255,255,0.10); }}
.block-container {{ padding-top: 1.6rem; max-width: 1250px; }}
h1, h2, h3 {{ letter-spacing: .01em; }}
.vc-card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; }}
.vc-hero {{ display:flex; flex-wrap:wrap; gap:22px; align-items:center; justify-content:space-between;
           background:linear-gradient(120deg, rgba(255,70,85,.16), rgba(255,255,255,.02) 55%);
           border:1px solid var(--line); border-left:4px solid var(--accent); border-radius:16px; padding:20px 24px; }}
.vc-name {{ font-size:1.9rem; font-weight:800; color:var(--ink); line-height:1.1; }}
.vc-name span {{ color:var(--muted); font-weight:600; }}
.vc-sub {{ color:var(--ink2); font-size:.92rem; margin-top:6px; }}
.vc-sub a {{ color:var(--ink2); }}
.vc-rank {{ min-width:230px; }}
.vc-rank .tier {{ font-size:1.35rem; font-weight:800; color:var(--ink); }}
.vc-rank .rr {{ color:var(--ink2); font-size:.9rem; margin:2px 0 6px; }}
.vc-bar {{ height:8px; background:rgba(255,255,255,.08); border-radius:4px; overflow:hidden; }}
.vc-bar > div {{ height:100%; background:var(--accent); border-radius:4px; }}
.vc-form {{ display:flex; gap:4px; margin-top:8px; }}
.vc-pill {{ width:22px; height:22px; border-radius:6px; font-size:.7rem; font-weight:800; color:#fff;
           display:flex; align-items:center; justify-content:center; }}
.vc-kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:14px 0 4px; }}
@media (max-width: 640px) {{ .vc-kpis {{ grid-template-columns:repeat(2,1fr); }} }}
.vc-kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; }}
.vc-kpi .l {{ color:var(--muted); font-size:.74rem; text-transform:uppercase; letter-spacing:.06em; }}
.vc-kpi .v {{ color:var(--ink); font-size:1.55rem; font-weight:800; margin-top:2px; }}
.vc-kpi .s {{ color:var(--ink2); font-size:.78rem; }}
.vc-focus {{ border:1px solid rgba(255,70,85,.45); background:rgba(255,70,85,.08); border-radius:14px;
            padding:14px 18px; margin:14px 0; }}
.vc-focus .h {{ color:var(--accent); font-weight:800; font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; }}
.vc-focus .t {{ color:var(--ink); font-weight:700; margin:4px 0; }}
.vc-focus .p {{ color:var(--ink2); }}
.vc-tip {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; margin-bottom:12px; }}
.vc-tip .top {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
.vc-tip .n {{ color:var(--muted); font-weight:800; }}
.vc-tip .title {{ color:var(--ink); font-weight:800; font-size:1.05rem; }}
.vc-badge {{ font-size:.7rem; font-weight:800; padding:3px 8px; border-radius:999px; color:#fff;
            text-transform:uppercase; letter-spacing:.05em; }}
.vc-warn {{ font-size:.7rem; font-weight:700; padding:3px 8px; border-radius:999px; color:#0b0b0b; background:#fab219; }}
.vc-impact {{ display:flex; align-items:center; gap:8px; margin:10px 0 4px; color:var(--muted); font-size:.75rem; }}
.vc-impact .track {{ flex:1; max-width:220px; height:6px; background:rgba(255,255,255,.08); border-radius:3px; overflow:hidden; }}
.vc-impact .fill {{ height:100%; background:{SERIES}; border-radius:3px; }}
.vc-tip dl {{ margin:8px 0 0; display:grid; grid-template-columns:max-content 1fr; gap:6px 14px; }}
.vc-tip dt {{ color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.05em; padding-top:2px; }}
.vc-tip dd {{ margin:0; color:var(--ink); }}
.vc-tip dd.i {{ color:var(--ink2); font-style:italic; }}
.vc-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; }}
.vc-ent .h {{ display:flex; justify-content:space-between; align-items:baseline; }}
.vc-ent .name {{ color:var(--ink); font-weight:800; font-size:1.05rem; }}
.vc-ent .role {{ color:var(--muted); font-size:.78rem; }}
.vc-ent .wr {{ font-size:1.6rem; font-weight:800; color:var(--ink); margin-top:4px; }}
.vc-ent .wr small {{ font-size:.8rem; color:var(--muted); font-weight:600; }}
.vc-ent .row {{ display:flex; gap:12px; color:var(--ink2); font-size:.82rem; margin-top:4px; flex-wrap:wrap; }}
.vc-timeline {{ display:flex; flex-wrap:wrap; gap:4px; margin:6px 0 2px; }}
.vc-r {{ width:30px; height:48px; border-radius:6px; display:flex; flex-direction:column; align-items:center;
        justify-content:center; font-size:.68rem; font-weight:800; color:#fff; position:relative; }}
.vc-r .k {{ font-size:.62rem; font-weight:700; opacity:.9; }}
.vc-r .t {{ font-size:.55rem; font-weight:800; background:rgba(0,0,0,.35); border-radius:3px; padding:0 2px; margin-top:1px; }}
.vc-r.half {{ margin-left:10px; }}
.vc-legend {{ color:var(--muted); font-size:.75rem; }}
.vc-foot {{ color:var(--muted); font-size:.75rem; margin-top:28px; border-top:1px solid var(--line); padding-top:10px; }}
div.stButton > button[kind="primary"] {{ background:var(--accent); border-color:var(--accent); }}
</style>
"""


# --------------------------------------------------------------------------- hero / header
def rr_progress(tier_name: str | None, rr) -> float | None:
    """Fraction of the way to the next rank. None for Immortal/Radiant (RR isn't capped at 100)."""
    if rr is None or tier_name is None:
        return None
    if any(t in tier_name for t in ("Immortal", "Radiant")):
        return None
    return max(0.0, min(1.0, float(rr) / 100))


def form_html(results: list[str]) -> str:
    pills = []
    for r in results:
        color, letter = (GOOD, "W") if r == "Win" else (BAD, "L") if r == "Loss" else (MUTED, "D")
        pills.append(f'<div class="vc-pill" style="background:{color}" title="{e(r)}">{letter}</div>')
    return f'<div class="vc-form" aria-label="Recent results, oldest to newest">{"".join(pills)}</div>'


def hero_html(riot_id: str, region: str, mmr: dict | None, summary: dict, form: list[str],
              profile_url: str, n_games: int, agent_filter: str | None = None, map_filter: str | None = None) -> str:
    name, _, tag = riot_id.partition("#")
    cur = (mmr or {}).get("current") or {}
    peak = (mmr or {}).get("peak") or {}
    tier = (cur.get("tier") or {}).get("name")
    rr = cur.get("rr")
    last = cur.get("last_change")
    prog = rr_progress(tier, rr)
    bar = f'<div class="vc-bar"><div style="width:{prog * 100:.0f}%"></div></div>' if prog is not None else ""
    last_txt = f" · last game {last:+d} RR" if isinstance(last, int) else ""
    peak_txt = f"Peak {e((peak.get('tier') or {}).get('name'))}" if peak.get("tier") else ""
    filt = " · ".join(e(f) for f in (agent_filter, map_filter) if f)
    wins = summary.get("wins", 0)
    games = summary.get("games", 0)
    return f"""
<div class="vc-hero">
  <div>
    <div class="vc-name">{e(name)} <span>#{e(tag)}</span></div>
    <div class="vc-sub">{e(region.upper())} · last {n_games} competitive games{(' · ' + filt) if filt else ''}
      · <a href="{e(profile_url)}" target="_blank" rel="noopener">tracker.gg ↗</a></div>
    <div class="vc-sub">Record <b>{wins}-{games - wins}</b> · recent form (oldest → newest)</div>
    {form_html(form)}
  </div>
  <div class="vc-rank">
    <div class="tier">{e(tier) if tier else 'Rank unavailable'}</div>
    <div class="rr">{(e(rr) + ' RR') if rr is not None else ''}{e(last_txt)}</div>
    {bar}
    <div class="vc-sub">{peak_txt}</div>
  </div>
</div>"""


def kpis_html(items: list[tuple[str, str, str]]) -> str:
    tiles = "".join(f'<div class="vc-kpi"><div class="l">{e(l)}</div><div class="v">{e(v)}</div>'
                    f'<div class="s">{e(s)}</div></div>' for l, v, s in items)
    return f'<div class="vc-kpis">{tiles}</div>'


def overview_kpis(s: dict) -> str:
    return kpis_html([
        ("Win rate", num(s.get("win_rate"), 0, "%"), f"{s.get('wins', 0)}W {s.get('games', 0) - s.get('wins', 0)}L"),
        ("K/D", num(s.get("kd"), 2), f"KAST {num(s.get('kast_pct'), 0, '%')}"),
        ("ACS", num(s.get("acs")), "combat score / round"),
        ("ADR", num(s.get("adr")), "damage / round"),
        ("Headshot %", num(s.get("hs_pct"), 1, "%"), f"legs {num(s.get('leg_pct'), 1, '%')}"),
        ("First kills", num(s.get("fk_per_round"), 2), f"vs {num(s.get('fd_per_round'), 2)} first deaths / rd"),
        ("Clutches", f"{s.get('clutches_won', 0)}/{s.get('clutch_attempts', 0)}", f"{s.get('aces', 0)} aces"),
        ("Net RR", num(s.get("rr_total"), 0, plus=True) if s.get("rr_total") is not None else "–", "these games"),
    ])


# --------------------------------------------------------------------------- tips
def focus_html(tip) -> str:
    return f"""<div class="vc-focus"><div class="h">🎯 Focus for your next session</div>
<div class="t">{e(tip.title)}</div><div class="p">{e(tip.practice)}</div></div>"""


def tip_html(i: int, tip, max_impact: float) -> str:
    color = CATEGORY_COLOR.get(tip.category, SERIES)
    width = 100 * tip.impact / max_impact if max_impact else 0
    low = '<span class="vc-warn">⚠ low sample</span>' if tip.low_sample else ""
    return f"""
<div class="vc-tip">
  <div class="top"><span class="n">#{i}</span><span class="vc-badge" style="background:{color}">{e(tip.category)}</span>
    <span class="title">{e(tip.title)}</span>{low}</div>
  <div class="vc-impact">impact <div class="track"><div class="fill" style="width:{width:.0f}%"></div></div>
    {tip.impact:.2f} · gap {tip.rel_gap:.0%} · {tip.sample} games</div>
  <dl>
    <dt>Data</dt><dd>{e(tip.data_shows)}</dd>
    <dt>Likely means</dt><dd class="i">Interpretation: {e(tip.interpretation)}</dd>
    <dt>Practice</dt><dd><b>{e(tip.practice)}</b></dd>
  </dl>
</div>"""


# --------------------------------------------------------------------------- agents / maps
def entity_cards_html(table: pd.DataFrame, key: str, side_map: pd.DataFrame | None = None) -> str:
    cards = []
    for r in table.itertuples(index=False):
        name = getattr(r, key)
        role = ""
        if key == "agent":
            from roles import role_of
            ro = role_of(name)
            role = f'{ROLE_ICON.get(ro, "")} {e(ro)}'
        extra = ""
        if side_map is not None and not side_map.empty:
            sm = side_map[side_map[key] == name].set_index("side")
            if "attack" in sm.index and "defense" in sm.index:
                extra = (f'<div class="row"><span>ATK {sm.loc["attack", "round_win_pct"]:.0f}%</span>'
                         f'<span>DEF {sm.loc["defense", "round_win_pct"]:.0f}%</span><span>rounds won</span></div>')
        low = ' <span class="vc-warn">low sample</span>' if r.low_sample else ""
        cards.append(f"""<div class="vc-card vc-ent"><div class="h"><span class="name">{e(name)}</span>
<span class="role">{role}</span></div>
<div class="wr">{num(r.win_rate, 0, '%')} <small>win · {r.games} game{'s' if r.games != 1 else ''}</small>{low}</div>
<div class="row"><span>K/D {num(r.kd, 2)}</span><span>ACS {num(r.acs)}</span><span>ADR {num(r.adr)}</span>
<span>HS {num(r.hs_pct, 0, '%')}</span></div>{extra}</div>""")
    return f'<div class="vc-grid">{"".join(cards)}</div>'


# --------------------------------------------------------------------------- matches
def match_label(r) -> str:
    """Expander label (Streamlit markdown: :green[]/:red[] + the word WIN/LOSS, never color alone)."""
    res = {"Win": ":green[**WIN**]", "Loss": ":red[**LOSS**]"}.get(r.result, "**DRAW**")
    rr = "" if pd.isna(r.rr_change) else f" · {int(r.rr_change):+d} RR"
    when = r.started_at.strftime("%b %d, %H:%M") if r.started_at is not None and not pd.isna(r.started_at) else ""
    safe = lambda t: str(t).replace("[", "(").replace("]", ")").replace(":", "꞉")  # noqa: E731
    return (f"{res} {safe(r.score)} · {safe(r.map)} · {safe(r.agent)} · {r.kills}/{r.deaths}/{r.assists} · "
            f"ACS {num(r.acs)}{rr} · {when}")


def round_timeline_html(rounds: pd.DataFrame) -> str:
    cells = []
    for r in rounds.itertuples(index=False):
        color, letter = (GOOD, "W") if r.won else (BAD, "L")
        cls = ["vc-r"]
        if r.first_kill:
            cls.append("fk")
        if r.first_death:
            cls.append("fd")
        if r.round == 13:
            cls.append("half")
        side = "ATK" if r.side == "attack" else "DEF"
        tip = (f"Round {r.round} ({side}, {r.buy_type}) — {'won' if r.won else 'lost'}; "
               f"{r.kills} kill(s){'; died' if r.died else '; survived'}"
               f"{'; first kill' if r.first_kill else ''}{'; first death' if r.first_death else ''}"
               f"{'; KAST' if r.kast else ''}")
        kills = f'<span class="k">{r.kills}K</span>' if r.kills else '<span class="k">&nbsp;</span>'
        tag = ('<span class="t">FK</span>' if r.first_kill else '<span class="t">FD</span>' if r.first_death
               else '<span class="k">&nbsp;</span>')
        cells.append(f'<div class="{" ".join(cls)}" style="background:{color}" title="{e(tip)}">'
                     f'{letter}{kills}{tag}</div>')
    legend = ('<div class="vc-legend">W/L = round result · nK = your kills · FK = you got the first kill · '
              'FD = you died first · gap = side swap · hover a round for details</div>')
    return f'<div class="vc-timeline">{"".join(cells)}</div>{legend}'


def footer_html(legal: str) -> str:
    return f'<div class="vc-foot">{e(legal)}</div>'


# --------------------------------------------------------------------------- Vega-Lite specs
def _base(height=220) -> dict:
    return {
        "height": height,
        "background": "transparent",
        "config": {
            "view": {"stroke": None},
            "axis": {"labelColor": MUTED, "titleColor": INK_2, "gridColor": GRID, "domainColor": AXIS,
                     "tickColor": AXIS, "labelFontSize": 11, "titleFontWeight": 600},
            "legend": {"labelColor": INK_2, "titleColor": INK_2},
            "title": {"color": INK, "anchor": "start", "fontSize": 13},
        },
    }


def rr_change_spec() -> dict:
    """Diverging bars: gain (blue) up, loss (red) down. Tooltip carries the signed number."""
    s = _base(200)
    s.update({
        "title": "RR change per game",
        "mark": {"type": "bar", "cornerRadiusEnd": 4, "width": {"band": 0.7}},
        "encoding": {
            "x": {"field": "game", "type": "ordinal", "title": None, "axis": {"labels": False, "ticks": False}},
            "y": {"field": "last_change", "type": "quantitative", "title": "RR"},
            "color": {"condition": {"test": "datum.last_change >= 0", "value": SERIES}, "value": NEG},
            "tooltip": [{"field": "date", "type": "temporal", "title": "Date", "format": "%b %d %H:%M"},
                        {"field": "map", "title": "Map"},
                        {"field": "last_change", "title": "RR", "format": "+d"},
                        {"field": "tier", "title": "Rank after"}],
        },
    })
    return s


def elo_spec() -> dict:
    s = _base(220)
    s.update({
        "title": "Rank rating over time",
        "layer": [
            {"mark": {"type": "line", "strokeWidth": 2, "color": SERIES, "interpolate": "monotone"}},
            {"mark": {"type": "point", "filled": True, "size": 64, "color": SERIES, "opacity": 0},
             "params": [{"name": "hover", "select": {"type": "point", "on": "pointerover", "nearest": True,
                                                       "clear": "pointerout"}}],
             "encoding": {"opacity": {"condition": {"param": "hover", "empty": False, "value": 1}, "value": 0}}},
        ],
        "encoding": {
            "x": {"field": "date", "type": "temporal", "title": None},
            "y": {"field": "elo", "type": "quantitative", "title": "Rating", "scale": {"zero": False}},
            "tooltip": [{"field": "date", "type": "temporal", "format": "%b %d %H:%M", "title": "Date"},
                        {"field": "tier", "title": "Rank"}, {"field": "rr", "title": "RR"},
                        {"field": "elo", "title": "Rating"}],
        },
    })
    return s


def trend_spec(field: str, label: str) -> dict:
    s = _base(150)
    s.update({
        "title": label,
        "mark": {"type": "line", "strokeWidth": 2, "color": SERIES, "point": {"filled": True, "size": 30}},
        "encoding": {
            "x": {"field": "game_no", "type": "quantitative", "title": "Game #", "axis": {"tickMinStep": 1}},
            "y": {"field": field, "type": "quantitative", "title": None, "scale": {"zero": False}},
            "tooltip": [{"field": "game_no", "title": "Game"},
                        {"field": field, "title": label, "format": ".1f"}],
        },
    })
    return s


def weapon_spec() -> dict:
    s = _base(260)
    s.update({
        "title": "Kills by weapon",
        "mark": {"type": "bar", "cornerRadiusEnd": 4, "color": SERIES, "height": {"band": 0.7}},
        "encoding": {
            "y": {"field": "weapon", "type": "nominal", "sort": "-x", "title": None},
            "x": {"field": "kills", "type": "quantitative", "title": "Kills"},
            "tooltip": [{"field": "weapon", "title": "Weapon"}, {"field": "kills", "title": "Kills"},
                        {"field": "share_pct", "title": "Share %", "format": ".1f"}],
        },
    })
    return s


def rr_frame(mmr_history: list[dict]) -> pd.DataFrame:
    h = pd.DataFrame(mmr_history or [])
    if h.empty:
        return h
    h["date"] = pd.to_datetime(h["date"], utc=True, errors="coerce")
    h = h.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    h["tier"] = h["tier"].map(lambda t: (t or {}).get("name") if isinstance(t, dict) else t)
    h["map"] = h["map"].map(lambda m: (m or {}).get("name") if isinstance(m, dict) else m)
    h["game"] = range(1, len(h) + 1)
    return h[["game", "date", "elo", "rr", "last_change", "tier", "map"]]
