import access


def test_choose_key_visitor_wins():
    assert access.choose_key("SITE", "  mine  ") == ("mine", "visitor")
    assert access.choose_key("SITE", "") == ("SITE", "site")
    assert access.choose_key(None, None) == (None, None)
    assert access.choose_key("  ", " ") == (None, None)


def test_looks_like_key():
    assert access.looks_like_key("HDEV-0a1b2c3d-1111-2222-3333-444455556666")
    assert not access.looks_like_key("short")
    assert not access.looks_like_key("has spaces in it 1234567890")
    assert not access.looks_like_key(None)


def test_read_setting_prefers_secrets(monkeypatch):
    monkeypatch.setenv("HENRIKDEV_API_KEY", "from-env")
    assert access.read_setting({"HENRIKDEV_API_KEY": "from-secrets"}, "HENRIKDEV_API_KEY") == "from-secrets"
    assert access.read_setting({}, "HENRIKDEV_API_KEY") == "from-env"
    assert access.read_setting(None, "MISSING_SETTING", 7) == 7

    class Raising:
        def __contains__(self, k):
            raise FileNotFoundError("no secrets.toml")
    assert access.read_setting(Raising(), "HENRIKDEV_API_KEY") == "from-env"


def test_cooldown():
    t = [100.0]
    cd = access.Cooldown(60, clock=lambda: t[0])
    assert cd.ready()
    cd.mark()
    t[0] += 20
    assert not cd.ready() and cd.remaining() == 40
    t[0] += 40
    assert cd.ready()


def test_client_requests_are_serialized():
    """The site key's client is shared by visitor threads; calls must not overlap."""
    import threading
    import time as _t
    import api_client as api

    active, peak = [0], [0]

    class SlowSession:
        headers = {}

        def get(self, url, params=None, timeout=None):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            _t.sleep(0.02)
            active[0] -= 1

            class R:
                status_code = 200
                headers = {}

                def json(self):
                    return {"status": 200, "data": {"current": {}}}
            return R()

    c = api.HenrikClient("KEY", session=SlowSession(), limiter=api.RateLimiter(max_calls=1000))
    threads = [threading.Thread(target=c.get_mmr, args=("na", "p")) for _ in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert peak[0] == 1 and c.calls_made == 6


def test_cache_is_thread_safe(tmp_path):
    import threading
    from cache import Cache
    from conftest import load
    c = Cache(tmp_path / "t.sqlite3")
    m = load("match_a_win_jett.json")
    errors = []

    def work(i):
        try:
            mm = dict(m, metadata=dict(m["metadata"], match_id=f"id-{i}"))
            c.put_match(mm)
            c.get_player_matches("me-puuid")
        except Exception as e:  # pragma: no cover
            errors.append(e)
    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors and len(c.get_player_matches("me-puuid")) == 20
