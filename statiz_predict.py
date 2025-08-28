# -*- coding: utf-8 -*-
"""
Statiz 승부예측 크롤러 + 파일 캐시
- pred:<YYYY-MM-DD>:<s_no>  : 단일 경기 상세(팀/퍼센트/텍스트)
- predlist:<YYYY-MM-DD>      : '완전한' 목록(팀2 + 퍼센트2 모두 있을 때만 저장)
"""

import json
import os
import re
import time
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone

# 셀레니움은 '필요할 때만' 로드되도록 import를 함수 안으로 미룸
# (서버에서는 predlist 캐시만 있으면 여기까지 오지도 않음)

BASE_URL = "https://statiz.sporki.com/prediction/"
CACHE_PATH = "statiz_cache.json"
DEFAULT_TTL_MIN = 30

# -------------------- 시간/캐시 유틸 --------------------

def _now_kst() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(hours=9)

def _today_kst_str() -> str:
    return _now_kst().strftime("%Y-%m-%d")

def _load_cache() -> Dict[str, Any]:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_cache(cache: Dict[str, Any]) -> None:
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE_PATH)

def _is_fresh(item: Dict[str, Any], ttl_minutes: int) -> bool:
    try:
        ts = datetime.fromisoformat(item.get("ts"))
    except Exception:
        return False
    return (_now_kst() - ts) < timedelta(minutes=ttl_minutes)

# -------------------- 셀레니움 헬퍼 --------------------

def _make_driver(headless: bool = True):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1600")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=opts)   # Selenium Manager 사용
    driver.set_page_load_timeout(30)
    return driver

# -------------------- 파싱 유틸 --------------------

def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _extract_percent(txt: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", txt or "")
    return float(m.group(1)) if m else None

def _percent_from_style(style: str) -> Optional[float]:
    m = re.search(r"width:\s*(\d+(?:\.\d+)?)\s*%", style or "")
    return float(m.group(1)) if m else None

# -------------------- s_no 목록 --------------------

def generate_s_no_list(headless=True, use_cache=True, ttl_minutes=DEFAULT_TTL_MIN, force_refresh=False) -> List[str]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    cache = _load_cache()
    day_key = _today_kst_str()
    cache_key = f"s_nos:{day_key}"

    if use_cache and not force_refresh:
        item = cache.get(cache_key)
        if item and _is_fresh(item, ttl_minutes):
            return list(item["data"])

    driver = _make_driver(headless=headless)
    try:
        driver.get(BASE_URL)
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.swiper-slide.item"))
        )

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(0.6)
        driver.execute_script("window.scrollTo(0, 0);"); time.sleep(0.2)

        slides = driver.find_elements(By.CSS_SELECTOR, "div.swiper-slide.item")
        s_nos = []
        for sl in slides:
            try:
                onclick = sl.find_element(By.CSS_SELECTOR, "a[onclick]").get_attribute("onclick") or ""
                m = re.search(r"s_no=(\d+)", onclick)
                if m:
                    s_nos.append(m.group(1))
            except Exception:
                pass

        uniq, seen = [], set()
        for s in s_nos:
            if s not in seen:
                seen.add(s); uniq.append(s)

        if use_cache:
            cache[cache_key] = {"ts": _now_kst().isoformat(timespec="seconds"), "data": uniq}
            _save_cache(cache)

        return uniq
    finally:
        driver.quit()

# -------------------- 단일 경기 상세 --------------------

def _parse_single_prediction(driver, s_no: str) -> Dict:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    url = f"{BASE_URL}?s_no={s_no}"
    driver.get(url)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.predict, .team_name"))
        )
    except TimeoutException:
        pass

    left_team = right_team = None
    try:
        left = driver.find_element(By.CSS_SELECTOR, ".team_name .left.team_item")
        right = driver.find_element(By.CSS_SELECTOR, ".team_name .right.team_item")
        lt = _clean_text(left.get_attribute("innerText"))
        rt = _clean_text(right.get_attribute("innerText"))
        left_team = lt.split()[-1] if lt else None
        right_team = rt.split()[0] if rt else None
    except Exception:
        pass

    left_percent = right_percent = None
    try:
        litem = driver.find_element(By.CSS_SELECTOR, ".predict .p_item.left")
        ritem = driver.find_element(By.CSS_SELECTOR, ".predict .p_item.right")
        left_percent  = _extract_percent(_clean_text(litem.text))  or _percent_from_style(litem.get_attribute("style"))
        right_percent = _extract_percent(_clean_text(ritem.text))  or _percent_from_style(ritem.get_attribute("style"))
    except Exception:
        pass

    predict_text = None
    try:
        predict_text = _clean_text(driver.find_element(By.CSS_SELECTOR, "div.predict_text").get_attribute("innerText"))
    except Exception:
        predict_text = None

    return {
        "s_no": s_no,
        "url": url,
        "left_team": left_team,
        "right_team": right_team,
        "left_percent": float(left_percent) if left_percent is not None else None,
        "right_percent": float(right_percent) if right_percent is not None else None,
        "predict_text": predict_text,
    }

# -------------------- 목록 페이지 (predlist는 완전할 때만 저장) --------------------

def scrape_list_page_predictions(headless=True, use_cache=True, ttl_minutes=DEFAULT_TTL_MIN, force_refresh=False) -> List[Dict]:
    cache = _load_cache()
    day_key = _today_kst_str()
    cache_key = f"predlist:{day_key}"

    # 캐시가 있으면 바로 반환(서버에서는 여기서 끝 → 셀레니움 안 씀)
    if use_cache and not force_refresh:
        item = cache.get(cache_key)
        if item and _is_fresh(item, ttl_minutes):
            return list(item["data"])

    # 여기부터는 실제 크롤링
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = _make_driver(headless=headless)
    rows: List[Dict] = []
    try:
        driver.get(BASE_URL)
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.swiper-slide.item"))
        )

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(0.6)
        driver.execute_script("window.scrollTo(0, 0);"); time.sleep(0.2)

        slides = driver.find_elements(By.CSS_SELECTOR, "div.swiper-slide.item")
        for sl in slides:
            s_no = None
            try:
                onclick = sl.find_element(By.CSS_SELECTOR, "a[onclick]").get_attribute("onclick") or ""
                m = re.search(r"s_no=(\d+)", onclick)
                if m:
                    s_no = m.group(1)
            except Exception:
                pass

            left_team = right_team = None
            left_percent = right_percent = None
            try:
                left = sl.find_element(By.CSS_SELECTOR, ".team_name .left.team_item")
                right = sl.find_element(By.CSS_SELECTOR, ".team_name .right.team_item")
                lt = _clean_text(left.get_attribute("innerText"))
                rt = _clean_text(right.get_attribute("innerText"))
                left_team  = lt.split()[-1] if lt else None
                right_team = rt.split()[0] if rt else None
            except Exception:
                pass
            try:
                litem = sl.find_element(By.CSS_SELECTOR, ".predict .p_item.left")
                ritem = sl.find_element(By.CSS_SELECTOR, ".predict .p_item.right")
                left_percent  = _extract_percent(_clean_text(litem.text))  or _percent_from_style(litem.get_attribute("style"))
                right_percent = _extract_percent(_clean_text(ritem.text))  or _percent_from_style(ritem.get_attribute("style"))
            except Exception:
                pass

            if s_no:
                rows.append({
                    "s_no": s_no,
                    "url": f"{BASE_URL}?s_no={s_no}",
                    "left_team": left_team,
                    "right_team": right_team,
                    "left_percent": float(left_percent) if left_percent is not None else None,
                    "right_percent": float(right_percent) if right_percent is not None else None,
                    "predict_text": None,
                })

        # 중복 제거
        uniq, seen = [], set()
        for r in rows:
            if r["s_no"] in seen:
                continue
            seen.add(r["s_no"]); uniq.append(r)

        # ✅ 팀/퍼센트 모두 있는 '완전한' 경우에만 predlist 저장
        complete = [
            r for r in uniq
            if r.get("left_team") and r.get("right_team")
            and r.get("left_percent") is not None and r.get("right_percent") is not None
        ]
        if use_cache and complete and len(complete) == len(uniq):
            cache[cache_key] = {"ts": _now_kst().isoformat(timespec="seconds"), "data": complete}
            _save_cache(cache)

        return uniq
    finally:
        driver.quit()

# -------------------- 상세 보완 + 최종 predlist 기록 --------------------

def fetch_predictions(s_no_list: List[str], headless=True, use_cache=True, ttl_minutes=DEFAULT_TTL_MIN, force_refresh=False) -> List[Dict]:
    if not s_no_list:
        return []

    cache = _load_cache()
    day_key = _today_kst_str()

    cached: Dict[str, Dict] = {}
    misses: List[str] = []
    for s_no in s_no_list:
        key = f"pred:{day_key}:{s_no}"
        item = cache.get(key)
        if use_cache and (not force_refresh) and item and _is_fresh(item, ttl_minutes):
            cached[s_no] = item["data"]
        else:
            misses.append(s_no)

    if misses:
        driver = _make_driver(headless=headless)
        try:
            for s_no in misses:
                data = _parse_single_prediction(driver, s_no)
                for k in ("left_percent", "right_percent"):
                    if data.get(k) is not None:
                        try:
                            data[k] = float(data[k])
                        except Exception:
                            data[k] = None
                if use_cache:
                    cache[f"pred:{day_key}:{s_no}"] = {"ts": _now_kst().isoformat(timespec="seconds"), "data": data}
                cached[s_no] = data
                time.sleep(0.3)
        finally:
            _save_cache(cache)
            driver.quit()

    return [cached[s_no] for s_no in s_no_list if s_no in cached]

def fetch_all_predictions_fast(headless=True, use_cache=True, ttl_minutes=DEFAULT_TTL_MIN, force_refresh=False, fill_detail=True) -> List[Dict]:
    rows = scrape_list_page_predictions(
        headless=headless, use_cache=use_cache, ttl_minutes=ttl_minutes, force_refresh=force_refresh
    )

    if not fill_detail:
        return rows

    need = []
    for r in rows:
        if (r.get("left_percent") is None or r.get("right_percent") is None
            or r.get("left_team") is None or r.get("right_team") is None
            or r.get("predict_text") is None):
            need.append(r["s_no"])

    detailed = {}
    if need:
        detailed = {d["s_no"]: d for d in fetch_predictions(
            need, headless=headless, use_cache=use_cache, ttl_minutes=ttl_minutes, force_refresh=force_refresh
        )}

    merged = []
    for base in rows:
        dn = detailed.get(base["s_no"])
        out = dict(base)
        if dn:
            for k in ("left_team", "right_team", "left_percent", "right_percent", "predict_text"):
                if out.get(k) is None and dn.get(k) is not None:
                    out[k] = dn[k]
        merged.append(out)

    # 최종 병합본이 '완전'하면 predlist 저장(텍스트는 없어도 OK)
    complete = [
        r for r in merged
        if r.get("left_team") and r.get("right_team")
        and r.get("left_percent") is not None and r.get("right_percent") is not None
    ]
    if use_cache and complete and len(complete) == len(merged):
        cache = _load_cache()
        cache[f"predlist:{_today_kst_str()}"] = {"ts": _now_kst().isoformat(timespec="seconds"), "data": complete}
        _save_cache(cache)

    return merged
