"""Local SQLite cache. Raw API payloads are stored zlib-compressed so stats can be
recomputed offline and match IDs already stored are never fetched again."""
from __future__ import annotations

import functools
import json
import os
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Iterable

DEFAULT_DB = Path(os.getenv("VALCOACH_DB", Path(__file__).with_name("valorant_cache.sqlite3")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    riot_id_lower TEXT PRIMARY KEY,
    puuid TEXT NOT NULL,
    region TEXT,
    payload BLOB NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    started_at TEXT,
    queue_id TEXT,
    payload BLOB NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS player_matches (
    puuid TEXT NOT NULL,
    match_id TEXT NOT NULL REFERENCES matches(match_id),
    PRIMARY KEY (puuid, match_id)
);
CREATE TABLE IF NOT EXISTS mmr_history (
    puuid TEXT NOT NULL,
    match_id TEXT NOT NULL,
    date TEXT,
    last_change INTEGER,
    rr INTEGER,
    elo INTEGER,
    tier_name TEXT,
    map_name TEXT,
    season_short TEXT,
    payload BLOB NOT NULL,
    PRIMARY KEY (puuid, match_id)
);
CREATE TABLE IF NOT EXISTS mmr_current (
    puuid TEXT PRIMARY KEY,
    payload BLOB NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_matches_started ON matches(started_at);
"""


def _pack(obj) -> bytes:
    return zlib.compress(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def _unpack(blob: bytes):
    return json.loads(zlib.decompress(blob).decode("utf-8"))


def strip_positions(obj):
    """Drop `player_locations` (per-kill/plant positions of all 10 players). The stats never use
    them and they are most of a match's size, so dropping them keeps a shared cache small."""
    if isinstance(obj, dict):
        return {k: strip_positions(v) for k, v in obj.items() if k != "player_locations"}
    if isinstance(obj, list):
        return [strip_positions(v) for v in obj]
    return obj


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        with self._lock:
            return fn(self, *a, **k)
    return wrapper


class Cache:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = str(path)
        # The website shares one connection between visitor threads; every method takes the lock.
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    @_locked
    def close(self) -> None:
        self.conn.close()

    # ---- accounts -----------------------------------------------------------------
    @_locked
    def get_account(self, riot_id: str, max_age_s: float = 86400) -> dict | None:
        row = self.conn.execute(
            "SELECT payload, fetched_at FROM accounts WHERE riot_id_lower = ?",
            (riot_id.lower(),)).fetchone()
        if row and time.time() - row[1] <= max_age_s:
            return _unpack(row[0])
        return None

    @_locked
    def put_account(self, riot_id: str, account: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO accounts VALUES (?, ?, ?, ?, ?)",
            (riot_id.lower(), account["puuid"], account.get("region"), _pack(account), time.time()))
        self.conn.commit()

    # ---- matches ------------------------------------------------------------------
    @_locked
    def has_match(self, match_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone() is not None

    @_locked
    def missing_match_ids(self, match_ids: Iterable[str]) -> list[str]:
        return [m for m in match_ids if not self.has_match(m)]

    @_locked
    def put_match(self, match: dict) -> None:
        match = strip_positions(match)
        meta = match.get("metadata") or {}
        match_id = meta["match_id"]
        queue_id = (meta.get("queue") or {}).get("id")
        self.conn.execute(
            "INSERT OR REPLACE INTO matches VALUES (?, ?, ?, ?, ?)",
            (match_id, meta.get("started_at"), queue_id, _pack(match), time.time()))
        for p in match.get("players") or []:
            if p.get("puuid"):
                self.conn.execute("INSERT OR IGNORE INTO player_matches VALUES (?, ?)", (p["puuid"], match_id))
        self.conn.commit()

    @_locked
    def get_match(self, match_id: str) -> dict | None:
        row = self.conn.execute("SELECT payload FROM matches WHERE match_id = ?", (match_id,)).fetchone()
        return _unpack(row[0]) if row else None

    @_locked
    def get_player_matches(self, puuid: str, *, queue_id: str = "competitive", limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            """SELECT m.payload FROM matches m JOIN player_matches pm ON pm.match_id = m.match_id
               WHERE pm.puuid = ? AND m.queue_id = ? ORDER BY m.started_at DESC LIMIT ?""",
            (puuid, queue_id, limit)).fetchall()
        return [_unpack(r[0]) for r in rows]

    # ---- MMR ----------------------------------------------------------------------
    @_locked
    def put_mmr_history(self, puuid: str, entries: Iterable[dict]) -> int:
        n = 0
        for e in entries:
            mid = e.get("match_id")
            if not mid:
                continue
            self.conn.execute(
                "INSERT OR REPLACE INTO mmr_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (puuid, mid, e.get("date"), e.get("last_change"), e.get("rr"), e.get("elo"),
                 (e.get("tier") or {}).get("name"), (e.get("map") or {}).get("name"),
                 (e.get("season") or {}).get("short"), _pack(e)))
            n += 1
        self.conn.commit()
        return n

    @_locked
    def get_mmr_history(self, puuid: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM mmr_history WHERE puuid = ? ORDER BY date DESC", (puuid,)).fetchall()
        return [_unpack(r[0]) for r in rows]

    @_locked
    def put_mmr_current(self, puuid: str, mmr: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO mmr_current VALUES (?, ?, ?)", (puuid, _pack(mmr), time.time()))
        self.conn.commit()

    @_locked
    def get_mmr_current(self, puuid: str) -> tuple[dict, float] | None:
        row = self.conn.execute("SELECT payload, fetched_at FROM mmr_current WHERE puuid = ?", (puuid,)).fetchone()
        return (_unpack(row[0]), row[1]) if row else None
