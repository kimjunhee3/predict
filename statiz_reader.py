# -*- coding: utf-8 -*-
"""
원격 JSON(깃허브 raw) → /data/statiz_cache.json 로컬 캐시
- REMOTE_CACHE_URL에서 받아오고 /data에 저장
- 실패 시 레포에 번들된 statiz_cache.json을 폴백
- 'pred:YYYY-MM-DD[:s_no]' 구조 지원 (오늘자 없으면 "가장 최근 날짜"로 폴백)
- 과거 포맷 'predlist:YYYY-MM-DD'도 하위호환 지원
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

# ---------- 시간/경로 ----------
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

# ---------- 파일 유틸 ----------
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

# ---------- 캐시 로딩 ----------
def fetch_remote_into_cache(force: bool = False) -> Dict[str, Any]:
    """
    우선순위:
    1) /data/statiz_cache.json (TTL 내)
    2) REMOTE_CACHE_URL에서 받아와 /data에 저장
    3) 레포에 번들된 statiz_cache.json 사용
    """
    cache_path = _cache_path()

    # 1) 로컬 캐시 신선
    if not force and _is_fresh_file(cache_path, CACHE_TTL_MIN):
        data = _load_local_json(cache_path)
        if data:
            return data

    # 2) 원격 갱신
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

# ---------- 키 파싱/선택 ----------
def _parse_pred_key_date(key: str) -> Optional[str]:
    """
    'pred:YYYY-MM-DD[:s_no]' → 'YYYY-MM-DD'
    'predlist:YYYY-MM-DD'    → 'YYYY-MM-DD'
    's_nos:YYYY-MM-DD'       → 'YYYY-MM-DD'
    그 외는 None
    """
    if key.startswith("pred:") or key.startswith("predlist:") or key.startswith("s_nos:"):
        parts = key.split(":")
        if len(parts) >= 2:
            return parts[1]
    return None

def _available_dates(cache_json: Dict[str, Any]) -> List[str]:
    dates = set()
    for k in cache_json.keys():
        d = _parse_pred_key_date(k)
        if d:
            dates.add(d)
    # 날짜 문자열을 실제 날짜로 소팅
    def to_dt(s: str) -> datetime:
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return datetime.min
    return sorted(list(dates), key=to_dt)

def _pick_latest_date(cache_json: Dict[str, Any]) -> Optional[str]:
    dates = _available_dates(cache_json)
    return dates[-1] if dates else None

# ---------- 오늘 rows 조회 ----------
def _rows_from_predlist(cache_json: Dict[str, Any], date_str: str) -> List[Dict[str, Any]]:
    item = cache_json.get(f"predlist:{date_str}")
    if item and isinstance(item.get("data"), list):
        return item["data"]
    return []

def _rows_from_pred_snos(cache_json: Dict[str, Any], date_str: str) -> List[Dict[str, Any]]:
    """
    - s_nos:YYYY-MM-DD 가 있으면 거기 나열된 s_no 순서로
      pred:YYYY-MM-DD:<s_no> 의 data(dict) 를 모아 리스트로 반환
    - s_nos 키가 없으면 'pred:YYYY-MM-DD:' prefix 전체를 스캔해서 수집
    """
    results: List[Dict[str, Any]] = []

    # 1) s_nos 우선
    snos_key = f"s_nos:{date_str}"
    snos_obj = cache_json.get(snos_key)
    if isinstance(snos_obj, dict) and isinstance(snos_obj.get("data"), list):
        for s_no in snos_obj["data"]:
            k = f"pred:{date_str}:{s_no}"
            o = cache_json.get(k)
            if isinstance(o, dict) and isinstance(o.get("data"), dict):
                results.append(o["data"])

    if results:
        return results

    # 2) s_nos가 없으면 prefix 스캔
    prefix = f"pred:{date_str}:"
    collected = []
    for k, v in cache_json.items():
        if k.startswith(prefix) and isinstance(v, dict) and isinstance(v.get("data"), dict):
            # k = pred:YYYY-MM-DD:NNNNNN
            try:
                s_no = int(k.split(":")[2])
            except Exception:
                s_no = 0
            collected.append((s_no, v["data"]))
    if collected:
        collected.sort(key=lambda x: x[0])
        return [row for _, row in collected]

    return []

def get_pred_rows_for_date(cache_json: Dict[str, Any], date_str: str) -> List[Dict[str, Any]]:
    """
    지정 날짜의 경기 rows 반환 (최신 포맷/구포맷 모두 지원)
    우선순위: pred:* → predlist:*
    """
    rows = _rows_from_pred_snos(cache_json, date_str)
    if rows:
        return rows
    return _rows_from_predlist(cache_json, date_str)

def get_today_predlist(cache_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    오늘(KST) rows 반환. 없으면 가장 최근 날짜 rows 폴백.
    """
    today = _today_kst_str()
    rows = get_pred_rows_for_date(cache_json, today)
    if rows:
        return rows
    # 폴백: 사용 가능한 가장 최근 날짜
    latest = _pick_latest_date(cache_json)
    if latest:
        return get_pred_rows_for_date(cache_json, latest)
    return []

# ---------- 행 선택 ----------
def find_match_for_team(predlist_rows: List[Dict[str, Any]], team: str) -> Optional[Dict[str, Any]]:
    for r in predlist_rows:
        if team in (r.get("left_team"), r.get("right_team")):
            return r
    return None

__all__ = [
    "fetch_remote_into_cache",
    "get_today_predlist",
    "get_pred_rows_for_date",
    "find_match_for_team",
    "_today_kst_str",
]
