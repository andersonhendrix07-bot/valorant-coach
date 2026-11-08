"""Read-only client for the HenrikDev unofficial VALORANT API.

Docs: https://docs.henrikdev.xyz  (endpoint reference pages under /api-reference/valorant/)

Only documented endpoints are used:
  GET /valorant/v2/account/{name}/{tag}
  GET /valorant/v4/by-puuid/matches/{affinity}/{platform}/{puuid}?mode=&size=&start=
  GET /valorant/v4/match/{affinity}/{match_id}
  GET /valorant/v3/by-puuid/mmr/{affinity}/{platform}/{puuid}
  GET /valorant/v2/by-puuid/mmr-history/{affinity}/{platform}/{puuid}
  GET /valorant/v2/by-puuid/stored-mmr-history/{affinity}/{platform}/{puuid}?size=

Auth: API key in the `Authorization` header (the account-v2 reference lists an apiKey
scheme on that header with no prefix; `api_key` query param is the alternative).

Rate limiting (docs /general/rate-limiting): every API call costs 1 and every background
request HenrikDev makes to Riot costs +1. Response headers: X-RateLimit-Limit,
X-RateLimit-Remaining, X-RateLimit-Reset (seconds), Retry-After on 429.

This module never scrapes tracker.gg and never touches the game client.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

import requests

BASE_URL = "https://api.henrikdev.xyz"
REGIONS = ("na", "eu", "ap", "kr", "latam", "br")
PLATFORMS = ("pc", "console")
MAX_MATCHES_PAGE_SIZE = 10  # documented: values above 10 are capped at 10

# Riot ID rules (Riot support): game name 3-16 chars, tagline 3-5 alphanumerics.
_RIOT_ID_RE = re.compile(r"^\s*(?P<name>[^#]{3,16})#(?P<tag>[A-Za-z0-9]{3,5})\s*$")


# --------------------------------------------------------------------------- errors
class ValorantAPIError(Exception):
    """Base class. `user_message` is safe to show in the UI."""

    def __init__(self, user_message: str, *, status: int | None = None, code: int | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.status = status
        self.code = code


class InvalidRiotIdError(ValorantAPIError):
    pass


class AuthError(ValorantAPIError):
    pass


class AccountNotFoundError(ValorantAPIError):
    pass


class NotFoundError(ValorantAPIError):
    pass


class RateLimitError(ValorantAPIError):
    pass


class ApiDownError(ValorantAPIError):
    pass


class BadRequestError(ValorantAPIError):
    pass


# --------------------------------------------------------------------------- helpers
@dataclass(frozen=True)
class RiotId:
    name: str
    tag: str

    def __str__(self) -> str:
        return f"{self.name}#{self.tag}"


def parse_riot_id(raw: str) -> RiotId:
    if not raw or "#" not in raw:
        raise InvalidRiotIdError("Riot ID must look like Name#Tag (for example: Player#NA1).")
    m = _RIOT_ID_RE.match(raw)
    if not m:
        raise InvalidRiotIdError(
            "Invalid Riot ID. The name must be 3-16 characters and the tag 3-5 letters/numbers "
            "(for example: Player#NA1)."
        )
    return RiotId(m.group("name").strip(), m.group("tag").strip())


def tracker_profile_url(riot_id: RiotId | str) -> str:
    """Link only (no scraping). Format: /valorant/profile/riot/<Name%23Tag>/overview"""
    return f"https://tracker.gg/valorant/profile/riot/{quote(str(riot_id), safe='')}/overview"


def tracker_match_url(match_id: str) -> str:
    return f"https://tracker.gg/valorant/match/{quote(match_id, safe='')}"


def _first_error(payload: Any) -> tuple[int | None, str | None]:
    """HenrikDev errors: {"errors": [{"code": int, "message": str, "status": int, "details": ...}]}"""
    try:
        err = payload["errors"][0]
        return err.get("code"), err.get("message")
    except (TypeError, KeyError, IndexError, AttributeError):
        return None, None


# --------------------------------------------------------------------------- rate limiter
class RateLimiter:
    """Client-side sliding window (default 28 calls / 60 s, leaving headroom under 30)
    plus server-header awareness (X-RateLimit-Remaining / X-RateLimit-Reset)."""

    def __init__(self, max_calls: int = 28, period: float = 60.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.max_calls = max_calls
        self.period = period
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._blocked_until = 0.0

    def wait(self) -> None:
        now = self._clock()
        if now < self._blocked_until:
            self._sleep(self._blocked_until - now)
            now = self._clock()
        while self._calls and now - self._calls[0] >= self.period:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            delay = self.period - (now - self._calls[0]) + 0.05
            if delay > 0:
                self._sleep(delay)
            now = self._clock()
            while self._calls and now - self._calls[0] >= self.period:
                self._calls.popleft()
        self._calls.append(self._clock())

    def update_from_headers(self, headers: Any) -> None:
        remaining = _to_float(headers.get("X-RateLimit-Remaining"))
        reset = _to_float(headers.get("X-RateLimit-Reset"))
        if remaining is not None and reset is not None and remaining <= 0:
            self.block_for(reset)

    def block_for(self, seconds: float) -> None:
        self._blocked_until = max(self._blocked_until, self._clock() + max(0.0, seconds))


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- client
class HenrikClient:
    def __init__(self, api_key: str, *, base_url: str = BASE_URL, timeout: float = 20.0,
                 limiter: RateLimiter | None = None, session: requests.Session | None = None,
                 max_retries: int = 3, sleep: Callable[[float], None] = time.sleep):
        if not api_key or not api_key.strip():
            raise AuthError("No API key found. Put HENRIKDEV_API_KEY=... in your .env file.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.limiter = limiter or RateLimiter(sleep=sleep)
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": api_key.strip(),
            "Accept": "application/json",
            "User-Agent": "valorant-coach/1.0 (personal stats tool)",
        })
        self.max_retries = max_retries
        self._sleep = sleep
        self.calls_made = 0
        self.last_rate_headers: dict[str, str] = {}
        # One client (and so one key) can be shared by every visitor of the website.
        # Requests are serialized so the rate limiter sees calls in order and visitors queue fairly.
        self._lock = threading.Lock()

    # ---- core request -------------------------------------------------------------
    def _get(self, path: str, params: dict | None = None, *, account_lookup: bool = False) -> dict:
        with self._lock:
            return self._get_unlocked(path, params, account_lookup=account_lookup)

    def _get_unlocked(self, path: str, params: dict | None = None, *, account_lookup: bool = False) -> dict:
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            self.limiter.wait()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                attempt += 1
                if attempt > self.max_retries:
                    raise ApiDownError(
                        "Could not reach the HenrikDev API (network error or timeout). "
                        "Check your connection or try again later."
                    ) from exc
                self._sleep(2 ** attempt)
                continue
            self.calls_made += 1
            self.last_rate_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower().startswith(("x-ratelimit", "ratelimit", "retry-after", "x-cache"))
            }
            self.limiter.update_from_headers(resp.headers)

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise ApiDownError("The API returned a response that isn't valid JSON.") from exc

            try:
                payload = resp.json()
            except ValueError:
                payload = None
            code, message = _first_error(payload)
            status = resp.status_code

            if status == 429:
                attempt += 1
                wait = (_to_float(resp.headers.get("Retry-After"))
                        or _to_float(resp.headers.get("X-RateLimit-Reset"))
                        or 2 ** attempt * 5)
                if attempt > self.max_retries:
                    raise RateLimitError(
                        f"Rate limited by HenrikDev (429) after {self.max_retries} retries. "
                        f"Wait about {int(wait)} s and try again.", status=429, code=code)
                self.limiter.block_for(wait)
                continue
            if status in (500, 502, 503, 504):
                attempt += 1
                if attempt > self.max_retries:
                    raise ApiDownError(
                        f"HenrikDev API error {status}: {message or 'server unavailable'}. "
                        "The API or Riot's servers may be down; try again later.",
                        status=status, code=code)
                self._sleep(2 ** attempt)
                continue
            if status == 401:
                raise AuthError("API key missing or not accepted (401). Check HENRIKDEV_API_KEY in .env.",
                                status=status, code=code)
            if status == 403:
                raise AuthError("API key is invalid or lacks access (403). Generate a key at "
                                "https://api.henrikdev.xyz/dashboard/ and update .env.",
                                status=status, code=code)
            if status == 404:
                if code == 22 or account_lookup:
                    raise AccountNotFoundError(
                        "Account not found. Check the spelling of Name#Tag (it is case-insensitive "
                        "but must be exact) and the region.", status=status, code=code)
                if code == 23:
                    raise NotFoundError("HenrikDev couldn't determine this account's region yet "
                                        "(play any match, then retry).", status=status, code=code)
                if code == 25:
                    raise NotFoundError("No MMR data for this account (unranked this act?).",
                                        status=status, code=code)
                raise NotFoundError(f"Not found (404): {message or path}", status=status, code=code)
            if status == 400:
                raise BadRequestError(f"Bad request (400): {message or 'invalid parameter'}",
                                      status=status, code=code)
            raise ApiDownError(f"Unexpected HTTP {status}: {message or ''}".strip(),
                               status=status, code=code)

    # ---- endpoints ----------------------------------------------------------------
    def get_account(self, riot_id: RiotId) -> dict:
        path = f"/valorant/v2/account/{quote(riot_id.name, safe='')}/{quote(riot_id.tag, safe='')}"
        return self._get(path, account_lookup=True)["data"]

    def get_matches(self, region: str, puuid: str, *, platform: str = "pc", mode: str = "competitive",
                    size: int = 10, start: int = 0) -> list[dict]:
        _check_region(region)
        size = max(1, min(int(size), MAX_MATCHES_PAGE_SIZE))
        path = f"/valorant/v4/by-puuid/matches/{region}/{platform}/{puuid}"
        return self._get(path, {"mode": mode, "size": size, "start": start}).get("data") or []

    def get_match(self, region: str, match_id: str) -> dict:
        _check_region(region)
        return self._get(f"/valorant/v4/match/{region}/{quote(match_id, safe='')}")["data"]

    def get_mmr(self, region: str, puuid: str, *, platform: str = "pc") -> dict:
        _check_region(region)
        return self._get(f"/valorant/v3/by-puuid/mmr/{region}/{platform}/{puuid}")["data"]

    def get_mmr_history(self, region: str, puuid: str, *, platform: str = "pc") -> list[dict]:
        _check_region(region)
        data = self._get(f"/valorant/v2/by-puuid/mmr-history/{region}/{platform}/{puuid}")["data"]
        return data.get("history") or []

    def get_stored_mmr_history(self, region: str, puuid: str, *, platform: str = "pc",
                               size: int = 50) -> list[dict]:
        _check_region(region)
        path = f"/valorant/v2/by-puuid/stored-mmr-history/{region}/{platform}/{puuid}"
        return self._get(path, {"size": size}).get("data") or []


def _check_region(region: str) -> None:
    if region not in REGIONS:
        raise BadRequestError(f"Unknown region '{region}'. Use one of: {', '.join(REGIONS)}.")
