"""Streamlit UI (works locally and as a public website).  Run:  streamlit run app.py"""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import stats
import ui
from access import Cooldown, choose_key, looks_like_key, read_setting, SITE_COOLDOWN_S_DEFAULT, SITE_MAX_MATCHES_DEFAULT
from api_client import (REGIONS, PLATFORMS, HenrikClient, ValorantAPIError, tracker_profile_url)
from cache import Cache
from report import markdown_report, matches_csv
from sync import MAX_MATCHES, sync_player
from tips import generate_tips, MIN_REL_GAP, MIN_GAMES

load_dotenv()
st.set_page_config(page_title="VALORANT Coach", page_icon="🎯", layout="wide")
st.markdown(ui.flat(ui.CSS), unsafe_allow_html=True)

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


def show(markup: str, where=st) -> None:
    where.markdown(ui.flat(markup), unsafe_allow_html=True)


# --------------------------------------------------------------------------- sidebar
qp = st.query_params
st.sidebar.markdown("## 🎯 VALORANT Coach")
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
    show(f"""
<div class="vc-hero"><div>
  <div class="vc-name">VALORANT Coach</div>
  <div class="vc-sub" style="font-size:1.05rem;max-width:640px">Free stats and <b>data-backed tips to climb</b>,
  built from your own recent competitive matches.</div>
</div></div>""")
    c1, c2, c3 = st.columns(3)
    show('<div class="vc-card"><b>1 · Enter your Riot ID</b><br><span class="vc-sub">Name#Tag and region in '
         'the sidebar, then <b>Load / refresh</b>. The first load takes a minute or two.</span></div>', c1)
    show('<div class="vc-card"><b>2 · Read your top tips</b><br><span class="vc-sub">Each tip shows the numbers '
         'behind it, what they likely mean, and one drill for your next session.</span></div>', c2)
    show('<div class="vc-card"><b>3 · Track progress</b><br><span class="vc-sub">RR trend, rolling form, '
         'agents, maps, clutches and a round-by-round view of every match.</span></div>', c3)
    st.caption("Tips compare you only with yourself (your other agents, maps, earlier games and sides), never with "
               "made-up rank averages.")
    if not SITE_KEY:
        st.warning("This site needs your own free HenrikDev API key: open **Use your own API key** in the sidebar.")
    show(ui.footer_html(RIOT_LEGAL))
    st.stop()

for w in res.warnings:
    st.warning(w)
if res.api_calls:
    st.sidebar.caption(f"Last refresh: {res.api_calls} API calls, {res.new_matches} new matches stored.")

puuid = res.account["puuid"]
all_mdf, _ = stats.build_frames(res.matches, puuid, res.mmr_history)
st.sidebar.subheader("Filters")
agents = sorted(all_mdf["agent"].dropna().unique()) if not all_mdf.empty else []
maps = sorted(all_mdf["map"].dropna().unique()) if not all_mdf.empty else []
agent_filter = st.sidebar.selectbox("Agent", ["All agents"] + agents)
map_filter = st.sidebar.selectbox("Map", ["All maps"] + maps)
agent_filter = None if agent_filter == "All agents" else agent_filter
map_filter = None if map_filter == "All maps" else map_filter
mdf, rdf = stats.build_frames(res.matches, puuid, res.mmr_history, agent_filter=agent_filter)
if map_filter and not mdf.empty:
    mdf = mdf[mdf["map"] == map_filter].reset_index(drop=True)
    rdf = rdf[rdf["map"] == map_filter].reset_index(drop=True)

summary = stats.summarize(mdf)
show(ui.hero_html(res.riot_id, res.region, res.mmr, summary, stats.recent_form(mdf), tracker_profile_url(res.riot_id),
                         len(mdf), agent_filter, map_filter))
if mdf.empty:
    st.info("No competitive matches found for this selection.")
    st.stop()

tips = generate_tips(mdf, rdf)
if tips:
    show(ui.focus_html(tips[0]))

tab_over, tab_tips, tab_matches, tab_agents, tab_maps, tab_combat, tab_export = st.tabs(
    ["📊 Overview", "💡 Tips", "🎮 Matches", "🧑‍🚀 Agents", "🗺️ Maps", "🎯 Combat", "⬇️ Export"])

# --------------------------------------------------------------------------- overview
with tab_over:
    show(ui.overview_kpis(summary))

    hist = ui.rr_frame(res.mmr_history)
    st.subheader("Rank progress")
    if hist.empty:
        st.info("No RR history available (placements, or the API returned none).")
    else:
        c1, c2 = st.columns(2)
        c1.vega_lite_chart(hist, ui.elo_spec(), use_container_width=True, theme=None)
        c2.vega_lite_chart(hist, ui.rr_change_spec(), use_container_width=True, theme=None)
        st.caption("Rating = HenrikDev's continuous rank rating (`elo`). Blue bars = RR gained, red = RR lost.")

    st.subheader("Rolling 5-game form")
    trend = stats.rolling_trend(mdf).dropna()
    if trend.empty:
        st.caption("Needs at least 5 games.")
    else:
        cols = st.columns(4)
        for col, (key, label) in zip(cols, [("acs_rolling", "ACS"), ("adr_rolling", "ADR"),
                                            ("hs_pct_rolling", "Headshot %"), ("win_rate_rolling", "Win rate %")]):
            col.vega_lite_chart(trend, ui.trend_spec(key, label), use_container_width=True, theme=None)

    st.subheader("Attack vs defense")
    side = stats.side_table(rdf)
    if not side.empty:
        s_idx = side.set_index("side")
        items = []
        for sd in ("attack", "defense"):
            if sd in s_idx.index:
                r = s_idx.loc[sd]
                items.append((f"{sd} rounds won", ui.num(r.round_win_pct, 0, "%"),
                              f"{int(r.rounds)} rounds · KAST {ui.num(r.kast_pct, 0, '%')} · FD {ui.num(r.fd_pct, 0, '%')}"))
        rp = stats.retake_postplant(rdf)
        items.append(("Post-plant wins", ui.num(rp.get("postplant_win_pct"), 0, "%"), f"{rp.get('postplant_rounds', 0)} rounds"))
        items.append(("Retake wins", ui.num(rp.get("retake_win_pct"), 0, "%"), f"{rp.get('retake_rounds', 0)} rounds"))
        show(ui.kpis_html(items))
    unverified = int((mdf["side_check"] != "verified").sum())
    st.caption("Sides are derived (Red attacks rounds 1-12, swap at 13, overtime alternates) and checked against "
               f"spike plants. {unverified} match(es) could not be fully verified.")

    st.subheader("By buy type")
    st.dataframe(rnd(stats.buy_table(rdf), 2), hide_index=True, use_container_width=True)
    st.caption(f"Tool-defined thresholds on YOUR loadout value at round start: pistol = rounds 1 & 13, "
               f"eco < {stats.ECO_MAX}, light < {stats.LIGHT_MAX}, full ≥ {stats.LIGHT_MAX}.")

    with st.expander("How every stat is calculated"):
        st.markdown(f"""
- **ACS** = combat score ÷ rounds · **ADR** = damage dealt ÷ rounds · **HS%** = head ÷ (head + body + leg) shots
- **First kill / first death** = the earliest kill event of the round · **Entry success** = FK ÷ (FK + FD)
- **KAST** = % of rounds with a Kill, Assist, Survived or Traded. **Traded = a teammate killed the player who
  killed you within {stats.KAST_TRADE_WINDOW_MS // 1000} seconds of your death.** A Sage revive still counts as a death.
- **Clutch** = you became your team's last player alive with enemies still alive (1vX); won if your team won the round.
- **Multi-kill** = 2+ kills by you in one round (5 = ace).
- **Low sample** = fewer than {stats.LOW_SAMPLE_GAMES} games. Totals are round-weighted, not averages of game averages.
""")

# --------------------------------------------------------------------------- tips
with tab_tips:
    st.caption(f"Ranked by impact = relative gap × √(games in the smaller group). A tip needs a gap of at least "
               f"{MIN_REL_GAP:.0%} and {MIN_GAMES}+ games on each side. Every comparison is against your own numbers.")
    if not tips:
        st.info("No gaps big enough to trigger a tip yet. Load more matches for more comparisons.")
    max_imp = max((t.impact for t in tips), default=0)
    show("".join(ui.tip_html(i, t, max_imp) for i, t in enumerate(tips[:5], 1)))
    if len(tips) > 5:
        with st.expander(f"{len(tips) - 5} more tips"):
            show("".join(ui.tip_html(i, t, max_imp) for i, t in enumerate(tips[5:], 6)))

# --------------------------------------------------------------------------- matches
with tab_matches:
    view = mdf.sort_values("started_at", ascending=False)
    st.caption("Newest first. Open a match for its round-by-round timeline.")
    for r in view.itertuples():
        with st.expander(ui.match_label(r)):
            c = st.columns([1, 1, 1, 1, 1, 1.4])
            c[0].metric("ACS", ui.num(r.acs))
            c[1].metric("ADR", ui.num(r.adr))
            c[2].metric("HS%", ui.num(r.hs_pct, 0, "%"))
            c[3].metric("KAST", ui.num(r.kast_pct, 0, "%"))
            c[4].metric("FK / FD", f"{r.first_kills} / {r.first_deaths}")
            c[5].link_button("Open on tracker.gg ↗", r.tracker_url, use_container_width=True)
            show(ui.round_timeline_html(rdf[rdf["match_id"] == r.match_id]))
    with st.expander("All matches as a table"):
        cols = ["started_at", "map", "agent", "result", "score", "kills", "deaths", "assists", "acs", "adr",
                "hs_pct", "first_kills", "first_deaths", "kast_pct", "k3", "k4", "aces", "clutches_won",
                "plants", "defuses", "avg_loadout", "casts_per_round", "rr_change", "side_check", "tracker_url"]
        st.dataframe(rnd(view[cols], 1), hide_index=True, use_container_width=True,
                     column_config={"tracker_url": st.column_config.LinkColumn("tracker.gg", display_text="open"),
                                    "started_at": st.column_config.DatetimeColumn("started", format="YYYY-MM-DD HH:mm")})

# --------------------------------------------------------------------------- agents / maps
LS = "⚠ low sample"


def show_table(df: pd.DataFrame, key: str):
    df = df.copy()
    df[LS] = df.pop("low_sample").map({True: "yes", False: ""})
    if key == "agent":
        df.insert(1, "role", df["agent"].map(stats.role_of))
    st.dataframe(rnd(df, 2), hide_index=True, use_container_width=True)


with tab_agents:
    agent_tbl = stats.group_table(mdf, "agent")
    show(ui.entity_cards_html(agent_tbl, "agent"))
    st.caption("Win rate always shown with its game count; under 5 games is flagged low sample.")
    with st.expander("Full agent table"):
        show_table(agent_tbl, "agent")

with tab_maps:
    map_tbl = stats.group_table(mdf, "map")
    show(ui.entity_cards_html(map_tbl, "map", stats.side_by_group(rdf, "map")))
    st.caption("ATK / DEF = share of rounds your team won on each side of that map.")
    with st.expander("Full map table"):
        show_table(map_tbl, "map")

# --------------------------------------------------------------------------- combat
with tab_combat:
    c1, c2 = st.columns([1.3, 1])
    with c1:
        wt = stats.weapon_table(rdf)
        if wt.empty:
            st.info("No kill data.")
        else:
            st.vega_lite_chart(wt.head(12), ui.weapon_spec(), use_container_width=True, theme=None)
            st.caption("From kill events. Headshot % per weapon isn't available in the API data.")
    with c2:
        show(ui.kpis_html([
            ("2K rounds", str(int(mdf["k2"].sum())), ""), ("3K rounds", str(int(mdf["k3"].sum())), ""),
            ("4K rounds", str(int(mdf["k4"].sum())), ""), ("Aces", str(int(mdf["aces"].sum())), ""),
        ]))
        st.markdown("**Clutches**")
        ct = stats.clutch_table(rdf)
        if ct.empty:
            st.caption("No clutch situations (last player alive) in these games.")
        else:
            st.dataframe(rnd(ct, 0), hide_index=True, use_container_width=True)
            st.caption("Revives aren't in the data; a player who gets a kill after dying is treated as revived.")

# --------------------------------------------------------------------------- export
with tab_export:
    safe = res.riot_id.replace("#", "_").replace(" ", "_")
    c1, c2 = st.columns(2)
    c1.download_button("Download per-match CSV", matches_csv(mdf), file_name=f"{safe}_matches.csv",
                       mime="text/csv", use_container_width=True)
    md = markdown_report(res.riot_id, res.region, res.mmr, mdf, rdf, tips, agent_filter)
    c2.download_button("Download improvement report (Markdown)", md, file_name=f"{safe}_report.md",
                       mime="text/markdown", use_container_width=True)
    with st.expander("Preview report"):
        st.markdown(md)

show(ui.footer_html(RIOT_LEGAL))
