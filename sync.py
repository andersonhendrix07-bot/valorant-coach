"""Fetch strategy: spend as few API calls as possible and never re-download a stored match.

1. Account lookup (cached 24 h).
2. Current MMR (1 call) and MMR history: live v2 + stored v2 (2 calls). MMR history is a
   cheap index of competitive match IDs *and* gives RR change per game.
3. Download only the match IDs from that index that are not in SQLite (1 call each).
4. If we still have fewer competitive matches than requested (e.g. placement games that
   have no RR entry), fall back to the competitive match-history endpoint (10 per page)
   and store any new matches it returns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from api_client import (HenrikClient, NotFoundError, ValorantAPIError, parse_riot_id,
                        MAX_MATCHES_PAGE_SIZE)
from cache import Cache

COMPETITIVE = "competitive"
MAX_MATCHES = 50

Progress = Callable[[float, str], None]


@dataclass
class SyncResult:
    account: dict
    riot_id: str
    region: str
    mmr: dict | None
    matches: list[dict]
    mmr_history: list[dict]
    new_matches: int = 0
    api_calls: int = 0
    warnings: list[str] = field(default_factory=list)


def _noop(_f: float, _t: str) -> None:
    pass


def _merge_history(*lists: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for lst in lists:
        for e in lst or []:
            mid = e.get("match_id")
            if mid and mid not in seen:
                seen[mid] = e
    return sorted(seen.values(), key=lambda e: e.get("date") or "", reverse=True)


def sync_player(client: HenrikClient | None, cache: Cache, riot_id_raw: str, region: str,
                n_matches: int = 20, *, platform: str = "pc", refresh: bool = True,
                progress: Progress = _noop) -> SyncResult:
    """`client=None` or `refresh=False` = offline mode: use only what is already cached."""
    n_matches = max(1, min(int(n_matches), MAX_MATCHES))
    rid = parse_riot_id(riot_id_raw)
    warnings: list[str] = []
    calls_before = client.calls_made if client else 0
    online = refresh and client is not None

    # 1. account
    progress(0.02, "Looking up account…")
    account = cache.get_account(str(rid))
    if account is None:
        if client is None:
            raise ValorantAPIError("This account isn't cached yet and no API key is configured.")
        account = client.get_account(rid)
        cache.put_account(str(rid), account)
    puuid = account["puuid"]
    acct_region = (account.get("region") or "").lower()
    if acct_region and acct_region != region:
        warnings.append(f"HenrikDev reports this account's region as '{acct_region}', "
                        f"but '{region}' was selected. Results may be empty or wrong.")

    mmr = None
    new = 0
    if online:
        # 2. MMR
        progress(0.08, "Fetching current rank…")
        try:
            mmr = client.get_mmr(region, puuid, platform=platform)
            cache.put_mmr_current(puuid, mmr)
        except NotFoundError as e:
            warnings.append(f"Current rank unavailable: {e.user_message}")

        progress(0.14, "Fetching RR history…")
        live, stored = [], []
        try:
            live = client.get_mmr_history(region, puuid, platform=platform)
        except NotFoundError as e:
            warnings.append(f"Live MMR history unavailable: {e.user_message}")
        try:
            stored = client.get_stored_mmr_history(region, puuid, platform=platform, size=MAX_MATCHES)
        except NotFoundError as e:
            warnings.append(f"Stored MMR history unavailable: {e.user_message}")
        history = _merge_history(live, stored)
        cache.put_mmr_history(puuid, history)

        # 3. only fetch IDs we don't have
        wanted = [e["match_id"] for e in history[:n_matches]]
        missing = cache.missing_match_ids(wanted)
        for i, mid in enumerate(missing, 1):
            progress(0.2 + 0.6 * i / max(1, len(missing)), f"Downloading match {i}/{len(missing)}…")
            try:
                match = client.get_match(region, mid)
            except NotFoundError:
                warnings.append(f"Match {mid} is no longer available from the API; skipped.")
                continue
            cache.put_match(match)
            new += 1

        # 4. fallback: competitive match-history endpoint
        have = len(cache.get_player_matches(puuid, queue_id=COMPETITIVE, limit=n_matches))
        start = 0
        while have < n_matches and start < n_matches + MAX_MATCHES_PAGE_SIZE:
            progress(0.85, f"Filling gaps from match history (page {start // MAX_MATCHES_PAGE_SIZE + 1})…")
            page = client.get_matches(region, puuid, platform=platform, mode=COMPETITIVE,
                                      size=MAX_MATCHES_PAGE_SIZE, start=start)
            for m in page:
                mid = (m.get("metadata") or {}).get("match_id")
                if mid and not cache.has_match(mid):
                    cache.put_match(m)
                    new += 1
            if len(page) < MAX_MATCHES_PAGE_SIZE:
                break
            start += MAX_MATCHES_PAGE_SIZE
            have = len(cache.get_player_matches(puuid, queue_id=COMPETITIVE, limit=n_matches))
    else:
        cached = cache.get_mmr_current(puuid)
        mmr = cached[0] if cached else None

    progress(0.95, "Loading matches from cache…")
    matches = cache.get_player_matches(puuid, queue_id=COMPETITIVE, limit=n_matches)
    if len(matches) < n_matches:
        warnings.append(f"Only {len(matches)} competitive matches available (asked for {n_matches}).")
    progress(1.0, "Done")
    return SyncResult(
        account=account, riot_id=f"{account.get('name', rid.name)}#{account.get('tag', rid.tag)}",
        region=region, mmr=mmr, matches=matches, mmr_history=cache.get_mmr_history(puuid),
        new_matches=new, api_calls=(client.calls_made - calls_before) if client else 0,
        warnings=warnings)
