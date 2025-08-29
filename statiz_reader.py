# -*- coding: utf-8 -*-
"""
원격 JSON(깃허브 raw 등) → /data/statiz_cache.json 로컬 캐시
- REMOTE_CACHE_URL에서 받아오고 /data에 저장
- 실패 시 레포에 번들된 statiz_cache.json을 폴백
- predlist:<YYYY-MM-DD>의 data 배열을 오늘자(없으면 최신)로 반환
"""
import os
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import requests

REMOTE_CACHE_URL = os.environ.get("REMOTE_CACHE_URL", "")
CACHE_TTL_MIN = int(os.environ.get("CACHE_TTL_MIN", "30"))
BUNDLED_CACHE_PATH = os.environ.get("BUNDLED_CACHE_PATH", "statiz_cache.json")

def _now_kst() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(hours=9)

def _today_kst_str() -> str:
    return _now_kst().strftime("%Y-%m-%d")

def _cache_dir() -> str:
    path = os.environ.get("CACHE_DIR") or ("/data" if os.path.isdir("/data") else ".")
    os.makedirs(path, exist_ok=True)
    return path

def _cache_path() -> str:
    return os.path.join(_cache_dir(), "statiz_cache.json")

def _is_fresh_file(path: str, ttl_minutes: int) -> bool:
    try:
        mtime = os.path.getmtime(path)
        return (time.time() - mtime) < ttl_minutes * 60
    except Exception:
        return False

def _load_local_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_local_json(path: str, data: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def fetch_remote_into_cache(force: bool = False) -> Dict[str, Any]:
    """
    우선순위:
    1) /data/statiz_cache.json (TTL 내)
    2) REMOTE_CACHE_URL에서 받아와 /data에 저장
    3) 레포에 번들된 statiz_cache.json 사용
    """
    cache_path = _cache_path()

    # 1) 로컬 캐시 신선하면 우선
    if not force and _is_fresh_file(cache_path, CACHE_TTL_MIN):
        data = _load_local_json(cache_path)
        if data:
            return data

    # 2) 원격
    if REMOTE_CACHE_URL:
        try:
            r = requests.get(REMOTE_CACHE_URL, timeout=12)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data:
                _save_local_json(cache_path, data)
                return data
        except Exception:
            pass

    # 3) 번들 폴백
    bundled = _load_local_json(BUNDLED_CACHE_PATH)
    if bundled:
        _save_local_json(cache_path, bundled)
        return bundled

    return {}

def _pick_latest_predlist_key(cache_json: Dict[str, Any]) -> Optional[str]:
    keys = [k for k in cache_json.keys() if k.startswith("predlist:")]
    if not keys:
        return None
    def to_dt(k: str) -> datetime:
        try:
            return datetime.strptime(k.split(":")[1], "%Y-%m-%d")
        except Exception:
            return datetime.min
    keys.sort(key=lambda k: to_dt(k), reverse=True)
    return keys[0]

def get_today_predlist(cache_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    today_key = f"predlist:{_today_kst_str()}"
    item = cache_json.get(today_key)
    if item and isinstance(item.get("data"), list):
        return item["data"]
    latest_key = _pick_latest_predlist_key(cache_json)
    if latest_key:
        item = cache_json.get(latest_key)
        if item and isinstance(item.get("data"), list):
            return item["data"]
    return []

def find_match_for_team(predlist_rows: List[Dict[str, Any]], team: str) -> Optional[Dict[str, Any]]:
    for r in predlist_rows:
        if team in (r.get("left_team"), r.get("right_team")):
            return r
    return None

__all__ = [
    "fetch_remote_into_cache", "get_today_predlist", "find_match_for_team", "_today_kst_str"
]
