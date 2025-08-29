# -*- coding: utf-8 -*-
"""
원격에 올려둔 statiz_cache.json을 읽어오는 모듈
- REMOTE_CACHE_URL 에서 JSON을 받아 /data/statiz_cache.json 에 저장(캐시)
- predlist:<YYYY-MM-DD> 의 data 배열을 읽어 오늘자(또는 최신)의 경기 리스트 반환
"""

import os
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import requests

# -----------------------------
# 환경설정
# -----------------------------
REMOTE_CACHE_URL = os.environ.get("REMOTE_CACHE_URL", "")  # e.g. https://raw.githubusercontent.com/<user>/<repo>/main/statiz_cache.json
CACHE_TTL_MIN = int(os.environ.get("CACHE_TTL_MIN", "30"))

def _cache_path() -> str:
    cache_dir = os.environ.get("CACHE_DIR") or ("/data" if os.path.isdir("/data") else ".")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "statiz_cache.json")

def _now_kst() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(hours=9)

def _today_kst_str() -> str:
    return _now_kst().strftime("%Y-%m-%d")

# -----------------------------
# I/O
# -----------------------------
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

# -----------------------------
# 원격 가져오기(+캐시)
# -----------------------------
def _is_fresh_file(path: str, ttl_minutes: int) -> bool:
    try:
        mtime = os.path.getmtime(path)
        age = time.time() - mtime
        return age < ttl_minutes * 60
    except Exception:
        return False

def fetch_remote_into_cache(force: bool = False) -> Dict[str, Any]:
    """
    REMOTE_CACHE_URL -> /data/statiz_cache.json
    - force=False면 TTL 내에는 로컬 캐시 그대로 사용
    """
    path = _cache_path()
    if not REMOTE_CACHE_URL:
        # 원격 주소가 없으면 로컬만 반환
        return _load_local_json(path)

    if (not force) and _is_fresh_file(path, CACHE_TTL_MIN):
        return _load_local_json(path)

    try:
        r = requests.get(REMOTE_CACHE_URL, timeout=12)
        r.raise_for_status()
        data = r.json()
        _save_local_json(path, data)
        return data
    except Exception:
        # 원격 실패 시 로컬 캐시라도 반환
        return _load_local_json(path)

# -----------------------------
# 조회 유틸
# -----------------------------
def _pick_latest_predlist_key(cache_json: Dict[str, Any]) -> Optional[str]:
    """predlist:<date> 키들 중 '최신 날짜'를 선택"""
    keys = [k for k in cache_json.keys() if k.startswith("predlist:")]
    if not keys:
        return None
    # 키에서 날짜 추출
    def key_date(k: str) -> datetime:
        try:
            ds = k.split(":")[1]
            return datetime.strptime(ds, "%Y-%m-%d")
        except Exception:
            return datetime.min
    keys.sort(key=lambda k: key_date(k), reverse=True)
    return keys[0]

def get_today_predlist(cache_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    1) 오늘자 predlist:<YYYY-MM-DD> 있으면 그 data 반환
    2) 없으면 최신 predlist:* 의 data 반환
    """
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
    """predlist data 배열에서 특정 팀이 포함된 한 경기(row)를 찾아 반환"""
    for r in predlist_rows:
        lt, rt = r.get("left_team"), r.get("right_team")
        if team == lt or team == rt:
            return r
    return None
