"""Streamlit UI (works locally and as a public website).  Run:  streamlit run app.py"""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import stats
from access import Cooldown, choose_key, looks_like_key, read_setting, SITE_COOLDOWN_S_DEFAULT, SITE_MAX_MATCHES_DEFAULT
from api_client import (REGIONS, PLATFORMS, HenrikClient, ValorantAPIError, tracker_profile_url)
from cache import Cache
from report import markdown_report, matches_csv
from sync import MAX_MATCHES, sync_player
from tips import generate_tips, MIN_REL_GAP, MIN_GAMES

load_dotenv()
st.set_page_config(page_title="VALORANT Coach", page_icon="🎯", layout="wide")

try:
    _SECRETS = st.secrets
except Exception:
    _SECRETS = None
SITE_KEY = read_setting(_SECRETS, "HENRIKDEV_API_KEY")
SITE_MAX = int(read_setting(_SECRETS, "SITE_MAX_MATCHES", SITE_MAX_MATCHES_DEFAULT))
SITE_COOLDOWN = float(read_setting(_SECRETS, "SITE_COOLDOWN_S", SITE_COOLDOWN_S_DEFAULT))

RIOT_LEGAL = ("VALORANT Coach isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot "
              "Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, "
              "and all associated properties are trademarks or registered trademarks of Riot Games, Inc.")


@st.cache_resource
def get_cache() -> Cache:
    return Cache()


@st.cache_resource
def get_site_client(key: str) -> HenrikClient:
    """Shared by every visitor, so its rate limiter covers all traffic on the site key."""
    return HenrikClient(key)


def get_visitor_client(key: str) -> HenrikClient:
    """Lives only in this visitor's session; the key is never stored on disk."""
    fp = hashlib.sha256(key.encode()).hexdigest()
    if st.session_state.get("_vkey_fp") != fp:
        st.session_state["_vclient"] = HenrikClient(key)
        st.session_state["_vkey_fp"] = fp
    return st.session_state["_vclient"]


def rnd(df: pd.DataFrame, n: int = 1) -> pd.DataFrame:
    df = df.copy()
    num = df.select_dtypes("number").columns
    df[num] = df[num].round(n)
    return df


def fmt(v, nd=1, unit=""):
    return "n/a" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:.{nd}f}{unit}"


# --------------------------------------------------------------------------- sidebar
qp = st.query_params
st.sidebar.title("🎯 VALORANT Coach")
riot_id = st.sidebar.text_input("Riot ID (Name#Tag)", value=st.session_state.get("riot_id", qp.get("riot", "")),
                                placeholder="Player#NA1")
_region_default = qp.get("region", "na")
region = st.sidebar.selectbox("Region", REGIONS,
                              index=REGIONS.index(_region_default) if _region_default in REGIONS else 0)
platform = st.sidebar.selectbox("Platform", PLATFORMS, index=0)

with st.sidebar.expander("Use your own API key" + ("" if SITE_KEY else " (required)"), expanded=not SITE_KEY):
    visitor_key = st.text_input("HenrikDev API key", type="password",
                                help="Free from https://api.henrikdev.xyz/dashboard/. Kept only in this browser "
                                     "session's memory and never saved.")
    st.caption("Your own key skips the shared queue and the "
               f"{SITE_MAX}-match limit." if SITE_KEY else "This site has no shared key, so lookups need yours.")

key, key_source = choose_key(SITE_KEY, visitor_key)
max_n = MAX_MATCHES if key_source == "visitor" else min(MAX_MATCHES, SITE_MAX)
n_matches = st.sidebar.slider("Recent competitive matches", 1, max_n, min(20, max_n))
offline = st.sidebar.checkbox("Use cached data only (no API calls)", value=False)
go = st.sidebar.button("Load / refresh", type="primary", use_container_width=True)
st.sidebar.divider()
st.sidebar.caption("Data from the unofficial [HenrikDev API](https://docs.henrikdev.xyz) (read-only). Nothing is "
                   "scraped and the game client is never touched. Match data is cached on the server to save "
                   "API calls.")
st.sidebar.caption(RIOT_LEGAL)

if go:
    try:
        if visitor_key and not looks_like_key(visitor_key):
            raise ValorantAPIError("That doesn't look like a HenrikDev API key. Copy it again from the dashboard.")
        client, refresh = None, False
        if not offline and key_source == "visitor":
            client, refresh = get_visitor_client(key), True
        elif not offline and key_source == "site":
            client = get_site_client(key)
            cd = st.session_state.setdefault("_cooldown", Cooldown(SITE_COOLDOWN))
            if cd.ready():
                refresh = True
                cd.mark()
            else:
                st.info(f"Showing cached data. You can refresh from the API again in {cd.remaining():.0f} s "
                        "(or add your own key to skip the wait).")
        elif not offline:
            st.info("No API key available, so only cached data can be shown. Add your own key in the sidebar.")
        bar = st.progress(0.0, text="Waiting for the API queue…" if key_source == "site" and refresh else "Starting…")
        res = sync_player(client, get_cache(), riot_id, region, n_matches, platform=platform, refresh=refresh,
                          progress=lambda f, t: bar.progress(min(1.0, f), text=t))
        bar.empty()
        st.session_state["res"] = res
        st.session_state["riot_id"] = riot_id
        st.query_params.update({"riot": res.riot_id, "region": region})   # shareable URL
    except ValorantAPIError as e:
        st.error(e.user_message)
    except Exception:  # last-resort guard so the UI never shows a raw traceback to visitors
        st.error("Something went wrong while loading this player. Please try again in a minute.")

res = st.session_state.get("res")
if res is None:
    st.title("VALORANT Coach")
    st.markdown(
        "Free stats and **data-backed tips to climb** from your recent competitive matches.\n\n"
        "1. Enter your **Riot ID** (Name#Tag) and **region** in the sidebar.\n"
        "2. Click **Load / refresh**. The first load downloads your matches and can take a minute or two; "
        "after that it's instant.\n"
        "3. Read your **Tips** tab. Every tip shows the numbers behind it and one thing to practise.\n\n"
        "Tips compare you only with **yourself** (your other agents, maps, earlier games and sides), never with "
        "made-up rank averages.")
    if not SITE_KEY:
        st.warning("This site needs your own free HenrikDev API key: open **Use your own API key** in the sidebar.")
    st.stop()

for w in res.warnings:
    st.warning(w)
if res.api_calls:
    st.sidebar.caption(f"Last refresh: {res.api_calls} API calls, {res.new_matches} new matches stored.")

puuid = res.account["puuid"]
all_mdf, _ = stats.build_frames(res.matches, puuid, res.mmr_history)
agents = sorted(all_mdf["agent"].dropna().unique()) if not all_mdf.empty else []
agent_filter = st.sidebar.selectbox("Agent filter", ["All agents"] + agents)
agent_filter = None if agent_filter == "All agents" else agent_filter
mdf, rdf = stats.build_frames(res.matches, puuid, res.mmr_history, agent_filter=agent_filter)

st.title(f"{res.riot_id}")
st.link_button("Open profile on tracker.gg", tracker_profile_url(res.riot_id))
if mdf.empty:
    st.info("No competitive matches found for this selection.")
    st.stop()

summary = stats.summarize(mdf)
tips = generate_tips(mdf, rdf)
tab_over, tab_agents, tab_maps, tab_matches, tab_tips, tab_export = st.tabs(
    ["Overview", "Agents", "Maps", "Matches", "Tips", "Export"])

# --------------------------------------------------------------------------- overview
with tab_over:
    cur = (res.mmr or {}).get("current") or {}
    peak = (res.mmr or {}).get("peak") or {}
    c = st.columns(4)
    c[0].metric("Current rank", (cur.get("tier") or {}).get("name", "Unavailable"))
    c[1].metric("RR", cur.get("rr", "n/a"), delta=cur.get("last_change"))
    c[2].metric("Peak", (peak.get("tier") or {}).get("name", "n/a"))
    c[3].metric("Net RR (these games)", summary.get("rr_total") if summary.get("rr_total") is not None else "n/a")

    c = st.columns(6)
    c[0].metric("Record", f"{summary['wins']}-{summary['games'] - summary['wins']}", fmt(summary["win_rate"], 0, "%"),
                delta_color="off")
    c[1].metric("K/D", fmt(summary["kd"], 2))
    c[2].metric("ACS", fmt(summary["acs"], 0))
    c[3].metric("ADR", fmt(summary["adr"], 0))
    c[4].metric("HS%", fmt(summary["hs_pct"], 1, "%"))
    c[5].metric("KAST", fmt(summary["kast_pct"], 0, "%"))

    hist = pd.DataFrame(res.mmr_history)
    if not hist.empty:
        hist["date"] = pd.to_datetime(hist["date"], utc=True, errors="coerce")
        hist = hist.dropna(subset=["date"]).sort_values("date")
        st.subheader("RR trend")
        st.caption("Continuous rank rating (the `elo` field of HenrikDev MMR history) over time.")
        st.line_chart(hist.set_index("date")["elo"], y_label="Rank rating (elo)")
        st.caption("RR change per game")
        st.bar_chart(hist.set_index("date")["last_change"], y_label="RR change")
    else:
        st.info("No RR history available (placements, or the API returned none).")

    st.subheader("Rolling 5-game trend")
    trend = stats.rolling_trend(mdf).set_index("game_no")
    if trend.dropna().empty:
        st.caption("Needs at least 5 games.")
    else:
        cols = st.columns(4)
        for col, (key, label) in zip(cols, [("acs_rolling", "ACS"), ("adr_rolling", "ADR"),
                                            ("hs_pct_rolling", "HS%"), ("win_rate_rolling", "Win rate %")]):
            col.caption(label)
            col.line_chart(trend[key], y_label=label, x_label="Game #")

    st.subheader("By side")
    st.dataframe(stats.side_table(rdf).round(1), hide_index=True)
    bad_sides = mdf[mdf["side_check"] != "verified"]
    st.caption("Sides are derived (Red attacks rounds 1-12, swap at 13, overtime alternates) and checked "
               f"against spike plants. {len(bad_sides)} match(es) could not be fully verified "
               "(see 'side_check' in the match list).")
    rp = stats.retake_postplant(rdf)
    st.caption(f"Retakes won: {fmt(rp.get('retake_win_pct'), 0, '%')} of {rp.get('retake_rounds', 0)} · "
               f"Post-plants won: {fmt(rp.get('postplant_win_pct'), 0, '%')} of {rp.get('postplant_rounds', 0)}")

    st.subheader("By buy type")
    st.dataframe(stats.buy_table(rdf).round(2), hide_index=True)
    st.caption(f"Tool-defined thresholds on YOUR loadout value at round start: pistol = rounds 1 & 13, "
               f"eco < {stats.ECO_MAX}, light < {stats.LIGHT_MAX}, full ≥ {stats.LIGHT_MAX}.")

    with st.expander("Stat definitions"):
        st.markdown(f"""
- **ACS** = combat score ÷ rounds · **ADR** = damage dealt ÷ rounds · **HS%** = head ÷ (head + body + leg) shots
- **First kill / first death** = the earliest kill event of the round
- **KAST** = % of rounds with a Kill, Assist, Survived or Traded. **Traded = a teammate killed the player who
  killed you within {stats.KAST_TRADE_WINDOW_MS // 1000} seconds of your death.** A Sage revive still counts as a death
  (the API has no revive event).
- **Entry success** = first kills ÷ (first kills + first deaths)
- **Ability casts / round** from the API's per-player cast counts (falls back to per-round counts)
- **Low sample** = fewer than {stats.LOW_SAMPLE_GAMES} games. Totals are round-weighted, not averages of game averages.
""")

# --------------------------------------------------------------------------- agents / maps
LS = "⚠ low sample"


def show_group(df: pd.DataFrame, key: str):
    df = df.copy()
    df[LS] = df.pop("low_sample").map({True: "yes", False: ""})
    if key == "agent":
        df.insert(1, "role", df["agent"].map(stats.role_of))
    st.dataframe(rnd(df, 2), hide_index=True, use_container_width=True)


with tab_agents:
    st.subheader("Agents")
    show_group(stats.group_table(mdf, "agent"), "agent")
    st.caption("Win rate always shown with its game count. Anything under 5 games is flagged low sample.")

with tab_maps:
    st.subheader("Maps")
    show_group(stats.group_table(mdf, "map"), "map")
    sbg = stats.side_by_group(rdf, "map")
    if not sbg.empty:
        st.subheader("Round win % by side per map")
        piv = sbg.pivot(index="map", columns="side", values=["round_win_pct", "rounds"])
        piv.columns = [f"{a}_{b}" for a, b in piv.columns]
        st.dataframe(piv.round(1), use_container_width=True)

# --------------------------------------------------------------------------- matches
with tab_matches:
    st.subheader("Matches (newest first)")
    view = mdf.sort_values("started_at", ascending=False)
    cols = ["started_at", "map", "agent", "result", "score", "kills", "deaths", "assists", "acs", "adr",
            "hs_pct", "first_kills", "first_deaths", "kast_pct", "plants", "defuses", "avg_loadout",
            "casts_per_round", "rr_change", "side_check", "tracker_url"]
    st.dataframe(rnd(view[cols], 1), hide_index=True, use_container_width=True,
                 column_config={"tracker_url": st.column_config.LinkColumn("tracker.gg", display_text="open"),
                                "started_at": st.column_config.DatetimeColumn("started", format="YYYY-MM-DD HH:mm")})
    labels = {f"{r.started_at:%Y-%m-%d %H:%M} · {r.map} · {r.agent} · {r.result} {r.score}": r.match_id
              for r in view.itertuples()}
    pick = st.selectbox("Drill into a match", list(labels))
    if pick:
        mid = labels[pick]
        row = view[view["match_id"] == mid].iloc[0]
        st.link_button("Open this match on tracker.gg", row["tracker_url"])
        c = st.columns(5)
        c[0].metric("K/D/A", f"{row.kills}/{row.deaths}/{row.assists}")
        c[1].metric("ACS", fmt(row.acs, 0))
        c[2].metric("ADR", fmt(row.adr, 0))
        c[3].metric("KAST", fmt(row.kast_pct, 0, "%"))
        c[4].metric("RR", "n/a" if pd.isna(row.rr_change) else f"{int(row.rr_change):+d}")
        rounds = rdf[rdf["match_id"] == mid][["round", "side", "won", "buy_type", "loadout", "kills", "died",
                                              "assisted", "traded", "kast", "first_kill", "first_death",
                                              "score", "damage", "ability_casts", "planted", "defused"]]
        st.dataframe(rounds, hide_index=True, use_container_width=True)

# --------------------------------------------------------------------------- tips
with tab_tips:
    st.subheader("Top 5 tips")
    st.caption(f"Ranked by impact = relative gap × √(games in the smaller group). A tip needs a gap of at least "
               f"{MIN_REL_GAP:.0%} and {MIN_GAMES}+ games on each side of the comparison. Every comparison is "
               "against your own numbers; no rank benchmarks are used.")

    def tip_card(i, t):
        with st.container(border=True):
            flag = "  ·  ⚠ low sample" if t.low_sample else ""
            st.markdown(f"**{i}. {t.title}**  \n`{t.category}` · impact {t.impact:.2f}{flag}")
            st.markdown(f"- **What the data shows:** {t.data_shows}\n"
                        f"- **What it likely means _(interpretation)_:** {t.interpretation}\n"
                        f"- **Practice next session:** {t.practice}")

    if not tips:
        st.info("No gaps big enough to trigger a tip. Load more matches for more comparisons.")
    for i, t in enumerate(tips[:5], 1):
        tip_card(i, t)
    if len(tips) > 5:
        with st.expander(f"{len(tips) - 5} more tips"):
            for i, t in enumerate(tips[5:], 6):
                tip_card(i, t)

# --------------------------------------------------------------------------- export
with tab_export:
    safe = res.riot_id.replace("#", "_").replace(" ", "_")
    st.download_button("Download per-match CSV", matches_csv(mdf), file_name=f"{safe}_matches.csv",
                       mime="text/csv")
    md = markdown_report(res.riot_id, res.region, res.mmr, mdf, rdf, tips, agent_filter)
    st.download_button("Download improvement report (Markdown)", md, file_name=f"{safe}_report.md",
                       mime="text/markdown")
    with st.expander("Preview report"):
        st.markdown(md)
