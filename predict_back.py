import os, re, json, time, logging
from typing import Dict, Any, List, Optional, Set
from flask import Flask, render_template, request
from bs4 import BeautifulSoup

# Selenium(Statiz) 켜기/끄기 스위치
STATIZ_ENABLE = os.getenv("STATIZ_ENABLE", "1") == "1"
if STATIZ_ENABLE:
    from statiz_predict import fetch_all_predictions_fast

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("predict")

FANVOTE_HTML_PATH = os.getenv("FANVOTE_HTML_PATH", "fanvote.html")
FANVOTE_CACHE_PATH = os.getenv("FANVOTE_CACHE_PATH", "fanvote_cache.json")
FANVOTE_TTL_MIN   = int(os.getenv("FANVOTE_TTL_MIN", "120"))

# 표준 팀명
TEAMS_STD = ["한화","LG","KT","두산","SSG","키움","KIA","NC","롯데","삼성"]

team_colors = {
    "한화":"#f37321","LG":"#c30452","KT":"#231f20","두산":"#13294b","SSG":"#d50032",
    "키움":"#5c0a25","KIA":"#d61c29","NC":"#1a419d","롯데":"#c9252c","삼성":"#0d3383"
}
player_img_map = {
    "한화":{"투수":"한화_투수.png","야수":"한화_야수.png"},
    "LG":{"투수":"엘지_투수.png","야수":"엘지_야수.png"},
    "KT":{"투수":"KT_투수.png","야수":"KT_야수.png"},
    "두산":{"투수":"두산_투수.png","야수":"두산_야수.png"},
    "SSG":{"투수":"SSG_투수.png","야수":"SSG_야수.png"},
    "키움":{"투수":"키움_투수.png","야수":"키움_야수.png"},
    "KIA":{"투수":"KIA_투수.png","야수":"KIA_야수.png"},
    "NC":{"투수":"NC_투수.png","야수":"NC_야수.png"},
    "롯데":{"투수":"롯데_투수.png","야수":"롯데_야수.png"},
    "삼성":{"투수":"삼성_투수.png","야수":"삼성_야수.png"},
}

# ---------- 헬스 체크 ----------
@app.route("/health")
def health():
    return "ok", 200

# ---------- 파일 캐시 유틸 ----------
def _load_cache(path: str) -> Dict[str, Any]:
    if not os.path.exists(path): return {}
    try:
        with open(path,"r",encoding="utf-8") as f: return json.load(f)
    except Exception:
        return {}

def _save_cache(path: str, obj: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(obj,f,ensure_ascii=False,indent=2)
    os.replace(tmp, path)

def _is_fresh(ts_iso: Optional[str], ttl_min: int) -> bool:
    if not ts_iso: return False
    try:
        ts = time.mktime(time.strptime(ts_iso, "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return False
    return (time.time() - ts) < ttl_min * 60

# ---------- 팀명 정규화 ----------
# 다양한 표기를 표준 표기로 변환
ALIAS = {
    "엘지":"LG","엘 지":"LG","lg":"LG","l g":"LG","lg트윈스":"LG","엘지트윈스":"LG",
    "케이티":"KT","kt":"KT","k t":"KT","kt위즈":"KT","케이티위즈":"KT",
    "기아":"KIA","kia":"KIA","k i a":"KIA","기아타이거즈":"KIA","kia타이거즈":"KIA",
    "엔씨":"NC","nc":"NC","n c":"NC","nc다이노스":"NC","엔씨다이노스":"NC",
    "에스에스지":"SSG","ssg":"SSG","s s g":"SSG","ssg랜더스":"SSG",
    "두산베어스":"두산","롯데자이언츠":"롯데","삼성라이온즈":"삼성",
    "키움히어로즈":"키움","한화이글스":"한화",
}
def normalize_team(name: Optional[str]) -> Optional[str]:
    if not name: return None
    n = re.sub(r"\s+", "", name.strip())   # 공백 제거
    n_low = n.lower()
    # 완전 매핑 먼저
    if n in ALIAS: return ALIAS[n]
    if n_low in ALIAS: return ALIAS[n_low]
    # 접두/접미 품사 제거(이글스/트윈스/베어스 등)
    n = re.sub(r"(트윈스|베어스|자이언츠|라이온즈|다이노스|랜더스|히어로즈|타이거즈|위즈|이글스)$", "", n)
    # 다시 매핑
    if n in ALIAS: return ALIAS[n]
    if n in TEAMS_STD: return n
    # 마지막: 앞/뒤 토큰 중 표준팀 포함되면 그걸 사용
    for t in TEAMS_STD:
        if t in name:
            return t
    return name  # 그대로 반환(최후수단)

# ---------- fanvote 파싱(+캐시) ----------
def _parse_fanvote_all(file_path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(file_path):
        log.warning("fanvote.html not found at %s", file_path)
        return []
    with open(file_path,"r",encoding="utf-8") as f:
        soup = BeautifulSoup(f,"html.parser")
    boxes = soup.select("div[class^='MatchBox_match_box']") \
            or soup.find_all("div", class_=re.compile(r"^MatchBox_match_box"))
    out=[]
    for b in boxes:
        teams_ = b.find_all("div", class_=re.compile(r"^MatchBox_name"))
        perc   = b.select("em[class^='MatchBox_rate'] span[class^='MatchBox_number']")
        if len(teams_)==2 and len(perc)==2:
            t1_raw = teams_[0].get_text(strip=True)
            t2_raw = teams_[1].get_text(strip=True)
            t1 = normalize_team(t1_raw)
            t2 = normalize_team(t2_raw)
            try:
                out.append({
                    "team1": t1,
                    "team2": t2,
                    "percent1": float(perc[0].get_text(strip=True).replace('%','').strip()),
                    "percent2": float(perc[1].get_text(strip=True).replace('%','').strip()),
                })
            except Exception as e:
                log.warning("fanvote row skip: %s", e)
    return out

def _ensure_fanvote_cache() -> Dict[str, Any]:
    cache = _load_cache(FANVOTE_CACHE_PATH)
    src_mtime = os.path.getmtime(FANVOTE_HTML_PATH) if os.path.exists(FANVOTE_HTML_PATH) else None
    need = True
    if cache and _is_fresh(cache.get("ts"), FANVOTE_TTL_MIN):
        if (src_mtime is None and cache.get("src_mtime") is None) or (src_mtime == cache.get("src_mtime")):
            need = False
    if need:
        data = _parse_fanvote_all(FANVOTE_HTML_PATH)
        cache = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "src_mtime": src_mtime,
            "data": data,
        }
        _save_cache(FANVOTE_CACHE_PATH, cache)
        log.info("fanvote cache refreshed: %d rows", len(data))
    return cache

def get_naver_match_for_team(team_name: str) -> Optional[Dict[str, Any]]:
    cache = _ensure_fanvote_cache()
    for row in cache.get("data", []):
        if team_name in (row["team1"], row["team2"]):
            r = dict(row)
            r["percent1_str"] = f"{r['percent1']:.1f}%"
            r["percent2_str"] = f"{r['percent2']:.1f}%"
            return r
    return None

def available_naver_teams() -> Set[str]:
    """fanvote 데이터에 등장하는 표준팀명 집합."""
    cache = _ensure_fanvote_cache()
    s: Set[str] = set()
    for r in cache.get("data", []):
        if r.get("team1"): s.add(r["team1"])
        if r.get("team2"): s.add(r["team2"])
    return s

# ---------- 메인 뷰 ----------
@app.route("/", methods=["GET", "POST"])
def index():
    # 1) 오늘 사용 가능한 팀 목록을 먼저 계산(네이버 기준, 없으면 빈)
    nav_teams = list(available_naver_teams())

    # 2) 사용자가 선택했으면 그걸 쓰고, 아니면 '실제로 존재하는 팀' 중 첫 팀으로 자동 선택
    if request.method == "POST":
        selected_team = request.form.get("team")
    else:
        selected_team = nav_teams[0] if nav_teams else TEAMS_STD[0]

    # NAVER
    naver_match = None
    try:
        naver_match = get_naver_match_for_team(selected_team)
    except Exception as e:
        log.exception("naver parse failed: %s", e)

    # STATIZ
    statiz_match = None
    if STATIZ_ENABLE:
        try:
            rows = fetch_all_predictions_fast(
                headless=True, use_cache=True, ttl_minutes=30, force_refresh=False, fill_detail=True
            )
            # 팀명 정규화 후 비교(혹시 표기가 다를 경우)
            def norm(x): return normalize_team(x) if x else x
            statiz_match = next((m for m in rows
                                if selected_team in [norm(m.get("left_team")), norm(m.get("right_team"))]), None)
            if statiz_match:
                lp = float(statiz_match.get("left_percent") or 0.0)
                rp = float(statiz_match.get("right_percent") or 0.0)
                statiz_match["left_percent"]  = round(lp, 1)
                statiz_match["right_percent"] = round(rp, 1)
                statiz_match["left_percent_str"]  = f"{statiz_match['left_percent']:.1f}%"
                statiz_match["right_percent_str"] = f"{statiz_match['right_percent']:.1f}%"
        except Exception as e:
            log.exception("statiz fetch failed: %s", e)

    # 화면에 뿌릴 팀 목록: 오늘 실제로 있는 팀이 있으면 그 리스트를 우선 노출
    teams_for_select = nav_teams if nav_teams else TEAMS_STD

    return render_template(
        "predict.html",
        teams=teams_for_select,
        selected_team=selected_team,
        statiz=statiz_match,
        naver=naver_match,
        team_colors=team_colors,
        player_img_map=player_img_map,
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
