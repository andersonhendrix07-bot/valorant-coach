# VALORANT Coach

A VALORANT improvement website/tool. It pulls your competitive matches from the
[HenrikDev unofficial VALORANT API](https://docs.henrikdev.xyz), works out your stats and
gives you rule-based tips. Every tip shows the numbers that triggered it.

This tool is **read-only.** It only calls a web API. It does not scrape tracker.gg, read
game memory, hook the client, or touch Vanguard. The tracker.gg buttons are plain links
you can use to cross-check the numbers.

## 1. Get an API key
1. Go to the HenrikDev dashboard: https://api.henrikdev.xyz/dashboard/
   (the HenrikDev Discord, `#get-a-key`, also hands out Basic keys).
2. Open **API Keys** in the sidebar and fill in **Generate New Key**. Choose a VALORANT
   **Basic** key (30 requests/min).

## 2. Create `.env`
```bash
cp .env.example .env
# then edit .env:
HENRIKDEV_API_KEY=HDEV-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```
`.env` is git-ignored. The key is never written anywhere else.

## 3. Install (Python 3.11+)
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

## 4. Run
```bash
streamlit run app.py
```
1. Enter `Name#Tag`, a region and how many matches to load (1–50, default 20).
2. Click **Load / refresh**.
3. After loading, use the **Agent filter** in the sidebar.

Run the tests:
```bash
pytest -q
```

## Put it online for other people (Streamlit Community Cloud, free)
1. **Make a GitHub repo.** On github.com create a new repository (e.g. `valorant-coach`;
   public or private both work). Upload the contents of this folder, either by dragging the
   files into the browser ("uploading an existing file") or with:
   ```bash
   git remote add origin https://github.com/<you>/valorant-coach.git
   git push -u origin main
   ```
   `.env`, `.streamlit/secrets.toml` and the cache file are git-ignored, so your key never
   gets uploaded.
2. **Create the app.** Sign in at https://share.streamlit.io with GitHub, click **Create app**
   → **Yup, I have an app**, and pick your repo, branch `main`, main file `app.py`.
   Optionally choose a URL like `valorant-coach.streamlit.app`.
3. **Advanced settings.** Pick Python **3.12**. In **Secrets**, paste the contents of
   `.streamlit/secrets.toml.example` with your real key, or leave Secrets empty to make
   every visitor bring their own key. Click **Save** → **Deploy**.
4. Share the URL. A lookup can be shared as a link, e.g.
   `https://<your-app>.streamlit.app/?riot=Player%23NA1&region=na`.

**How the website handles API keys and load**
- **Visitors can paste their own key.** The field is in the sidebar. The key is kept only
  in that visitor's session memory. It is never written to disk, the cache, or the URL.
  Their lookups don't use your quota.
- **Your key, if you set one, is shared.** All visitors' calls go through one queue and one
  28-calls/min limiter. To keep one person from hogging it, a lookup on your key is capped
  at `SITE_MAX_MATCHES` (default 20). Each visitor can also refresh from the API only once
  per `SITE_COOLDOWN_S` (default 60 s). In between, they see cached data.
- **The match cache is shared.** A match downloaded for one player is reused when
  anyone else in that match looks themselves up. Position data is dropped to keep it
  small. On Community Cloud the cache resets whenever the app restarts, which is harmless:
  matches are simply downloaded again.
- **For a busy public site, ask HenrikDev for an Advanced key** from the dashboard. A
  shared Basic key (30/min) handles roughly one brand-new 20-match first load every 1–2 minutes.
  Repeat visits are almost free because of the cache.
- **Required disclaimer.** The footer shows Riot's standard "not endorsed by Riot Games"
  notice, which Riot asks fan sites to display.

## How API calls are kept low
The Basic key allows 30 calls per minute. HenrikDev also charges **+1 for every
background request it makes to Riot**, so a single fresh match can cost 2 or more.
To stay under the limit, the tool:

- **Caches everything.** Responses are stored in `valorant_cache.sqlite3` (set
  `VALCOACH_DB` to move it), so a match is downloaded only once.
- **Uses RR history as the index of match IDs.** That is 1–2 calls, and it also gives
  you RR change per game.
- **Downloads only the match IDs it doesn't have.**
- **Falls back to match history only when needed.** If you still have fewer matches
  than requested (for example placement games, which have no RR entry), it uses the
  competitive match-history endpoint. That endpoint returns at most 10 matches per call.
- **Paces itself.** It keeps a client-side limit of 28 calls/min, reads
  `X-RateLimit-Remaining` / `X-RateLimit-Reset`, and backs off on `429` using
  `Retry-After`.

Tick **Use cached data only** to reopen your stats without making any API calls.

## What is (and isn't) derivable
| Stat | Source | Notes |
|---|---|---|
| K/D/A, ACS, ADR, HS% | player match stats | ACS = score ÷ rounds, ADR = damage ÷ rounds |
| First kills / deaths | `kills[]` | earliest kill event of each round |
| KAST | `kills[]` | traded = a teammate kills your killer within 5 s. Sage revives aren't in the data, so a revived death still counts as a death |
| Side per round | **derived** | Red attacks rounds 1–12, Blue 13–24, overtime alternates. Checked against every spike plant; any mismatch shows in `side_check` |
| Plants / defuses | `rounds[].plant/defuse` | |
| Loadout / eco rounds | `rounds[].stats[].economy.loadout_value` | buy-type thresholds are this tool's own (eco < 2000, light < 3900) |
| Ability casts / round | `players[].ability_casts`, else per-round casts | |
| RR change | MMR history `last_change` | games missing from RR history show `n/a` |
| Multi-kills (2K–ace) | `kills[]` | kills by you in one round |
| Clutches (1vX) | `kills[]` | you became your team's last player alive with enemies alive; revives inferred when a dead player gets a kill |
| Kills by weapon | `kills[].weapon` | headshot % per weapon is not in the data |

Not available, so not shown: utility damage or flash assists by type, and positional
heatmaps (positions exist in the data but aren't used).

## Tips
- **Your own baselines only.** Tips compare you with yourself: other agents, other
  maps, earlier games, wins vs losses, and attack vs defense. They never use
  rank-average benchmarks.
- **Ranking.** Impact = relative gap × √(games in the smaller group). The top 5 are
  shown first.
- **Low sample.** Anything under 5 games is flagged "low sample".

## Files
```
access.py       website key rules (visitor key vs shared site key, cooldown)
api_client.py   HenrikDev client: auth, rate limiting, error mapping, tracker.gg links
cache.py        SQLite cache
sync.py         fetch only what's missing
stats.py        per-round / per-match stats and aggregates
roles.py        agent -> role map
tips.py         rule-based tips engine
report.py       CSV + Markdown export
app.py          Streamlit UI (layout)
ui.py           CSS, HTML cards and chart specs (escaped, testable)
tests/          pytest suite + JSON fixtures (synthetic, hand-checkable)
scripts/save_fixture.py   save a real match as a fixture for invariant tests
```

## Notes
- **The test fixtures are synthetic.** They follow the documented v4 schema, and
  every value in them was hand-designed so the expected stats can be checked on paper.
- **Testing against real data.** Run `python scripts/save_fixture.py na <match_id>`.
  `tests/test_real_fixtures.py` will then check invariants on the saved match,
  including that the side rule agrees with the plants.
- **New agents.** An agent not in `roles.py` shows up as role "Unknown" until you add it.
