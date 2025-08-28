import json
import os
import re
import time
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

BASE_URL = "https://statiz.sporki.com/prediction/"
CACHE_PATH = "statiz_cache.json"          # 캐시 파일 경로
DEFAULT_TTL_MIN = int(os.getenv("STATIZ_TTL_MIN", "30"))

# ===================== 시간/캐시 유틸 =====================

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

def clear_cache():
    if os.path.exists(CACHE_PATH):
        os.remove(CACHE_PATH)

# ===================== Selenium 드라이버 =====================

def _make_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    # Dockerfile에서 지정한 바이너리 경로 사용
    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        opts.binary_location = chrome_bin

    if headless:
        # chromium 최신 headless
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1600")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    # /usr/bin/chromedriver 가 PATH에 있으므로 별도 Service 지정 불필요
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(30)
    return driver

# ===================== 파싱 유틸 =====================

def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _extract_percent(txt: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", txt or "")
    return float(m.group(1)) if m else None

def _percent_from_style(style: str) -> Optional[float]:
    m = re.search(r"width:\s*(\d+(?:\.\d+)?)\s*%", style or "")
    return float(m.group(1)) if m else None

# ===================== s_no 수집(+캐시) =====================

def generate_s_no_list(
    headless: bool = True,
    use_cache: bool = True,
    ttl_minutes: int = DEFAULT_TTL_MIN,
    force_refresh: bool = False,
) -> List[str]:
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
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.6)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.2)

        slides = driver.find_elements(By.CSS_SELECTOR, "div.swiper-slide.item")
        s_nos = []
        for sl in slides:
            try:
                onclick = sl.find_element(By.CSS_SELECTOR, "a[onclick]").get_attribute("onclick") or ""
                m = re.search(r"s_no=(\d+)", onclick)
                if m:
                    s_nos.append(m.group(1))
            except NoSuchElementException:
                pass

        seen, uniq = set(), []
        for s in s_nos:
            if s not in seen:
                seen.add(s); uniq.append(s)

        if use_cache:
            cache[cache_key] = {"ts": _now_kst().isoformat(timespec="seconds"), "data": uniq}
            _save_cache(cache)

        return uniq
    finally:
        driver.quit()

# ===================== 단일 경기 파싱(상세) =====================

def _parse_single_prediction(driver, s_no: str) -> Dict:
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
        left_team_txt = _clean_text(left.get_attribute("innerText"))
        right_team_txt = _clean_text(right.get_attribute("innerText"))
        left_team = left_team_txt.split()[-1] if left_team_txt else None
        right_team = right_team_txt.split()[0] if right_team_txt else None
    except NoSuchElementException:
        pass

    left_percent = right_percent = None
    try:
        left_item = driver.find_element(By.CSS_SELECTOR, ".predict .p_item.left")
        right_item = driver.find_element(By.CSS_SELECTOR, ".predict .p_item.right")

        left_percent = _extract_percent(_clean_text(left_item.text))
        right_percent = _extract_percent(_clean_text(right_item.text))
        if left_percent is None:
            left_percent = _percent_from_style(left_item.get_attribute("style"))
        if right_percent is None:
            right_percent = _percent_from_style(right_item.get_attribute("style"))
    except NoSuchElementException:
        pass

    predict_text = None
    try:
        predict_text = _clean_text(
            driver.find_element(By.CSS_SELECTOR, "div.predict_text").get_attribute("innerText")
        )
    except NoSuchElementException:
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

# ===================== 목록 페이지에서 긁기 =====================

def scrape_list_page_predictions(
    headless: bool = True,
    use_cache: bool = True,
    ttl_minutes: int = DEFAULT_TTL_MIN,
    force_refresh: bool = False,
) -> List[Dict]:
    cache = _load_cache()
    day_key = _today_kst_str()
    cache_key = f"predlist:{day_key}"

    if use_cache and not force_refresh:
        item = cache.get(cache_key)
        if item and _is_fresh(item, ttl_minutes):
            return list(item["data"])

    driver = _make_driver(headless=headless)
    rows: List[Dict] = []
    try:
        driver.get(BASE_URL)
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.swiper-slide.item"))
        )

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.6)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.2)

        slides = driver.find_elements(By.CSS_SELECTOR, "div.swiper-slide.item")
        for sl in slides:
            s_no = None
            try:
                onclick = sl.find_element(By.CSS_SELECTOR, "a[onclick]").get_attribute("onclick") or ""
                m = re.search(r"s_no=(\d+)", onclick)
                if m:
                    s_no = m.group(1)
            except NoSuchElementException:
                pass

            left_team = right_team = None
            try:
                left = sl.find_element(By.CSS_SELECTOR, ".team_name .left.team_item")
                right = sl.find_element(By.CSS_SELECTOR, ".team_name .right.team_item")
                lt = _clean_text(left.get_attribute("innerText"))
                rt = _clean_text(right.get_attribute("innerText"))
                left_team = lt.split()[-1] if lt else None
                right_team = rt.split()[0] if rt else None
            except NoSuchElementException:
                pass

            left_percent = right_percent = None
            try:
                litem = sl.find_element(By.CSS_SELECTOR, ".predict .p_item.left")
                ritem = sl.find_element(By.CSS_SELECTOR, ".predict .p_item.right")
                left_percent = _extract_percent(_clean_text(litem.text))
                right_percent = _extract_percent(_clean_text(ritem.text))
                if left_percent is None:
                    left_percent = _percent_from_style(litem.get_attribute("style"))
                if right_percent is None:
                    right_percent = _percent_from_style(ritem.get_attribute("style"))
            except NoSuchElementException:
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

        uniq_rows, seen = [], set()
        for r in rows:
            key = r["s_no"]
            if key in seen: 
                continue
            seen.add(key)
            uniq_rows.append(r)

        if use_cache:
            cache[cache_key] = {"ts": _now_kst().isoformat(timespec="seconds"), "data": uniq_rows}
            _save_cache(cache)

        return uniq_rows
    finally:
        driver.quit()

# ===================== 상세 보완 + 캐시 저장 =====================

def fetch_predictions(
    s_no_list: List[str],
    headless: bool = True,
    use_cache: bool = True,
    ttl_minutes: int = DEFAULT_TTL_MIN,
    force_refresh: bool = False,
) -> List[Dict]:
    if not s_no_list:
        return []

    cache = _load_cache()
    day_key = _today_kst_str()

    cached_data: Dict[str, Dict] = {}
    misses: List[str] = []
    for s_no in s_no_list:
        cache_key = f"pred:{day_key}:{s_no}"
        item = cache.get(cache_key)
        if use_cache and (not force_refresh) and item and _is_fresh(item, ttl_minutes):
            cached_data[s_no] = item["data"]
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
                    cache_key = f"pred:{day_key}:{s_no}"
                    cache[cache_key] = {
                        "ts": _now_kst().isoformat(timespec="seconds"),
                        "data": data,
                    }
                cached_data[s_no] = data
                time.sleep(0.3)
        finally:
            _save_cache(cache)
            driver.quit()

    return [cached_data[s_no] for s_no in s_no_list if s_no in cached_data]

# ===================== 하이브리드: 목록 긁고 누락 상세 보완 =====================

def fetch_all_predictions_fast(
    headless: bool = True,
    use_cache: bool = True,
    ttl_minutes: int = DEFAULT_TTL_MIN,
    force_refresh: bool = False,
    fill_detail: bool = True,
) -> List[Dict]:
    rows = scrape_list_page_predictions(
        headless=headless,
        use_cache=use_cache,
        ttl_minutes=ttl_minutes,
        force_refresh=force_refresh,
    )

    if not fill_detail:
        return rows

    need_snos: List[str] = []
    for r in rows:
        if r.get("left_percent") is None or r.get("right_percent") is None \
           or r.get("left_team") is None or r.get("right_team") is None \
           or r.get("predict_text") is None:
            need_snos.append(r["s_no"])

    if not need_snos:
        return rows

    detailed = {d["s_no"]: d for d in fetch_predictions(
        need_snos,
        headless=headless,
        use_cache=use_cache,
        ttl_minutes=ttl_minutes,
        force_refresh=force_refresh,
    )}

    merged: List[Dict] = []
    for base in rows:
        dn = detailed.get(base["s_no"])
        if not dn:
            merged.append(base); continue
        out = dict(base)
        for k in ("left_team", "right_team", "left_percent", "right_percent", "predict_text"):
            if out.get(k) is None and dn.get(k) is not None:
                out[k] = dn[k]
        merged.append(out)
    return merged
