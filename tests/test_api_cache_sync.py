import json

import pytest

import api_client as api
from cache import Cache
from conftest import ME, load
from report import markdown_report, matches_csv
import stats
import sync
import tips


# --------------------------------------------------------------------------- riot id + links
@pytest.mark.parametrize("raw,name,tag", [("Hendrix#NA1", "Hendrix", "NA1"), (" Big Name#1234 ", "Big Name", "1234")])
def test_parse_riot_id_ok(raw, name, tag):
    rid = api.parse_riot_id(raw)
    assert (rid.name, rid.tag) == (name, tag)


@pytest.mark.parametrize("raw", ["", "NoTag", "ab#NA1", "Hendrix#N", "Hendrix#TOOLONG", "Hendrix#N@1"])
def test_parse_riot_id_bad(raw):
    with pytest.raises(api.InvalidRiotIdError):
        api.parse_riot_id(raw)


def test_tracker_links():
    assert api.tracker_profile_url("C9 leaf#XITER") == \
        "https://tracker.gg/valorant/profile/riot/C9%20leaf%23XITER/overview"
    assert api.tracker_match_url("abc") == "https://tracker.gg/valorant/match/abc"


# --------------------------------------------------------------------------- client error mapping
class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


def client(responses, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    lim = api.RateLimiter(max_calls=1000, sleep=sleeps.append)
    return api.HenrikClient("KEY", session=FakeSession(responses), limiter=lim, sleep=sleeps.append)


def err(code, status):
    return {"errors": [{"code": code, "message": "m", "status": status}]}


def test_auth_header_and_url():
    c = client([FakeResp(200, {"status": 200, "data": {"puuid": "p"}})])
    c.get_account(api.RiotId("Big Name", "NA1"))
    assert c.session.headers["Authorization"] == "KEY"
    assert c.session.calls[0][0] == "https://api.henrikdev.xyz/valorant/v2/account/Big%20Name/NA1"


@pytest.mark.parametrize("status,body,exc", [
    (401, err(0, 401), api.AuthError),
    (403, err(0, 403), api.AuthError),
    (404, err(22, 404), api.AccountNotFoundError),
    (400, err(6, 400), api.BadRequestError),
])
def test_error_mapping(status, body, exc):
    with pytest.raises(exc) as e:
        client([FakeResp(status, body)]).get_account(api.RiotId("abc", "NA1"))
    assert e.value.user_message


def test_match_404_is_not_account_error():
    with pytest.raises(api.NotFoundError) as e:
        client([FakeResp(404, err(26, 404))]).get_match("na", "x")
    assert not isinstance(e.value, api.AccountNotFoundError)


def test_429_backs_off_using_retry_after_then_succeeds():
    sleeps = []
    t = [0.0]
    lim = api.RateLimiter(max_calls=1000, clock=lambda: t[0], sleep=lambda s: (sleeps.append(s), t.__setitem__(0, t[0] + s)))
    c = api.HenrikClient("KEY", limiter=lim, sleep=sleeps.append, session=FakeSession([
        FakeResp(429, err(0, 429), {"Retry-After": "7"}),
        FakeResp(200, {"status": 200, "data": []}),
    ]))
    assert c.get_matches("na", ME) == []
    assert sleeps and sleeps[0] == pytest.approx(7)


def test_429_gives_up_after_retries():
    with pytest.raises(api.RateLimitError):
        client([FakeResp(429, err(0, 429), {"Retry-After": "1"})] * 5).get_mmr("na", ME)


def test_5xx_retries_then_api_down():
    with pytest.raises(api.ApiDownError):
        client([FakeResp(503)] * 5).get_mmr("na", ME)


def test_connection_error_is_api_down():
    import requests

    class Boom(FakeSession):
        def get(self, *a, **k):
            raise requests.ConnectionError("down")
    c = api.HenrikClient("KEY", session=Boom([]), limiter=api.RateLimiter(sleep=lambda s: None), sleep=lambda s: None)
    with pytest.raises(api.ApiDownError):
        c.get_mmr("na", ME)


def test_missing_key():
    with pytest.raises(api.AuthError):
        api.HenrikClient("  ")


def test_bad_region():
    with pytest.raises(api.BadRequestError):
        client([]).get_match("xx", "id")


def test_size_capped_at_10():
    c = client([FakeResp(200, {"status": 200, "data": []})])
    c.get_matches("na", ME, size=50)
    assert c.session.calls[0][1]["size"] == 10 and c.session.calls[0][1]["mode"] == "competitive"


# --------------------------------------------------------------------------- rate limiter
def test_rate_limiter_window():
    t = [0.0]
    slept = []
    lim = api.RateLimiter(max_calls=3, period=60, clock=lambda: t[0],
                          sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    for _ in range(3):
        lim.wait()
    assert slept == []
    lim.wait()  # 4th call within the window must wait ~60 s
    assert slept and slept[0] == pytest.approx(60.05)


def test_rate_limiter_respects_remaining_zero():
    t = [0.0]
    slept = []
    lim = api.RateLimiter(clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    lim.update_from_headers({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "12"})
    lim.wait()
    assert slept[0] == pytest.approx(12)


# --------------------------------------------------------------------------- cache
def test_cache_roundtrip(tmp_path):
    c = Cache(tmp_path / "t.sqlite3")
    a, b = load("match_a_win_jett.json"), load("match_b_loss_sova_ot.json")
    c.put_match(a)
    assert c.has_match(a["metadata"]["match_id"])
    assert c.missing_match_ids([a["metadata"]["match_id"], "zzz"]) == ["zzz"]
    c.put_match(b)
    got = c.get_player_matches(ME)
    assert [m["metadata"]["map"]["name"] for m in got] == ["Bind", "Ascent"]   # newest first
    from cache import strip_positions
    assert got[1] == strip_positions(a)                                       # positions dropped, rest identical
    assert "player_locations" not in json.dumps(got[1])
    assert stats.match_row(got[1], ME) == stats.match_row(a, ME)              # stats unaffected
    c.put_mmr_history(ME, load("mmr_history.json"))
    assert len(c.get_mmr_history(ME)) == 2
    c.put_account("Hendrix#NA1", {"puuid": ME, "region": "na"})
    assert c.get_account("hendrix#na1")["puuid"] == ME


# --------------------------------------------------------------------------- sync
class FakeClient:
    def __init__(self):
        self.calls_made = 0
        self.fetched = []
        self.matches = {m["metadata"]["match_id"]: m for m in
                        (load("match_a_win_jett.json"), load("match_b_loss_sova_ot.json"))}

    def _c(self):
        self.calls_made += 1

    def get_account(self, rid):
        self._c(); return {"puuid": ME, "name": "Hendrix", "tag": "NA1", "region": "na"}

    def get_mmr(self, region, puuid, platform="pc"):
        self._c(); return {"current": {"tier": {"id": 15, "name": "Gold 1"}, "rr": 40}}

    def get_mmr_history(self, region, puuid, platform="pc"):
        self._c(); return load("mmr_history.json")[:1]

    def get_stored_mmr_history(self, region, puuid, platform="pc", size=50):
        self._c(); return load("mmr_history.json")

    def get_match(self, region, mid):
        self._c(); self.fetched.append(mid); return self.matches[mid]

    def get_matches(self, *a, **k):
        self._c(); return []


def test_sync_fetches_only_missing(tmp_path):
    cache = Cache(tmp_path / "s.sqlite3")
    cache.put_match(load("match_a_win_jett.json"))
    fc = FakeClient()
    res = sync.sync_player(fc, cache, "Hendrix#NA1", "na", 2)
    assert fc.fetched == ["bbbbbbbb-0000-0000-0000-000000000002"]
    assert res.new_matches == 1 and len(res.matches) == 2
    # second run: nothing new to download
    fc2 = FakeClient()
    sync.sync_player(fc2, cache, "Hendrix#NA1", "na", 2)
    assert fc2.fetched == []


def test_sync_offline_mode(tmp_path):
    cache = Cache(tmp_path / "o.sqlite3")
    sync.sync_player(FakeClient(), cache, "Hendrix#NA1", "na", 2)
    res = sync.sync_player(None, cache, "Hendrix#NA1", "na", 2, refresh=False)
    assert len(res.matches) == 2 and res.mmr["current"]["rr"] == 40 and res.api_calls == 0


def test_sync_region_mismatch_warning(tmp_path):
    res = sync.sync_player(FakeClient(), Cache(tmp_path / "w.sqlite3"), "Hendrix#NA1", "eu", 2)
    assert any("region" in w for w in res.warnings)


# --------------------------------------------------------------------------- report
def test_exports(match_a, match_b, mmr_hist):
    mdf, rdf = stats.build_frames([match_a, match_b], ME, mmr_hist)
    csv = matches_csv(mdf)
    assert csv.splitlines()[0].startswith("started_at,match_id,map,agent")
    assert len(csv.strip().splitlines()) == 3
    md = markdown_report("Hendrix#NA1", "na", {"current": {"tier": {"name": "Gold 1"}, "rr": 40}},
                         mdf, rdf, tips.generate_tips(mdf, rdf))
    for section in ("# VALORANT improvement report", "## Top tips", "## Agents", "## Maps", "## Sides",
                    "## Definitions", "within 5 seconds", "Gold 1 — 40 RR", "Hendrix%23NA1"):
        assert section in md
